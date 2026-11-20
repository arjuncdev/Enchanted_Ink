"""Prepare line-image manifests and train/evaluate a TrOCR model.

Linux example (replace DATA_ROOT with the extracted dataset directory):
  python training/trocr_iam.py prepare --iam-root "$DATA_ROOT" --manifest "$HOME/iam-lines.csv"
  python training/trocr_iam.py train --manifest "$HOME/iam-lines.csv" --output "$HOME/trocr-output"

Colab may use /content paths; those paths do not exist on a local Linux machine.

This script does not download or redistribute dataset files.
"""
import argparse
import csv
import json
import math
import os
import random
import re
import subprocess
import time
from pathlib import Path


def prepare_manifest(iam_root: str, output_csv: str) -> int:
    root = Path(iam_root).expanduser()
    if not root.is_dir():
        raise FileNotFoundError(
            f"Dataset root is not a directory: {root}. Download and extract the dataset first, "
            "then pass the extracted folder containing lines.txt and its line images. "
            "The /content path is for Google Colab, not a local Linux machine."
        )
    annotation_files = sorted(root.rglob("lines.txt"))
    if not annotation_files:
        raise FileNotFoundError(
            f"Could not find lines.txt under dataset root: {root}. Check that the "
            "annotation archive is downloaded and extracted; --iam-root must "
            "point to the extracted dataset folder, not the archive or an image-only folder."
        )
    output_path = Path(output_csv).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with output_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["image_path", "text", "writer_id"])
        writer.writeheader()
        for annotation in annotation_files:
            for line in annotation.read_text(encoding="utf-8").splitlines():
                if not line or line.startswith("#"):
                    continue
                fields = line.split()
                if len(fields) < 9 or fields[1] == "err":
                    continue
                line_id = fields[0]
                text_start = 9 if len(fields) > 9 and all(
                    field.lower() == "x" for field in fields[1:9]
                ) else 8
                text = " ".join(" ".join(fields[text_start:]).replace("|", " ").split())
                if not text or len(text) > 1000:
                    continue
                candidates = [root / "lines" / line_id.split("-")[0] / f"{line_id}.png",
                              annotation.parent / "lines" / line_id.split("-")[0] / f"{line_id}.png"]
                image_path = next((p for p in candidates if p.is_file()), None)
                if image_path is None:
                    matches = list(root.rglob(f"{line_id}.png"))
                    image_path = matches[0] if matches else None
                if image_path is None:
                    continue
                line_id_parts = line_id.split("-")
                writer_id = line_id_parts[1] if len(line_id_parts) >= 4 else "unknown"
                writer.writerow({"image_path": str(image_path.resolve()), "text": text,
                                 "writer_id": writer_id})
                count += 1
    if not count:
        raise ValueError("No labeled line images found; check the extracted dataset layout")
    return count


def _form_text_lines(image):
    """Find handwritten body rows below the printed reference paragraph."""
    import numpy as np

    gray = np.asarray(image.convert("L"))
    height, width = gray.shape
    left, right = int(width * 0.12), int(width * 0.91)
    top, bottom = int(height * 0.17), int(height * 0.86)
    ink = gray[top:bottom, left:right] < 150
    row_counts = ink.sum(axis=1)
    lower_rule_rows = []

    # The full-width form rules are not handwriting rows.
    for row_index, row in enumerate(ink):
        dark_columns = np.flatnonzero(row)
        if not len(dark_columns):
            continue
        runs = np.split(dark_columns, np.flatnonzero(np.diff(dark_columns) > 1) + 1)
        longest_run = max(len(run) for run in runs)
        if longest_run > row.shape[0] * 0.2:
            if top + row_index > height * 0.55:
                lower_rule_rows.append(row_index)
            ink[row_index] = False
            row_counts[row_index] = 0

    if lower_rule_rows:
        content_end = max(0, min(lower_rule_rows) - 5)
        ink[content_end:] = False
        row_counts[content_end:] = 0

    threshold = max(12, int((right - left) * 0.006))
    active_rows = np.flatnonzero(row_counts >= threshold)
    groups = []
    if len(active_rows):
        start = previous = int(active_rows[0])
        for value in active_rows[1:]:
            value = int(value)
            if value - previous > 32:
                groups.append((start, previous))
                start = value
            previous = value
        groups.append((start, previous))

    line_crops = []
    for first, last in groups:
        if last - first + 1 < 15:
            continue
        region = ink[first:last + 1]
        active_columns = np.flatnonzero(region.sum(axis=0) >= 2)
        if not len(active_columns):
            continue
        x0 = max(0, int(active_columns[0]) - 14)
        x1 = min(region.shape[1], int(active_columns[-1]) + 15)
        y0 = max(0, first - 18)
        y1 = min(ink.shape[0], last + 19)
        crop = image.crop((left + x0, top + y0, left + x1, top + y1))
        line_crops.append(crop)
    return line_crops


