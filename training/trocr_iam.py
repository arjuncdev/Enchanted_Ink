"""Train and evaluate a writer-disjoint TrOCR model on IAM line images.

Colab example:
  !python training/trocr_iam.py prepare --iam-root /content/iam --manifest /content/iam.csv
  !python training/trocr_iam.py train --manifest /content/iam.csv --output /content/trocr-output

IAM must be downloaded through its official registration process. This script
does not download or redistribute dataset files.
"""
import argparse
import csv
import json
import math
import os
import random
import re
import time
from pathlib import Path


def prepare_manifest(iam_root: str, output_csv: str) -> int:
    root = Path(iam_root)
    annotation_files = list(root.rglob("lines.txt"))
    if not annotation_files:
        raise FileNotFoundError("Could not find IAM lines.txt under --iam-root")
    count = 0
    with open(output_csv, "w", newline="", encoding="utf-8") as stream:
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
                text = " ".join(" ".join(fields[8:]).replace("|", " ").split())
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
                writer.writerow({"image_path": str(image_path.resolve()), "text": text,
                                 "writer_id": line_id.split("-")[1]})
                count += 1
    if not count:
        raise ValueError("No IAM line images found; check the extracted IAM directory layout")
    return count


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
    import torch
    from PIL import Image
    from transformers import (TrOCRProcessor, VisionEncoderDecoderModel,
                              Seq2SeqTrainer, Seq2SeqTrainingArguments,
                              EarlyStoppingCallback)
    with open(args.manifest, newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r.get("text", "").strip() and r.get("writer_id")]
    usable = []
    for row in rows:
        if len(row["text"]) > args.max_text_chars or not os.path.isfile(row["image_path"]):
            continue
        try:
            with Image.open(row["image_path"]) as image: image.verify()
            usable.append(row)
        except Exception:
            print(f"Skipping malformed image: {row['image_path']}")
    rows = usable
    if not rows:
        raise ValueError("Manifest contains no usable image/transcript/writer rows")
    splits = writer_disjoint_split(rows, args.seed)
    if not splits["validation"] or not splits["test"]:
        raise ValueError("At least 10 distinct writers are recommended for nonempty train/validation/test splits")

    os.makedirs(args.output, exist_ok=True)
    processor = TrOCRProcessor.from_pretrained(args.base_model)
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
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--iam-root", required=True); prepare.add_argument("--manifest", required=True)
    train_parser = sub.add_parser("train")
    train_parser.add_argument("--manifest", required=True); train_parser.add_argument("--output", required=True)
    train_parser.add_argument("--base-model", default="microsoft/trocr-small-stage1")
    train_parser.add_argument("--resume", default=""); train_parser.add_argument("--seed", type=int, default=42)
    train_parser.add_argument("--epochs", type=int, default=20); train_parser.add_argument("--batch-size", type=int, default=4)
    train_parser.add_argument("--gradient-accumulation", type=int, default=4)
    train_parser.add_argument("--learning-rate", type=float, default=5e-5)
    train_parser.add_argument("--max-text-chars", type=int, default=1000)
    train_parser.add_argument("--threshold", type=float, default=0.72)
    args = parser.parse_args()
    if args.command == "prepare": print(f"Wrote {prepare_manifest(args.iam_root, args.manifest)} IAM samples to {args.manifest}")
    else: train(args)


if __name__ == "__main__": main()