def _ocr_printed_reference(image, image_path: Path) -> str:
    """Read the printed transcript at the top of a Kaggle IAM form."""
    import io

    width, height = image.size
    reference = image.crop((
        int(width * 0.13), int(height * 0.085),
        int(width * 0.91), int(height * 0.17),
    )).convert("L")
    output = io.BytesIO()
    reference.save(output, format="PNG")
    try:
        result = subprocess.run(
            ["tesseract", "stdin", "stdout", "--psm", "6"],
            input=output.getvalue(),
            capture_output=True,
            check=False,
            timeout=30,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "The Kaggle forms contain the reference text printed above the handwriting. "
            "Install Tesseract OCR first (Ubuntu/Debian: sudo apt install tesseract-ocr), "
            "then rerun prepare-forms."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Tesseract timed out while reading {image_path.name}") from exc
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"Tesseract failed on {image_path.name}: {detail[:300]}")
    text = result.stdout.decode("utf-8", errors="replace")
    return " ".join(text.split())


def _align_reference_to_lines(reference: str, line_crops) -> list[str]:
    """Split OCR text into approximate line labels, proportioned by crop width."""
    words = reference.split()
    if not words or not line_crops:
        return []
    if len(words) < len(line_crops):
        return []

    weights = [max(1, crop.width) for crop in line_crops]
    total_weight = sum(weights)
    prefix_lengths = [0]
    for word in words:
        length = len(word) + 1
        prefix_lengths.append(prefix_lengths[-1] + length)

    # Dynamic programming assigns contiguous words to each handwritten row.
    # This is an initial alignment only; OCR and line wraps must be reviewed.
    costs = [{0: (0.0, [])}]
    for line_index, weight in enumerate(weights):
        next_costs = {}
        remaining_lines = len(weights) - line_index - 1
        target = prefix_lengths[-1] * weight / total_weight
        for start, (cost, boundaries) in costs[-1].items():
            max_end = len(words) - remaining_lines
            for end in range(start + 1, max_end + 1):
                length = prefix_lengths[end] - prefix_lengths[start]
                line_cost = ((length - target) ** 2) / max(1.0, target)
                candidate = (cost + line_cost, boundaries + [end])
                previous = next_costs.get(end)
                if previous is None or candidate[0] < previous[0]:
                    next_costs[end] = candidate
        costs.append(next_costs)
    if len(words) not in costs[-1]:
        return []
    boundaries = costs[-1][len(words)][1]
    labels = []
    start = 0
    for end in boundaries:
        labels.append(" ".join(words[start:end]))
        start = end
    return labels


def prepare_forms_manifest(forms_root: str, output_dir: str, output_csv: str = "",
                           limit: int = 0) -> int:
    """Crop handwritten rows from IAM form scans and align printed reference text."""
    from PIL import Image

    root = Path(forms_root).expanduser().resolve()
    destination = Path(output_dir).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Forms directory is not a directory: {root}")
    if destination == root:
        raise ValueError("Choose an output directory separate from the source forms directory.")
    destination.mkdir(parents=True, exist_ok=True)
    manifest_path = (Path(output_csv).expanduser().resolve() if output_csv
                     else destination / "forms_manifest.csv")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    images = sorted(
        path for path in root.rglob("*.png")
        if destination not in path.resolve().parents
    )
    if limit > 0:
        images = images[:limit]
    if not images:
        raise FileNotFoundError(f"No PNG form images found under {root}")

    rows = []
    skipped = 0
    for image_path in images:
        try:
            with Image.open(image_path) as source:
                image = source.convert("RGB")
            if image.width < 1000 or image.height < 1000:
                skipped += 1
                continue
            line_crops = _form_text_lines(image)
            if not line_crops:
                skipped += 1
                continue
            reference = _ocr_printed_reference(image, image_path)
            labels = _align_reference_to_lines(reference, line_crops)
            if len(labels) != len(line_crops):
                skipped += 1
                continue
            form_parts = image_path.stem.split("-", 1)
            if len(form_parts) != 2 or not form_parts[1]:
                skipped += 1
                continue
            writer_id = form_parts[1]
            for line_index, (crop, text) in enumerate(zip(line_crops, labels), 1):
                crop_name = f"{image_path.stem}-line-{line_index:02d}.png"
                crop_path = destination / crop_name
                crop.save(crop_path, format="PNG")
                rows.append({
                    "image_path": str(crop_path),
                    "text": text,
                    "writer_id": writer_id,
                    "source_form": image_path.name,
                    "alignment_review_required": "true",
                })
        except (OSError, RuntimeError) as exc:
            raise RuntimeError(f"Could not prepare form {image_path}: {exc}") from exc

    if not rows:
        raise ValueError(
            f"No labeled line crops were created from {len(images)} form images. "
            "Check the form layout and OCR output; install Tesseract if it is missing."
        )
    with manifest_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=[
            "image_path", "text", "writer_id", "source_form", "alignment_review_required",
        ])
        writer.writeheader()
        writer.writerows(rows)
    print(
        f"Created {len(rows)} line crops from {len(images) - skipped} forms; "
        f"skipped {skipped}. Review OCR and line alignment in {manifest_path} before training."
    )
    return len(rows)


def repair_form_manifest_writer_ids(input_csv: str, output_csv: str) -> int:
    """Write a corrected copy of a form manifest using IAM writer IDs in filenames."""
    input_path = Path(input_csv).expanduser()
    output_path = Path(output_csv).expanduser()
    if not input_path.is_file():
        raise FileNotFoundError(f"Form manifest not found: {input_path}")
    if input_path.resolve() == output_path.resolve():
        raise ValueError("Choose a different --output path so the original manifest is preserved.")
    with input_path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or not {"source_form", "writer_id"}.issubset(reader.fieldnames):
            raise ValueError("Manifest must contain source_form and writer_id columns.")
        rows = list(reader)
        fieldnames = reader.fieldnames
    for row in rows:
        form_id = Path(row["source_form"]).stem.split("-", 1)
        if len(form_id) != 2 or not form_id[1]:
            raise ValueError(f"Cannot extract writer ID from source_form: {row['source_form']}")
        row["writer_id"] = form_id[1]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def writer_disjoint_split(rows, seed=42):
    """Deterministic 80/10/10 split by writer ID, never by individual line."""
    writers = sorted({r["writer_id"] for r in rows})
    random.Random(seed).shuffle(writers)
    n = len(writers)
    n_train = max(1, int(n * 0.8))
    n_val = max(1, int(n * 0.1)) if n >= 3 else 0
    train_ids = set(writers[:n_train])
    val_ids = set(writers[n_train:n_train + n_val])
    test_ids = set(writers[n_train + n_val:])
    if not test_ids and n >= 3:
        move = next(iter(val_ids))
        val_ids.remove(move)
        test_ids.add(move)
    splits = {"train": [r for r in rows if r["writer_id"] in train_ids],
              "validation": [r for r in rows if r["writer_id"] in val_ids],
              "test": [r for r in rows if r["writer_id"] in test_ids]}
    assert not (train_ids & val_ids or train_ids & test_ids or val_ids & test_ids)
    return splits


def line_random_split(rows, seed=42):
    """Deterministic 80/10/10 split by line for datasets without writer metadata."""
    if len(rows) < 3:
        raise ValueError("At least three labeled lines are required for a line-level split")
    shuffled = list(rows)
    random.Random(seed).shuffle(shuffled)
    train_count = max(1, int(len(shuffled) * 0.8))
    validation_count = max(1, int(len(shuffled) * 0.1))
    if train_count + validation_count >= len(shuffled):
        train_count = len(shuffled) - 2
        validation_count = 1
    return {
        "train": shuffled[:train_count],
        "validation": shuffled[train_count:train_count + validation_count],
        "test": shuffled[train_count + validation_count:],
    }


def normalized_edit_distance(reference, hypothesis):
    previous = list(range(len(hypothesis) + 1))
    for i, left in enumerate(reference, 1):
        current = [i]
        for j, right in enumerate(hypothesis, 1):
            current.append(min(current[-1] + 1, previous[j] + 1,
                               previous[j - 1] + (left != right)))
        previous = current
    return previous[-1]


def fit_temperature(scores, correct):
    """Fit T to sequence score s=mean token log-probability on validation only."""
    best = (float("inf"), 1.0)
    for step in range(1, 1001):
        temperature = 0.05 + step * 0.02
        loss = 0.0
        for score, label in zip(scores, correct):
            p = min(1 - 1e-7, max(1e-7, math.exp(max(-60.0, score / temperature))))
            loss -= label * math.log(p) + (1 - label) * math.log(1 - p)
        loss /= max(1, len(scores))
        if loss < best[0]:
            best = (loss, temperature)
    return best[1]


def ece(confidences, correct, bins=15):
    total, result = len(correct), 0.0
    if not total:
        return None
    for index in range(bins):
        low, high = index / bins, (index + 1) / bins
        members = [i for i, p in enumerate(confidences)
                   if low <= p < high or (index == bins - 1 and p == 1)]
        if members:
            avg_conf = sum(confidences[i] for i in members) / len(members)
            avg_acc = sum(correct[i] for i in members) / len(members)
            result += len(members) / total * abs(avg_conf - avg_acc)
    return result


def train(args):
    manifest_path = Path(args.manifest).expanduser()
    if not manifest_path.is_file():
        raise FileNotFoundError(
            f"Training manifest not found: {manifest_path}. Run the prepare command "
            "successfully first. On Linux, use the actual dataset path; /content "
            "is a Google Colab directory."
        )
    from PIL import Image
    with manifest_path.open(newline="", encoding="utf-8") as f:
        manifest_rows = list(csv.DictReader(f))
    needs_alignment_review = [
        row for row in manifest_rows
        if row.get("alignment_review_required", "").strip().lower() in {"1", "true", "yes"}
    ]
    if needs_alignment_review:
        raise ValueError(
            f"{len(needs_alignment_review)} form-derived rows still require transcript "
            "review. Correct their text in the manifest and set "
            "alignment_review_required to false before training."
        )
    rows = [r for r in manifest_rows if r.get("text", "").strip() and r.get("writer_id")]
    for row in rows:
        if row.get("source_form") and row.get("alignment_review_required") is not None:
            form_id = Path(row["source_form"]).stem.split("-", 1)
            if len(form_id) == 2 and form_id[1]:
                row["writer_id"] = form_id[1]
    if not rows:
        raise ValueError(
            f"Training manifest is empty or missing required image_path, text, and "
            f"writer_id columns: {manifest_path}. Re-run prepare and check its sample count."
        )
    usable = []
    for row in rows:
        if len(row["text"]) > args.max_text_chars or not os.path.isfile(row["image_path"]):
            continue
        try:
            with Image.open(row["image_path"]) as image: image.verify()
            usable.append(row)
        except Exception:
            print(f"Skipping malformed image: {row['image_path']}")
    skipped_rows = len(rows) - len(usable)
    rows = usable
    if not rows:
        raise ValueError(
            "Manifest contains no usable samples. Check that image_path values point to "
            "existing, readable image files and that the manifest has image_path, text, "
            "and writer_id columns."
        )
    print(f"Usable samples: {len(rows)}; skipped missing/invalid/oversized samples: {skipped_rows}")
    if getattr(args, "allow_line_split", False):
        print("WARNING: using a line-level split; evaluation does not measure generalization to unseen writers.")
        splits = line_random_split(rows, args.seed)
    else:
        splits = writer_disjoint_split(rows, args.seed)
    if not splits["validation"] or not splits["test"]:
        writer_count = len({row["writer_id"] for row in rows})
        raise ValueError(
            f"Writer-disjoint splitting produced an empty validation or test split "
            f"({writer_count} distinct writer IDs found). This dataset may not include "
            "writer IDs; use --allow-line-split for an explicitly non-writer-disjoint experiment."
        )

    import torch
    from transformers import (TrOCRProcessor, VisionEncoderDecoderModel,
                              Seq2SeqTrainer, Seq2SeqTrainingArguments,
                              EarlyStoppingCallback)
    os.makedirs(args.output, exist_ok=True)
    processor = TrOCRProcessor.from_pretrained(args.base_model, use_fast=False)
    model = VisionEncoderDecoderModel.from_pretrained(args.resume or args.base_model)
    model.config.decoder_start_token_id = processor.tokenizer.cls_token_id
    model.config.pad_token_id = processor.tokenizer.pad_token_id
    model.config.eos_token_id = processor.tokenizer.sep_token_id
    model.config.max_length = 128
    model.config.vocab_size = model.config.decoder.vocab_size

    class LineDataset(torch.utils.data.Dataset):
        def __init__(self, data): self.data = data
        def __len__(self): return len(self.data)
        def __getitem__(self, index):
            row = self.data[index]
            try:
                image = Image.open(row["image_path"]).convert("RGB")
                pixels = processor(images=image, return_tensors="pt").pixel_values[0]
                labels = processor.tokenizer(row["text"], truncation=True, max_length=128,
                                             return_tensors="pt").input_ids[0]
                labels[labels == processor.tokenizer.pad_token_id] = -100
                return {"pixel_values": pixels, "labels": labels}
            except Exception as exc:
                raise ValueError(f"Invalid IAM sample {row['image_path']}: {exc}") from exc

    def collate(features):
        return {"pixel_values": torch.stack([x["pixel_values"] for x in features]),
                "labels": torch.nn.utils.rnn.pad_sequence([x["labels"] for x in features],
                    batch_first=True, padding_value=-100)}

    def cer_metric(eval_prediction):
        predictions = eval_prediction.predictions
        if isinstance(predictions, tuple): predictions = predictions[0]
        labels = eval_prediction.label_ids.copy()
        labels[labels == -100] = processor.tokenizer.pad_token_id
        pred_text = processor.batch_decode(predictions, skip_special_tokens=True)
        ref_text = processor.batch_decode(labels, skip_special_tokens=True)
        chars = sum(normalized_edit_distance(r, p) for r, p in zip(ref_text, pred_text))
        words = sum(normalized_edit_distance(r.split(), p.split()) for r, p in zip(ref_text, pred_text))
        return {"cer": chars / max(1, sum(len(r) for r in ref_text)),
                "wer": words / max(1, sum(len(r.split()) for r in ref_text))}

    # Baseline result is recorded before any training steps.
    eval_args = Seq2SeqTrainingArguments(output_dir=os.path.join(args.output, "baseline"),
        per_device_eval_batch_size=args.batch_size, predict_with_generate=True,
        generation_max_length=128, report_to=[], fp16=torch.cuda.is_available())
    baseline = Seq2SeqTrainer(model=model, args=eval_args,
        eval_dataset=LineDataset(splits["validation"]), data_collator=collate,
        compute_metrics=cer_metric, processing_class=processor)
    baseline_metrics = baseline.evaluate()

    train_args = Seq2SeqTrainingArguments(output_dir=os.path.join(args.output, "checkpoints"),
        learning_rate=args.learning_rate, lr_scheduler_type="linear", warmup_ratio=0.05,
        weight_decay=0.01, num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size, per_device_eval_batch_size=args.batch_size,
        gradient_accumulation_steps=args.gradient_accumulation,
        fp16=torch.cuda.is_available(), predict_with_generate=True, generation_max_length=128,
        eval_strategy="epoch", save_strategy="epoch", save_total_limit=2,
        load_best_model_at_end=True, metric_for_best_model="cer", greater_is_better=False,
        report_to=[], logging_steps=50)
    trainer = Seq2SeqTrainer(model=model, args=train_args, train_dataset=LineDataset(splits["train"]),
        eval_dataset=LineDataset(splits["validation"]), data_collator=collate,
        compute_metrics=cer_metric, processing_class=processor,
        callbacks=[EarlyStoppingCallback(early_stopping_patience=3)])
    trainer.train(resume_from_checkpoint=args.resume or None)
    trainer.save_model(args.output)
    processor.save_pretrained(args.output)

    # Sequence score extraction: average decoder token log-probability; whole-line
    # exact match is the binary calibration target. Validation only fits T.
    def score_split(data):
        scores, correct, refs, hyps = [], [], [], []
        model.eval()
        for start in range(0, len(data), args.batch_size):
            chunk = data[start:start + args.batch_size]
            images = [Image.open(r["image_path"]).convert("RGB") for r in chunk]
            pixel_values = processor(images=images, return_tensors="pt").pixel_values.to(model.device)
            with torch.inference_mode():
                out = model.generate(pixel_values, num_beams=1, max_new_tokens=128,
                                     return_dict_in_generate=True, output_scores=True)
                decoded = processor.batch_decode(out.sequences, skip_special_tokens=True)
                for i, hyp in enumerate(decoded):
                    token_logps = []
                    for step, logits in enumerate(out.scores):
                        token_id = int(out.sequences[i, step + 1])
                        if token_id == processor.tokenizer.eos_token_id: break
                        token_logps.append(float(torch.log_softmax(logits[i].float(), -1)[token_id]))
                    score = sum(token_logps) / max(1, len(token_logps))
                    ref = chunk[i]["text"].strip()
                    scores.append(score); correct.append(float(hyp.strip() == ref))
                    refs.append(ref); hyps.append(hyp.strip())
        return scores, correct, refs, hyps

    val_scores, val_correct, val_refs, val_hyps = score_split(splits["validation"])
    temperature = fit_temperature(val_scores, val_correct)
    val_conf = [math.exp(max(-60, s / temperature)) for s in val_scores]
    config = {"temperature": temperature, "acceptance_threshold": args.threshold,
              "calibration_method": "temperature scaling of length-normalized sequence log probability",
              "fit_split": "validation", "base_model": args.base_model}
    with open(os.path.join(args.output, "calibration.json"), "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)

    test_scores, test_correct, test_refs, test_hyps = score_split(splits["test"])
    test_conf = [math.exp(max(-60, s / temperature)) for s in test_scores]
    cer = sum(normalized_edit_distance(r, h) for r, h in zip(test_refs, test_hyps)) / max(1, sum(len(r) for r in test_refs))
    ref_words = sum(len(r.split()) for r in test_refs)
    wer = sum(normalized_edit_distance(r.split(), h.split()) for r, h in zip(test_refs, test_hyps)) / max(1, ref_words)
    test_metrics = trainer.evaluate(eval_dataset=LineDataset(splits["test"]))
    # Measure practical laptop inference independently on CPU, excluding model load.
    cpu_model = model.to("cpu").eval()
    latencies = []
    for row in splits["test"][:min(20, len(splits["test"]))]:
        image = Image.open(row["image_path"]).convert("RGB")
        pixels = processor(images=image, return_tensors="pt").pixel_values
        start = time.perf_counter()
        with torch.inference_mode(): cpu_model.generate(pixels, num_beams=1, max_new_tokens=128)
        latencies.append(time.perf_counter() - start)
    cpu_latency = {"sample_count": len(latencies), "mean_seconds": sum(latencies) / max(1, len(latencies)),
                   "p95_seconds": sorted(latencies)[min(len(latencies) - 1, int(0.95 * len(latencies)))] if latencies else None}
    report = {"baseline_validation": baseline_metrics, "best_validation": trainer.evaluate(),
              "test_loss_and_metrics": test_metrics, "cpu_inference_latency": cpu_latency,
              "test_cer": cer, "test_wer": wer, "validation_ece": ece(val_conf, val_correct),
              "test_ece": ece(test_conf, test_correct), "temperature": temperature,
              "writers": {k: len({r['writer_id'] for r in v}) for k, v in splits.items()},
              "lines": {k: len(v) for k, v in splits.items()},
              "test_risk_coverage": [[i / max(1, len(test_conf)),
                  1 - sum(test_correct[j] for j in sorted(range(len(test_conf)), key=lambda j: test_conf[j], reverse=True)[:i]) / max(1, i)]
                  for i in range(1, len(test_conf) + 1)]}
    with open(os.path.join(args.output, "evaluation.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    try:
        import matplotlib.pyplot as plt
        bins = [i / 10 for i in range(11)]
        acc, conf = [], []
        for low, high in zip(bins, bins[1:]):
            ids = [i for i, p in enumerate(test_conf) if low <= p < high]
            if ids:
                conf.append(sum(test_conf[i] for i in ids) / len(ids))
                acc.append(sum(test_correct[i] for i in ids) / len(ids))
        plt.figure(); plt.plot([0, 1], [0, 1], "--", color="gray"); plt.plot(conf, acc, "o-")
        plt.xlabel("Confidence"); plt.ylabel("Exact-line accuracy"); plt.title("Test reliability diagram")
        plt.savefig(os.path.join(args.output, "reliability.png"), dpi=160, bbox_inches="tight"); plt.close()
        risk = report["test_risk_coverage"]
        plt.figure(); plt.plot([p[0] for p in risk], [p[1] for p in risk])
        plt.xlabel("Coverage"); plt.ylabel("Line error risk"); plt.title("Test risk-coverage")
        plt.savefig(os.path.join(args.output, "risk_coverage.png"), dpi=160, bbox_inches="tight"); plt.close()
    except ImportError:
        print("matplotlib unavailable: reliability/risk plots were not generated")
    print(json.dumps(report, indent=2))


def main():
    # Define dataset preparation, repair, and model-training command workflows.
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument(
        "--iam-root", required=True,
        help="Extracted dataset root containing lines.txt and line images",
    )
    prepare.add_argument("--manifest", required=True)
    prepare_forms = sub.add_parser(
        "prepare-forms",
        help="Crop handwritten rows and prepare reviewed labels from Kaggle IAM form scans",
    )
    prepare_forms.add_argument("--forms-root", required=True)
    prepare_forms.add_argument("--output-dir", required=True)
    prepare_forms.add_argument("--manifest", default="")
    prepare_forms.add_argument("--limit", type=int, default=0,
                               help="Process only the first N forms (useful for a pilot run)")
    repair_forms = sub.add_parser(
        "repair-form-writers",
        help="Create a corrected copy of a form manifest with IAM writer IDs",
    )
    repair_forms.add_argument("--manifest", required=True, help="Existing forms CSV")
    repair_forms.add_argument("--output", required=True, help="New corrected CSV path")
    train_parser = sub.add_parser("train")
    train_parser.add_argument("--manifest", required=True); train_parser.add_argument("--output", required=True)
    train_parser.add_argument("--base-model", default="microsoft/trocr-small-stage1")
    train_parser.add_argument("--resume", default=""); train_parser.add_argument("--seed", type=int, default=42)
    train_parser.add_argument("--epochs", type=int, default=20); train_parser.add_argument("--batch-size", type=int, default=4)
    train_parser.add_argument("--gradient-accumulation", type=int, default=4)
    train_parser.add_argument("--learning-rate", type=float, default=5e-5)
    train_parser.add_argument("--max-text-chars", type=int, default=1000)
    train_parser.add_argument("--threshold", type=float, default=0.72)
    train_parser.add_argument(
        "--allow-line-split", action="store_true",
        help="Split by line when writer IDs are unavailable; evaluation will not be writer-disjoint",
    )
    args = parser.parse_args()
    # Dispatch the selected workflow and report expected input errors as CLI errors.
    try:
        if args.command == "prepare":
            count = prepare_manifest(args.iam_root, args.manifest)
            print(f"Wrote {count} labeled line samples to {Path(args.manifest).expanduser()}")
        elif args.command == "prepare-forms":
            prepare_forms_manifest(
                args.forms_root, args.output_dir, args.manifest, args.limit)
        elif args.command == "repair-form-writers":
            count = repair_form_manifest_writer_ids(args.manifest, args.output)
            print(f"Corrected writer IDs for {count} rows in {Path(args.output).expanduser()}")
        else:
            train(args)
    except (FileNotFoundError, OSError, ValueError, RuntimeError, csv.Error) as exc:
        parser.error(str(exc))


if __name__ == "__main__": main()
