"""Research-safe CSV, Markdown, PNG and standalone interactive HTML reports."""
from __future__ import annotations

import csv
import base64
import html
import io
import json
import math
import re
import random
import statistics
from collections import Counter
from pathlib import Path
from typing import Optional, Sequence

from PIL import Image, ImageOps
from evaluation.metrics import align_sequences, character_confusion, evaluate_sequences, top_substitutions

MODEL_LABELS = {
    "trocr": "TrOCR",
    "kraken": "Kraken PP-OCRv6 Small",
}
PREDICTION_COLUMNS = (
    "sample_id", "image_path", "ground_truth", "writer_id", "split", "source", "category",
    "model", "model_id", "prediction", "status", "latency_seconds", "network_seconds",
    "confidence", "confidence_status", "confidence_details_json", "error",
)


def _write_csv(path: Path, rows: list[dict], columns: Optional[Sequence[str]] = None) -> None:
    if columns is None:
        columns = list(rows[0]) if rows else []
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _image_url(path: str) -> Optional[str]:
    try:
        with Image.open(path) as image:
            image = ImageOps.exif_transpose(image).convert("RGB")
            stream = io.BytesIO()
            image.save(stream, format="PNG")
        return "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode("ascii")
    except OSError:
        return None


def _quantile(values: Sequence[float], q: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    low, high = math.floor(position), math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] * (high - position) + ordered[high] * (position - low)


def _bootstrap_ci(samples: list[dict], model: str, metric: str, allowed_ids: set[str],
                  seed: int = 42,
                  iterations: int = 1000) -> Optional[list[float]]:
    eligible = [row for row in samples if row["sample_id"] in allowed_ids
                and row.get(f"{model}_status") in ("success", "empty")]
    if not eligible:
        return None
    rng = random.Random(seed)
    estimates = []
    for _ in range(iterations):
        chosen = [rng.choice(eligible) for _ in eligible]
        references = [row["ground_truth"] for row in chosen]
        hypotheses = [row.get(f"{model}_prediction") or "" for row in chosen]
        value = evaluate_sequences(references, hypotheses).get(metric)
        if value is not None and math.isfinite(value):
            estimates.append(value)
    if not estimates:
        return None
    return [_quantile(estimates, 0.025), _quantile(estimates, 0.975)]


def _pairwise_sign_test(samples: list[dict], first: str, second: str) -> Optional[dict]:
    first_wins = second_wins = 0
    for row in samples:
        if row.get(f"{first}_status") not in ("success", "empty") or \
                row.get(f"{second}_status") not in ("success", "empty"):
            continue
        reference = row["ground_truth"]
        first_cer = evaluate_sequences([reference], [row.get(f"{first}_prediction") or ""])["cer"]
        second_cer = evaluate_sequences([reference], [row.get(f"{second}_prediction") or ""])["cer"]
        if first_cer < second_cer:
            first_wins += 1
        elif second_cer < first_cer:
            second_wins += 1
    n = first_wins + second_wins
    if n == 0:
        return {"comparable_non_ties": 0, "p_value": None, "interpretation": "all comparisons tied or unavailable"}
    tail = sum(math.comb(n, k) for k in range(min(first_wins, second_wins) + 1)) / (2 ** n)
    p_value = min(1.0, 2 * tail)
    return {
        "comparable_non_ties": n,
        "first_wins": first_wins,
        "second_wins": second_wins,
        "p_value": p_value,
        "interpretation": (
            "nominal p < 0.05 in this exploratory sample; not a generalizable winner claim"
            if p_value < 0.05 else "not significant at 0.05"
        ),
    }


def _sample_records(samples: list[dict], predictions: list[dict]) -> list[dict]:
    by_id = {sample["sample_id"]: dict(sample) for sample in samples}
    for result in predictions:
        sample = by_id[result["sample_id"]]
        name = result["model"]
        sample[f"{name}_prediction"] = result.get("prediction")
        sample[f"{name}_status"] = result.get("status")
        sample[f"{name}_error"] = result.get("error")
    return list(by_id.values())


def _common_sample_ids(samples: list[dict], predictions: list[dict], metadata: dict) -> set[str]:
    initialized = {engine["model"] for engine in metadata["engines"] if engine.get("status") == "ready"}
    by_model_sample = {(item["model"], item["sample_id"]): item for item in predictions}
    return {
        sample["sample_id"] for sample in samples
        if initialized and all(
            by_model_sample.get((model, sample["sample_id"]), {}).get("status") in ("success", "empty")
            for model in initialized
        )
    }


def _model_metrics(samples: list[dict], predictions: list[dict], metadata: dict) -> list[dict]:
    rows = []
    sample_records = _sample_records(samples, predictions)
    initialized = {engine["model"] for engine in metadata["engines"] if engine.get("status") == "ready"}
    common_ids = _common_sample_ids(samples, predictions, metadata)
    metadata["dataset"]["common_comparison_samples"] = len(common_ids)
    metadata["dataset"]["common_comparison_models"] = sorted(initialized)
    for engine in metadata["engines"]:
        name = engine["model"]
        selected = [item for item in predictions if item["model"] == name]
        completed = [item for item in selected if item.get("status") in ("success", "empty")]
        metric_rows = [item for item in completed if item["sample_id"] in common_ids]
        references = [item["ground_truth"] for item in metric_rows]
        hypotheses = [item.get("prediction") or "" for item in metric_rows]
        quality = evaluate_sequences(references, hypotheses) if metric_rows else {}
        board_pairs = [
            item for item in metric_rows
            if "board" in str(item.get("category", "")).lower()
            or re.match(r"^\s*@\s*board\b", item["ground_truth"], flags=re.IGNORECASE)
        ]
        board_exact = []
        board_prefix_correct = []
        board_instruction_success = []
        for item in board_pairs:
            expected = item["ground_truth"].strip()
            predicted = (item.get("prediction") or "").strip()
            expected_prefix = bool(re.match(r"^\s*@\s*board\b", expected, flags=re.IGNORECASE))
            predicted_match = re.match(r"^\s*@\s*board\b", predicted, flags=re.IGNORECASE)
            predicted_prefix = bool(predicted_match)
            board_exact.append(" ".join(expected.casefold().split()) ==
                               " ".join(predicted.casefold().split()))
            board_prefix_correct.append(expected_prefix == predicted_prefix)
            instruction = predicted[predicted_match.end():].strip() if predicted_match else ""
            board_instruction_success.append(predicted_prefix and bool(instruction))
        latencies = [item["latency_seconds"] for item in completed if item.get("latency_seconds") is not None]
        network_latencies = [item["network_seconds"] for item in completed
                             if item.get("network_seconds") is not None]
        attempts = len(selected) if engine.get("status") == "ready" else 0
        successful = sum(item.get("status") == "success" for item in selected)
        empty = sum(item.get("status") == "empty" for item in selected)
        errors = sum(item.get("status") == "error" for item in selected)
        row = {
            "model": name,
            "model_label": MODEL_LABELS.get(name, name),
            "model_id": engine.get("model_id"),
            "model_source": engine.get("model_source"),
            "run_status": engine.get("status"),
            "error": engine.get("error"),
            "requested_samples": len(samples),
            "attempted_samples": attempts,
            "successful_samples": successful,
            "empty_samples": empty,
            "failed_samples": errors,
            "successful_recognition_rate": successful / attempts if attempts else None,
            "empty_result_rate": empty / attempts if attempts else None,
            "provider_failure_rate": errors / attempts if attempts else None,
            "loading_seconds": engine.get("loading_seconds"),
            "download_seconds": engine.get("download_seconds"),
            "model_load_seconds": engine.get("model_load_seconds"),
            "model_size_bytes": engine.get("model_size_bytes"),
            "average_latency_seconds": statistics.fmean(latencies) if latencies else None,
            "median_latency_seconds": statistics.median(latencies) if latencies else None,
            "p95_latency_seconds": _quantile(latencies, 0.95),
            "average_network_seconds": statistics.fmean(network_latencies) if network_latencies else None,
            **{key: quality.get(key) for key in (
                "cer", "wer", "exact_line_match_accuracy", "character_alignment_accuracy",
                "word_alignment_accuracy", "character_micro_precision",
                "character_micro_recall", "character_micro_f1", "character_macro_f1",
                "character_weighted_f1", "word_micro_precision", "word_micro_recall", "word_micro_f1",
                "character_substitutions", "character_insertions", "character_deletions",
                "word_substitutions", "word_insertions", "word_deletions",
            )},
            "metric_samples": len(metric_rows),
            "metric_scope": "shared successful sample intersection across all initialized models",
            "confidence_calibration": "N/A: no valid held-out confidence calibration in this run",
            "ece": None,
            "brier_score": None,
            "board_command_samples": len(board_pairs),
            "command_transcription_accuracy": (sum(board_exact) / len(board_exact) if board_exact else None),
            "board_prefix_detection_accuracy": (
                sum(board_prefix_correct) / len(board_prefix_correct) if board_prefix_correct else None),
            "instruction_extraction_success_rate": (
                sum(board_instruction_success) / len(board_instruction_success)
                if board_instruction_success else None),
            "end_to_end_command_execution_rate": None,
            "manual_confirmation_rate": None,
        }
        for metric in ("cer", "wer", "exact_line_match_accuracy", "character_micro_f1",
                       "character_macro_f1", "character_weighted_f1", "word_micro_f1"):
            row[f"{metric}_bootstrap_95ci"] = _bootstrap_ci(
                sample_records, name, metric, common_ids
            )
        rows.append(row)
    return rows


def _confusion_rows(references: list[str], hypotheses: list[str]) -> list[dict]:
    counts = character_confusion(references, hypotheses)
    actual_labels = sorted({label for pair in counts for label in pair})
    row_totals = Counter()
    for (expected, _predicted), count in counts.items():
        row_totals[expected] += count
    rows = []
    for expected in actual_labels:
        for predicted in actual_labels:
            count = counts.get((expected, predicted), 0)
            rows.append({
                "ground_truth_character": expected,
                "predicted_character": predicted,
                "raw_count": count,
                "row_normalized": count / row_totals[expected] if row_totals[expected] else None,
            })
    return rows


def _edit_details(reference: str, hypothesis: str) -> list[dict]:
    result = []
    for expected, predicted in align_sequences(list(reference), list(hypothesis)).pairs:
        if expected == predicted:
            operation = "match"
        elif expected is None:
            operation = "insertion"
        elif predicted is None:
            operation = "deletion"
        else:
            operation = "substitution"
        if operation != "match":
            result.append({
                "operation": operation,
                "ground_truth": expected,
                "prediction": predicted,
            })
    return result


def _escaped_text_diff(reference: str, hypothesis: str) -> str:
    pieces = []
    for expected, predicted in align_sequences(list(reference), list(hypothesis)).pairs:
        if expected == predicted and expected is not None:
            pieces.append(html.escape(expected))
        elif expected is None:
            pieces.append(f'<mark class="inserted">+{html.escape(predicted or "")}</mark>')
        elif predicted is None:
            pieces.append(f'<mark class="deleted">−{html.escape(expected)}</mark>')
        else:
            pieces.append(
                f'<mark class="substituted" title="expected {html.escape(expected)}">'
                f'{html.escape(predicted)}</mark>'
            )
    return "".join(pieces)


def _chart_pngs(output: Path, metrics: list[dict], sample_records: list[dict],
                predictions: list[dict]) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LogNorm
    plots = output / "plots"
    plots.mkdir(parents=True, exist_ok=True)
    available = [row for row in metrics if row["metric_samples"]]
    labels = [row["model_label"] for row in metrics]
    colors = ["#4c78a8", "#f2a541", "#59a14f"]

    def bars(filename, title, keys, names, ylabel):
        fig, ax = plt.subplots(figsize=(8, 4.5), constrained_layout=True)
        width = 0.78 / max(1, len(keys))
        x = list(range(len(labels)))
        for index, (key, name) in enumerate(zip(keys, names)):
            vals = [row.get(key) if row.get(key) is not None else float("nan") for row in metrics]
            offset = (index - (len(keys) - 1) / 2) * width
            ax.bar([item + offset for item in x], vals, width, label=name)
        ax.set_xticks(x, labels, rotation=12, ha="right")
        ax.set_title(title)
        ax.set_ylabel(ylabel)
        if len(keys) > 1:
            ax.legend()
        ax.grid(axis="y", alpha=0.25)
        fig.savefig(plots / filename, dpi=200)
        plt.close(fig)

    bars("cer_comparison.png", "Character Error Rate (lower is better)", ["cer"], ["CER"], "CER")
    bars("wer_comparison.png", "Word Error Rate (lower is better)", ["wer"], ["WER"], "WER")
    bars("f1_comparison.png", "Sequence-aligned F1 scores (higher is better)",
         ["character_micro_f1", "character_macro_f1", "character_weighted_f1", "word_micro_f1"],
         ["Character micro", "Character macro", "Character weighted", "Word micro"], "F1")
    bars("precision_recall.png", "Micro precision and recall (higher is better)",
         ["character_micro_precision", "character_micro_recall"],
         ["Character precision", "Character recall"], "Score")
    bars("latency_comparison.png", "Local inference latency",
         ["average_latency_seconds", "median_latency_seconds", "p95_latency_seconds"],
         ["Mean", "Median", "P95"], "Seconds")
    fig, ax = plt.subplots(figsize=(7, 5), constrained_layout=True)
    for index, row in enumerate(metrics):
        x, y = row.get("median_latency_seconds"), row.get("character_alignment_accuracy")
        if x is not None and y is not None:
            ax.scatter(x, y, s=90, color=colors[index % len(colors)])
            ax.annotate(row["model_label"], (x, y), xytext=(5, 6), textcoords="offset points")
    ax.set_xlabel("Median end-to-end latency (seconds)")
    ax.set_ylabel("Character alignment accuracy (reference characters matched)")
    ax.set_title("Character quality versus median latency")
    ax.grid(alpha=0.25)
    fig.savefig(plots / "accuracy_latency.png", dpi=200)
    plt.close(fig)
    bars("error_breakdown.png", "Character edit operations", [
        "character_substitutions", "character_insertions", "character_deletions",
    ], ["Substitutions", "Insertions", "Deletions"], "Count")
    bars("exact_line_accuracy.png", "Exact-line recognition (higher is better)",
         ["exact_line_match_accuracy"], ["Exact line"], "Accuracy")
    bars("calibration_comparison.png", "Calibration (N/A without valid calibration artifacts)",
         ["ece"], ["ECE"], "ECE")

    for model in ("trocr", "kraken"):
        matching = [item for item in predictions
                    if item["model"] == model and item.get("status") in ("success", "empty")]
        refs = [item["ground_truth"] for item in matching]
        hyps = [item.get("prediction") or "" for item in matching]
        confusion = character_confusion(refs, hyps)
        totals = Counter()
        for (expected, _), count in confusion.items():
            if expected != "<INSERTION>":
                totals[expected] += count
        labels_top = [label for label, _ in totals.most_common(24)]
        if not labels_top:
            labels_top = ["N/A"]
        grid = [[confusion.get((expected, predicted), 0) for predicted in labels_top]
                for expected in labels_top]
        fig, ax = plt.subplots(figsize=(9, 8), constrained_layout=True)
        image = ax.imshow(grid, cmap="Blues", norm=LogNorm(vmin=1, vmax=max(1, max(map(max, grid)))))
        ax.set_xticks(range(len(labels_top)), [label if label != " " else "<SP>" for label in labels_top])
        ax.set_yticks(range(len(labels_top)), [label if label != " " else "<SP>" for label in labels_top])
        ax.set_xlabel("Predicted character")
        ax.set_ylabel("Ground-truth character")
        ax.set_title(f"{MODEL_LABELS[model]} — most common character classes")
        fig.colorbar(image, ax=ax, label="Aligned counts (log color scale)")
        fig.savefig(plots / f"confusion_{model}.png", dpi=200)
        plt.close(fig)

    substitutions = []
    for model in ("trocr", "kraken"):
        matching = [item for item in predictions if item["model"] == model
                    and item.get("status") in ("success", "empty")]
        substitutions.extend({**item, "model": model} for item in top_substitutions(
            [row["ground_truth"] for row in matching],
            [row.get("prediction") or "" for row in matching], 20))
    fig, ax = plt.subplots(figsize=(9, 6), constrained_layout=True)
    top = sorted(substitutions, key=lambda row: row["count"], reverse=True)[:20]
    ax.barh([f'{MODEL_LABELS[row["model"]]}: {row["ground_truth"]!r}→{row["prediction"]!r}'
             for row in top][::-1], [row["count"] for row in top][::-1], color="#d95f59")
    ax.set_title("Most frequent aligned character substitutions")
    ax.set_xlabel("Count")
    fig.savefig(plots / "top_substitutions.png", dpi=200)
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(9, 4), constrained_layout=True)
    for axis, key, title in zip(axes, ("character_insertions", "character_deletions"),
                                ("Insertions", "Deletions")):
        axis.bar(labels, [row.get(key) or 0 for row in metrics], color=colors[:len(labels)])
        axis.set_title(title)
        axis.tick_params(axis="x", rotation=12)
        axis.grid(axis="y", alpha=0.25)
    fig.savefig(plots / "insertion_deletion.png", dpi=200)
    plt.close(fig)
    for operation in ("insertion", "deletion"):
        frequency = Counter()
        for model in ("trocr", "kraken"):
            matching = [item for item in predictions if item["model"] == model
                        and item.get("status") in ("success", "empty")]
            for reference, hypothesis in zip(
                [item["ground_truth"] for item in matching],
                [item.get("prediction") or "" for item in matching],
            ):
                for expected, predicted in align_sequences(list(reference), list(hypothesis)).pairs:
                    if (operation == "insertion" and expected is None and predicted is not None):
                        frequency[predicted] += 1
                    if (operation == "deletion" and expected is not None and predicted is None):
                        frequency[expected] += 1
        top = frequency.most_common(20)
        fig, ax = plt.subplots(figsize=(8, 5), constrained_layout=True)
        ax.barh([repr(char) for char, _ in top][::-1], [count for _, count in top][::-1],
                color="#6e91bd")
        ax.set_title(f"Most frequent character {operation}s")
        ax.set_xlabel("Count")
        fig.savefig(plots / f"{operation}_frequency.png", dpi=200)
        plt.close(fig)


def _dashboard(output: Path, metrics: list[dict], samples: list[dict], predictions: list[dict],
               comparison_predictions: list[dict], metadata: dict) -> None:
    by_sample = {row["sample_id"]: row for row in samples}
    details = []
    for prediction in predictions:
        sample = by_sample[prediction["sample_id"]]
        details.append({
            "sample_id": prediction["sample_id"],
            "model": prediction["model"],
            "model_id": prediction["model_id"],
            "status": prediction["status"],
            "ground_truth": sample["ground_truth"],
            "prediction": prediction.get("prediction") or "",
            "error": prediction.get("error"),
            "latency_seconds": prediction.get("latency_seconds"),
            "image": prediction.get("image_data_url"),
            "diff_html": _escaped_text_diff(
                sample["ground_truth"], prediction.get("prediction") or ""
            ) if prediction.get("status") in ("success", "empty") else None,
            "edit_details": _edit_details(
                sample["ground_truth"], prediction.get("prediction") or ""
            ) if prediction.get("status") in ("success", "empty") else None,
            "edits": (evaluate_sequences([sample["ground_truth"]], [prediction.get("prediction") or ""])
                      if prediction.get("status") in ("success", "empty") else None),
        })
    confusion_details = {}
    substitution_details = {}
    operation_details = {}
    for model in ("trocr", "kraken"):
        matching = [item for item in comparison_predictions
                    if item["model"] == model and item.get("status") in ("success", "empty")]
        refs = [item["ground_truth"] for item in matching]
        hyps = [item.get("prediction") or "" for item in matching]
        counts = character_confusion(refs, hyps)
        frequency = Counter()
        for (expected, predicted), count in counts.items():
            if expected not in ("<INSERTION>", "<DELETION>"):
                frequency[expected] += count
            if expected == "<INSERTION>":
                operation_details.setdefault(model, {}).setdefault("insertions", Counter())[predicted] += count
            elif predicted == "<DELETION>":
                operation_details.setdefault(model, {}).setdefault("deletions", Counter())[expected] += count
        top_chars = [character for character, _ in frequency.most_common(24)]
        confusion_details[model] = {
            "labels": top_chars,
            "matrix": [[counts.get((expected, predicted), 0) for predicted in top_chars]
                       for expected in top_chars],
        }
        substitution_details[model] = top_substitutions(refs, hyps, 20)
    operation_details = {
        model: {kind: [{"character": character, "count": count}
                       for character, count in counts.most_common(20)]
                for kind, counts in kinds.items()}
        for model, kinds in operation_details.items()
    }
    initialized = [row["model"] for row in metrics if row.get("run_status") == "ready"]
    paired_tests = []
    for index, first in enumerate(initialized):
        for second in initialized[index + 1:]:
            paired_tests.append({
                "first": first,
                "second": second,
                "test": _pairwise_sign_test(samples, first, second),
            })
    payload = json.dumps({
        "metrics": metrics,
        "samples": details,
        "metadata": metadata,
        "labels": MODEL_LABELS,
        "confusions": confusion_details,
        "substitutions": substitution_details,
        "edit_frequencies": operation_details,
        "paired_tests": paired_tests,
    }, ensure_ascii=False).replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    page = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Enchanted Ink — HTR Model Comparison</title>
<style>
:root{color-scheme:light;--ink:#17243a;--muted:#61718b;--line:#dce4ef;--blue:#4776c6;--amber:#e5a13c;--green:#4c9a72;--red:#c75555}
*{box-sizing:border-box}body{margin:0;background:#f4f7fb;color:var(--ink);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
header{background:#15243b;color:white;padding:28px max(5vw,20px)}header h1{margin:0 0 5px;font-size:clamp(1.5rem,3vw,2.4rem)}header p{margin:0;color:#c5d1e2}
main{max-width:1400px;margin:22px auto;padding:0 20px}.notice{padding:13px 16px;border:1px solid #e8c879;background:#fff9e8;border-radius:10px;margin-bottom:18px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px}.card{background:white;border:1px solid var(--line);border-radius:13px;padding:17px;box-shadow:0 3px 13px #2036530b}
h2{font-size:1.15rem;margin:0 0 12px}.chart{width:100%;height:auto;min-height:180px}.muted{color:var(--muted)}.metrics{overflow:auto}
table{border-collapse:collapse;width:100%;font-size:.87rem}th,td{text-align:left;padding:8px 9px;border-bottom:1px solid var(--line);vertical-align:top}th{white-space:nowrap;color:#52637d}
.controls{display:flex;gap:12px;flex-wrap:wrap;margin:10px 0}.controls select{padding:9px 12px;border:1px solid var(--line);border-radius:8px;background:white}
.sample{display:grid;grid-template-columns:minmax(240px,1fr) minmax(280px,2fr);gap:18px;align-items:start}.sample img{max-width:100%;max-height:340px;object-fit:contain;background:#fff;border:1px solid var(--line);border-radius:8px}
.prediction{white-space:pre-wrap;overflow-wrap:anywhere;padding:10px;background:#f5f7fb;border-radius:8px;margin:6px 0}.substituted{background:#ffdf94}.inserted{background:#b8e4c5}.deleted{background:#ffc9c9;text-decoration:line-through}
.error{color:#9e3333}.pill{display:inline-block;padding:3px 8px;border-radius:99px;background:#e8eef8;margin:2px}.method{font-size:.88rem;color:var(--muted)}
mark{padding:1px 2px;border-radius:3px}.heat{display:grid;grid-template-columns:repeat(auto-fit,minmax(18px,1fr));gap:2px;max-width:570px}
 .heat-cell{aspect-ratio:1;display:grid;place-items:center;min-width:16px;font-size:9px;overflow:hidden}
footer{max-width:1400px;margin:5px auto 35px;padding:0 20px;color:var(--muted)}svg text{font-family:inherit}
@media(max-width:720px){.sample{grid-template-columns:1fr}main{padding:0 12px}.card{padding:13px}}
</style></head><body><header><h1>Handwriting Recognition Benchmark</h1>
<p>Independent model inference on the same held-out handwriting lines · local, standalone report</p></header>
<main><div class="notice"><b>Research integrity:</b> missing runs are marked NOT RUN; metrics use only successful model outputs.
Confidence calibration is N/A unless a valid validation-fitted artifact exists.</div>
<section class="grid" id="charts"></section>
<section class="card metrics" style="margin-top:16px"><h2>Measured results</h2><div id="table"></div>
<p class="method">CER/WER are Levenshtein edits divided by reference characters/words. Sequence precision/recall/F1 align tokens:
matches are TP; substitutions are FP+FN; insertions FP; deletions FN. Character macro F1 averages observed classes;
weighted F1 weights by reference support. Character/word alignment accuracy is aligned matches divided by reference units.
These are sequence-alignment metrics, not sentence-classification scores.</p></section>
<section class="card" style="margin-top:16px"><h2>Measured conclusions and paired comparisons</h2><div id="conclusions"></div></section>
<section class="card" style="margin-top:16px"><h2>Example-level error analysis</h2>
<div class="controls"><label>Test sample <select id="sample"></select></label></div>
<div class="sample"><div><img id="image" alt="Selected handwritten test line"><p id="sampleInfo" class="muted"></p></div>
<div id="sampleDetail"></div></div></section>
<section class="card" style="margin-top:16px"><h2>Run metadata and limitations</h2><div id="metadata"></div></section>
</main><footer>Generated locally. Handwriting images are embedded in this HTML; keep the report private if samples are sensitive.</footer>
<script id="payload" type="application/json">__PAYLOAD__</script>
<script>
const D=JSON.parse(document.getElementById('payload').textContent), colors=['#4776c6','#e5a13c','#4c9a72'];
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt=x=>x==null?'N/A':(typeof x==='number'?x.toFixed(3):esc(x));
function bar(title,key,lower=false){const rows=D.metrics,vals=rows.map(r=>r[key]),max=Math.max(.001,...vals.filter(v=>v!=null));
let w=520,h=220,left=150,right=30,rowH=48,svg=`<h2>${esc(title)}</h2><svg class=\"chart\" viewBox=\"0 0 ${w} ${h}\" role=\"img\" aria-label=\"${esc(title)}\">`;
rows.forEach((r,i)=>{let y=25+i*rowH,v=vals[i],width=v==null?0:(w-left-right)*Math.max(0,v)/max;svg+=`<text x=\"${left-8}\" y=\"${y+19}\" text-anchor=\"end\" font-size=\"12\">${esc(r.model_label)}</text><rect x=\"${left}\" y=\"${y}\" width=\"${width}\" height=\"25\" rx=\"4\" fill=\"${colors[i%3]}\"/><text x=\"${left+width+6}\" y=\"${y+18}\" font-size=\"12\">${fmt(v)}</text>`});svg+='</svg><p class=\"muted\">'+(lower?'Lower is better.':'Higher is better.')+'</p>';return `<article class=\"card\">${svg}</article>`}
function latency(){const vals=D.metrics.map(r=>r.median_latency_seconds),max=Math.max(.001,...vals.filter(v=>v!=null)),w=520,h=220,left=150;
let s='<article class=\"card\"><h2>Median latency (seconds)</h2><svg class=\"chart\" viewBox=\"0 0 520 220\">';D.metrics.forEach((r,i)=>{let y=25+i*48,v=vals[i],width=v==null?0:340*v/max;s+=`<text x=\"140\" y=\"${y+18}\" text-anchor=\"end\" font-size=\"12\">${esc(r.model_label)}</text><rect x=\"150\" y=\"${y}\" width=\"${width}\" height=\"25\" rx=\"4\" fill=\"${colors[i%3]}\"/><text x=\"${156+width}\" y=\"${y+18}\" font-size=\"12\">${fmt(v)}</text>`});return s+'</svg></article>'}
function multi(title,keys,names){let rows=D.metrics,w=560,h=230,left=155,barH=18,gap=5,group=keys.length*(barH+gap)+14;
let maxima=keys.map(k=>Math.max(.001,...rows.map(r=>r[k]).filter(v=>v!=null))),s=`<article class=\"card\"><h2>${esc(title)}</h2><svg class=\"chart\" viewBox=\"0 0 ${w} ${Math.max(h,rows.length*group+30)}\">`;
rows.forEach((r,i)=>{s+=`<text x=\"${left-7}\" y=\"${i*group+14}\" text-anchor=\"end\" font-size=\"11\">${esc(r.model_label)}</text>`;
keys.forEach((key,j)=>{let v=r[key],y=i*group+j*(barH+gap),width=v==null?0:350*v/maxima[j];s+=`<rect x=\"${left}\" y=\"${y}\" width=\"${width}\" height=\"${barH}\" fill=\"${colors[j%3]}\"/><text x=\"${left+width+4}\" y=\"${y+14}\" font-size=\"10\">${fmt(v)} ${esc(names[j])}</text>`})});
return s+'</svg><p class=\"muted\">Higher is better.</p></article>'}
function accuracyLatency(){let points=D.metrics.filter(r=>r.median_latency_seconds!=null&&r.character_alignment_accuracy!=null),xs=points.map(r=>r.median_latency_seconds),min=Math.min(...xs,0),max=Math.max(.001,...xs),s='<article class=\"card\"><h2>Accuracy versus latency</h2><svg class=\"chart\" viewBox=\"0 0 520 260\"><line x1=\"60\" y1=\"220\" x2=\"490\" y2=\"220\" stroke=\"#9aa8bb\"/><line x1=\"60\" y1=\"20\" x2=\"60\" y2=\"220\" stroke=\"#9aa8bb\"/>';
points.forEach(r=>{let i=D.metrics.indexOf(r),x=70+400*(r.median_latency_seconds-min)/(max-min||1),y=210-175*(r.character_alignment_accuracy);s+=`<circle cx=\"${x}\" cy=\"${y}\" r=\"7\" fill=\"${colors[i%3]}\"/><text x=\"${x+8}\" y=\"${y-8}\" font-size=\"11\">${esc(r.model_label)}</text>`});return s+'</svg><p class=\"muted\">X: median local inference seconds. Y: character alignment accuracy; higher and faster is preferred.</p></article>'}
function confusionCard(name){let d=D.confusions[name],s=`<article class=\"card\"><h2>${esc(D.labels[name])} character confusion · top classes</h2>`;
if(!d||!d.labels.length)return s+'<p class=\"muted\">N/A — no predictions.</p></article>';
let max=Math.max(1,...d.matrix.flat()),n=d.labels.length,step=Math.min(22,350/n),width=530,height=Math.max(220,100+n*step);s+=`<svg class=\"chart\" viewBox=\"0 0 ${width} ${height}\"><text x=\"${width/2}\" y=\"15\" text-anchor=\"middle\" font-size=\"11\">Predicted character →</text><text x=\"12\" y=\"${height/2}\" transform=\"rotate(-90 12 ${height/2})\" text-anchor=\"middle\" font-size=\"11\">Ground-truth character →</text>`;
d.labels.forEach((label,j)=>{let show=label===' '?'␠':label;s+=`<text x=\"${150+j*step+step/2}\" y=\"42\" transform=\"rotate(-55 ${150+j*step+step/2} 42)\" text-anchor=\"start\" font-size=\"9\">${esc(show)}</text>`});
d.matrix.forEach((row,i)=>{let show=d.labels[i]===' '?'␠':d.labels[i];s+=`<text x=\"140\" y=\"${58+i*step+step*.75}\" text-anchor=\"end\" font-size=\"9\">${esc(show)}</text>`;row.forEach((v,j)=>{let intensity=Math.round(255-150*v/max),title=`GT ${d.labels[i]} → ${d.labels[j]}: ${v}`;s+=`<rect x=\"${150+j*step}\" y=\"${52+i*step}\" width=\"${step}\" height=\"${step}\" fill=\"rgb(${intensity},${Math.min(255,intensity+15)},255)\"><title>${esc(title)}</title></rect>`})});
return s+'</svg><p class=\"muted\">Rows are ground-truth characters; columns are predicted characters. Insertion/deletion categories are reported separately.</p></article>'}
function errorCard(name){let rows=D.substitutions[name]||[],s=`<article class=\"card\"><h2>${esc(D.labels[name])} · top character substitutions</h2>`;
if(!rows.length)return s+'<p class=\"muted\">N/A — no substitutions observed.</p></article>';
let max=Math.max(...rows.map(r=>r.count),1);rows=rows.slice(0,10);s+='<svg class=\"chart\" viewBox=\"0 0 520 310\">';rows.forEach((r,i)=>{let y=10+i*28,w=300*r.count/max;s+=`<text x=\"140\" y=\"${y+15}\" text-anchor=\"end\" font-size=\"11\">${esc(JSON.stringify(r.ground_truth))} → ${esc(JSON.stringify(r.prediction))}</text><rect x=\"150\" y=\"${y}\" width=\"${w}\" height=\"19\" fill=\"#c75555\"/><text x=\"${155+w}\" y=\"${y+14}\" font-size=\"10\">${r.count}</text>`});return s+'</svg></article>'}
function calibrationCard(){return '<article class=\"card\"><h2>Confidence calibration</h2><p>N/A — the run has no valid validation-fitted per-prediction probability and held-out calibration. Raw model scores are not probabilities.</p><p>ECE, Brier score and reliability diagrams are intentionally not fabricated.</p></article>'}
function frequencyCard(name,kind){let rows=D.edit_frequencies[name]?.[kind]||[],s=`<article class=\"card\"><h2>${esc(D.labels[name])} · character ${esc(kind)}</h2>`;
if(!rows.length)return s+'<p class=\"muted\">None observed, or model not run.</p></article>';
let max=Math.max(...rows.map(r=>r.count),1);s+='<svg class=\"chart\" viewBox=\"0 0 520 230\">';rows.slice(0,8).forEach((r,i)=>{let y=10+i*27,w=300*r.count/max;s+=`<text x=\"140\" y=\"${y+15}\" text-anchor=\"end\" font-size=\"11\">${esc(JSON.stringify(r.character))}</text><rect x=\"150\" y=\"${y}\" width=\"${w}\" height=\"18\" fill=\"#6e91bd\"/><text x=\"${155+w}\" y=\"${y+14}\" font-size=\"10\">${r.count}</text>`});return s+'</svg></article>'}
function commandCard(){let any=D.metrics.some(r=>r.board_command_samples);if(!any)return '<article class=\"card\"><h2>@board command performance</h2><p>N/A — no test rows were labeled as @board commands.</p><p>End-to-end execution and manual-confirmation rates require a separate application workflow experiment.</p></article>';
return multi('@board command measures (end-to-end execution N/A)', ['command_transcription_accuracy','board_prefix_detection_accuracy','instruction_extraction_success_rate'],['exact text','prefix','instruction'])}
document.getElementById('charts').innerHTML=bar('Character Error Rate (CER)','cer',true)+bar('Word Error Rate (WER)','wer',true)+multi('F1-score comparison',['character_micro_f1','character_macro_f1','character_weighted_f1','word_micro_f1'],['char micro','char macro','char weighted','word micro'])+multi('Character precision and recall',['character_micro_precision','character_micro_recall'],['precision','recall'])+bar('Exact line match','exact_line_match_accuracy')+multi('Latency comparison',['average_latency_seconds','median_latency_seconds','p95_latency_seconds'],['mean','median','P95'])+accuracyLatency()+bar('Character substitutions','character_substitutions')+bar('Character insertions','character_insertions')+bar('Character deletions','character_deletions')+D.metrics.map(r=>confusionCard(r.model)).join('')+D.metrics.map(r=>errorCard(r.model)).join('')+D.metrics.map(r=>frequencyCard(r.model,'insertions')).join('')+D.metrics.map(r=>frequencyCard(r.model,'deletions')).join('')+calibrationCard()+commandCard();
const columns=[['model_label','Model'],['model_id','Actual model ID'],['run_status','Run'],['metric_samples','Shared N'],['cer','CER ↓'],['wer','WER ↓'],['character_alignment_accuracy','Character accuracy'],['word_alignment_accuracy','Word accuracy'],['exact_line_match_accuracy','Exact line'],['character_micro_precision','Char P (micro)'],['character_micro_recall','Char R (micro)'],['character_micro_f1','Char F1 (micro)'],['character_macro_f1','Char F1 (macro)'],['character_weighted_f1','Char F1 (weighted)'],['word_micro_f1','Word F1 (micro)'],['average_latency_seconds','Mean s'],['median_latency_seconds','Median s'],['p95_latency_seconds','P95 s'],['loading_seconds','Load s'],['model_size_bytes','Model bytes'],['successful_recognition_rate','Success rate'],['ece','ECE']];
document.getElementById('table').innerHTML='<table><thead><tr>'+columns.map(c=>`<th>${esc(c[1])}</th>`).join('')+'</tr></thead><tbody>'+D.metrics.map(r=>'<tr>'+columns.map(([key])=>`<td>${fmt(r[key])}</td>`).join('')+'</tr>').join('')+'</tbody></table>';
const valid=D.metrics.filter(r=>r.cer!=null),best=(key,lower=true)=>valid.length?valid.reduce((a,b)=>((lower?b[key]<a[key]:b[key]>a[key])?b:a)):null;
const bestCer=best('cer'),bestWer=best('wer'),bestChar=best('character_micro_f1',false),bestWord=best('word_micro_f1',false);
const tests=D.paired_tests.length?'<table><thead><tr><th>Paired models</th><th>Non-tied samples</th><th>Exact sign-test p</th><th>Interpretation</th></tr></thead><tbody>'+D.paired_tests.map(x=>`<tr><td>${esc(D.labels[x.first])} vs ${esc(D.labels[x.second])}</td><td>${x.test.comparable_non_ties}</td><td>${fmt(x.test.p_value)}</td><td>${esc(x.test.interpretation)}</td></tr>`).join('')+'</tbody></table>':'<p>No pairwise test: fewer than two models produced valid outputs.</p>';
document.getElementById('conclusions').innerHTML=`<p>Lowest observed CER: ${bestCer?`${esc(bestCer.model_label)} (${fmt(bestCer.cer)})`:'N/A'} · Lowest observed WER: ${bestWer?`${esc(bestWer.model_label)} (${fmt(bestWer.wer)})`:'N/A'} · Highest character micro F1: ${bestChar?`${esc(bestChar.model_label)} (${fmt(bestChar.character_micro_f1)})`:'N/A'} · Highest word micro F1: ${bestWord?`${esc(bestWord.model_label)} (${fmt(bestWord.word_micro_f1)})`:'N/A'}.</p><p class=\"muted\">Observed results on this test split only; they are not a generalizable ranking.</p>${tests}`;
const sample=document.getElementById('sample'),sampleIds=[...new Set(D.samples.map(x=>x.sample_id))];
sample.innerHTML=sampleIds.map(x=>`<option value=\"${esc(x)}\">${esc(x)}</option>`).join('');
function showSample(){const rows=D.samples.filter(x=>x.sample_id===sample.value),r=rows[0];if(!r)return;
document.getElementById('image').src=r.image||'';document.getElementById('sampleInfo').textContent=`Sample: ${r.sample_id} · ${r.status}`;
const models=rows.map(x=>{const edits=x.edits?`CER ${fmt(x.edits.cer)} · WER ${fmt(x.edits.wer)} · char edits ${x.edits.character_substitutions+x.edits.character_insertions+x.edits.character_deletions} · word edits ${x.edits.word_substitutions+x.edits.word_insertions+x.edits.word_deletions}`:'No metrics: prediction unavailable.';
const prediction=x.status==='success'||x.status==='empty'?x.diff_html:`<span class=\"error\">${esc(x.error||'Recognition failed')}</span>`;
return `<article class=\"card\"><h3>${esc(D.labels[x.model]||x.model)} · ${esc(x.status)} · ${esc(x.model_id||'')}</h3><div class=\"prediction\">${prediction||''}</div><p>${edits}</p><p class=\"muted\">Aligned edits: ${esc(JSON.stringify(x.edit_details))}</p><p class=\"muted\">Latency: ${fmt(x.latency_seconds)} s</p></article>`}).join('');
document.getElementById('sampleDetail').innerHTML=`<div><b>Ground truth</b><div class=\"prediction\">${esc(r.ground_truth)}</div><div class=\"grid\">${models}</div></div>`}
sample.addEventListener('change',showSample);showSample();
const md=D.metadata,ds=md.dataset,system=md.system;document.getElementById('metadata').innerHTML=`<p><b>Dataset:</b> ${esc(ds.source)} · ${ds.test_samples} evaluated lines · ${esc(ds.split_method)} · writer-disjoint: ${ds.writer_disjoint?'yes':'no'} · licence: ${esc(ds.license)}</p><p><b>Split counts:</b> ${esc(JSON.stringify(ds.split_counts))}</p><p><b>System:</b> ${esc(system.os)} · Python ${esc(system.python)} · CPU ${esc(system.cpu)} · RAM ${fmt(system.ram_total_bytes/1e9)} GB</p><p><b>Packages:</b> ${esc(JSON.stringify(md.library_versions))}</p><p><b>Confidence:</b> no ECE/Brier/reliability curve is claimed unless a held-out, calibrated confidence source is available. Model confidence values remain raw/unscored metadata.</p><p><b>Full run metadata:</b> available in run_metadata.json and summary.json.</p>`;
</script></body></html>"""
    page = page.replace("__PAYLOAD__", payload)
    (output / "index.html").write_text(page, encoding="utf-8")


def _markdown(output: Path, metrics: list[dict], metadata: dict,
              comparisons: list[dict]) -> None:
    dataset = metadata["dataset"]
    lines = [
        "# Handwriting Recognition Benchmark",
        "",
        f"- Dataset/source: {dataset['source']}",
        f"- Test lines evaluated: {dataset['test_samples']}",
        f"- Split methodology: {dataset['split_method']}",
        f"- Writer-disjoint: {dataset['writer_disjoint']}",
        f"- Manifest provenance/license: {dataset['license']}",
        "- Comparative quality metrics use the shared intersection of successful outputs for all initialized models; missing model runs are N/A, never zero-filled.",
        "",
        "## Results",
        "",
        "| Model | Actual model | Status | N | CER ↓ | WER ↓ | Exact line ↑ | Char micro F1 ↑ | Char macro F1 ↑ | Char weighted F1 ↑ | Word micro F1 ↑ | Mean/median/P95 seconds |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in metrics:
        ci = row.get("cer_bootstrap_95ci")
        cer = _fmt(row["cer"]) + (f" (bootstrap 95% CI {_fmt(ci[0])}–{_fmt(ci[1])})" if ci else "")
        latency = "/".join(_fmt(row[key]) for key in (
            "average_latency_seconds", "median_latency_seconds", "p95_latency_seconds"))
        lines.append(
            f"| {row['model_label']} | {row['model_id'] or 'N/A'} | {row['run_status']} | "
            f"{row['metric_samples']} | {cer} | {_fmt(row['wer'])} | "
            f"{_fmt(row['exact_line_match_accuracy'])} | {_fmt(row['character_micro_f1'])} | "
            f"{_fmt(row['character_macro_f1'])} | {_fmt(row['character_weighted_f1'])} | "
            f"{_fmt(row['word_micro_f1'])} | {latency} |"
        )
    successful = [row for row in metrics if row.get("cer") is not None]
    if successful:
        best_cer = min(successful, key=lambda row: row["cer"])
        best_wer = min(successful, key=lambda row: row["wer"])
        best_char = max(successful, key=lambda row: row["character_micro_f1"])
        best_word = max(successful, key=lambda row: row["word_micro_f1"])
        lines += [
            "",
            "## Findings",
            "",
            f"- Lowest measured CER: {best_cer['model_label']} ({best_cer['cer']:.4f}).",
            f"- Lowest measured WER: {best_wer['model_label']} ({best_wer['wer']:.4f}).",
            f"- Highest character micro F1: {best_char['model_label']} ({best_char['character_micro_f1']:.4f}).",
            f"- Highest word micro F1: {best_word['model_label']} ({best_word['word_micro_f1']:.4f}).",
        ]
    else:
        lines += ["", "## Findings", "", "No model produced evaluable predictions; no accuracy winner is reported."]
    local = [row for row in successful
             and row.get("median_latency_seconds") is not None]
    if local:
        fastest = min(local, key=lambda row: row["median_latency_seconds"])
        lowest_p95 = min(local, key=lambda row: row["p95_latency_seconds"])
        lines.append(f"- Fastest local median: {fastest['model_label']} ({fastest['median_latency_seconds']:.4f}s).")
        lines.append(f"- Lowest local P95: {lowest_p95['model_label']} ({lowest_p95['p95_latency_seconds']:.4f}s).")
        rank_sums = Counter()
        for key in ("cer", "wer", "median_latency_seconds"):
            for rank, row in enumerate(sorted(local, key=lambda item: item[key]), start=1):
                rank_sums[row["model"]] += rank
        winner = min(local, key=lambda row: (rank_sums[row["model"]], row["cer"], row["median_latency_seconds"]))
        lines.append(
            f"- Descriptive local accuracy/speed trade-off (sum of ranks across CER, WER, and median latency): "
            f"{winner['model_label']}; this is a descriptive pilot ranking, not a significance claim."
        )
    lines += ["", "### Paired CER comparisons", ""]
    if comparisons:
        lines.append("| Model A | Model B | Non-tied pairs | Exact paired sign-test p | Result |")
        lines.append("|---|---|---:|---:|---|")
        for item in comparisons:
            value = item["test"]
            lines.append(
                f"| {MODEL_LABELS[item['first']]} | {MODEL_LABELS[item['second']]} | "
                f"{value['comparable_non_ties']} | {_fmt(value['p_value'])} | {value['interpretation']} |"
            )
        lines.append("The two-sided exact sign test compares per-line CER on shared test samples and ignores ties. "
                     "A nominal p-value below 0.05 in a 10-line pilot is exploratory, not a generalizable winner claim; "
                     "paired tests do not repair dataset bias.")
    else:
        lines.append("No pair had enough jointly evaluated predictions for a paired comparison.")
    lines += [
        "",
        "## Confidence and limitations",
        "",
        "- TrOCR reports decoder sequence-level raw scores; they are not character-level probabilities. "
        "Only valid calibration fitted on validation data may be called calibrated.",
        "- Kraken raw character scores, when exposed, are preserved without interpreting them as calibrated probabilities.",
        "- Confidence is N/A when no validation-fitted calibration artifact is loaded.",
        "- ECE, Brier score and reliability diagrams are N/A without per-item calibrated correctness probabilities.",
        "- Inference latency is wall-clock for the local evaluation environment.",
        "- Bootstrap intervals resample the test lines 1,000 times and are descriptive, not a substitute for writer-disjoint evaluation.",
        "- No full-page layout/segmentation claim is made; this run evaluates text-line images only.",
        "",
        "## Reproducibility",
        "",
        f"- Run metadata: `run_metadata.json`",
        f"- Per-sample/model predictions: `predictions.csv`",
        f"- Example error analysis: `sample_errors.csv`",
        f"- Interactive dashboard: `index.html`",
    ]
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _fmt(value) -> str:
    return "N/A" if value is None else f"{value:.4f}" if isinstance(value, float) else str(value)


def generate_report(output: Path, samples: list[dict], predictions: list[dict], metadata: dict) -> None:
    output.mkdir(parents=True, exist_ok=True)
    metric_rows = _model_metrics(samples, predictions, metadata)
    combined = _sample_records(samples, predictions)
    common_ids = _common_sample_ids(samples, predictions, metadata)
    comparison_predictions = [item for item in predictions if item["sample_id"] in common_ids]
    _write_csv(output / "predictions.csv", predictions, PREDICTION_COLUMNS)
    _write_csv(output / "metrics.csv", metric_rows)

    errors = []
    for prediction in predictions:
        sample = next(row for row in samples if row["sample_id"] == prediction["sample_id"])
        metric = (evaluate_sequences([sample["ground_truth"]], [prediction.get("prediction") or ""])
                  if prediction.get("status") in ("success", "empty") else {})
        errors.append({
            "sample_id": sample["sample_id"],
            "image_path": sample["image_path"],
            "ground_truth": sample["ground_truth"],
            "model": prediction["model"],
            "model_id": prediction.get("model_id"),
            "prediction": prediction.get("prediction"),
            "status": prediction.get("status"),
            "character_error_count": metric.get("character_substitutions", 0)
                + metric.get("character_insertions", 0) + metric.get("character_deletions", 0)
                if metric else None,
            "word_error_count": metric.get("word_substitutions", 0)
                + metric.get("word_insertions", 0) + metric.get("word_deletions", 0)
                if metric else None,
            "substitutions": json.dumps(top_substitutions(
                [sample["ground_truth"]], [prediction.get("prediction") or ""], 100
            ), ensure_ascii=False) if metric else None,
            "edit_alignments": json.dumps(_edit_details(
                sample["ground_truth"], prediction.get("prediction") or ""
            ), ensure_ascii=False) if metric else None,
            "error": prediction.get("error"),
        })
    _write_csv(output / "sample_errors.csv", errors)
    for name in ("trocr", "kraken"):
        matching = [item for item in comparison_predictions
                    if item["model"] == name and item.get("status") in ("success", "empty")]
        refs = [item["ground_truth"] for item in matching]
        hyps = [item.get("prediction") or "" for item in matching]
        _write_csv(output / f"confusion_matrix_{name}.csv",
                   _confusion_rows(refs, hyps),
                   ("ground_truth_character", "predicted_character", "raw_count", "row_normalized"))
    comparisons = []
    ready = {item["model"] for item in predictions if item.get("status") in ("success", "empty")}
    for index, first in enumerate(("trocr", "kraken")):
        for second in ("trocr", "kraken")[index + 1:]:
            if first in ready and second in ready:
                comparisons.append({
                    "first": first, "second": second,
                    "test": _pairwise_sign_test(combined, first, second),
                })
    local_with_metrics = [item for item in metric_rows if item.get("cer") is not None
                          and item.get("wer") is not None
                          and item.get("median_latency_seconds") is not None]
    tradeoff = None
    if local_with_metrics:
        rank_sums = {}
        for key in ("cer", "wer", "median_latency_seconds"):
            for rank, item in enumerate(sorted(local_with_metrics, key=lambda row: row[key]), start=1):
                rank_sums[item["model"]] = rank_sums.get(item["model"], 0) + rank
        winner = min(local_with_metrics,
                     key=lambda row: (rank_sums[row["model"]], row["cer"], row["median_latency_seconds"]))
        tradeoff = {
            "model": winner["model"],
            "method": "lowest summed rank across local CER, WER, and median latency; descriptive only",
            "summed_ranks": rank_sums,
        }
    measured = [item for item in metric_rows if item.get("cer") is not None]
    best_cer = min(measured, key=lambda row: row["cer"], default=None)
    best_wer = min(measured, key=lambda row: row["wer"], default=None)
    best_char = max(measured, key=lambda row: row["character_micro_f1"], default=None)
    best_word = max(measured, key=lambda row: row["word_micro_f1"], default=None)
    local_measured = [item for item in measured if item.get("median_latency_seconds") is not None
                      and item.get("p95_latency_seconds") is not None]
    fastest_local = min(local_measured, key=lambda row: row["median_latency_seconds"], default=None)
    lowest_p95_local = min(local_measured, key=lambda row: row["p95_latency_seconds"], default=None)
    summary = {
        "dataset": metadata["dataset"],
        "metrics": metric_rows,
        "paired_cer_sign_tests": comparisons,
        "conclusions": {
            "best_cer": best_cer["model"] if best_cer else None,
            "best_wer": best_wer["model"] if best_wer else None,
            "best_character_micro_f1": best_char["model"] if best_char else None,
            "best_word_micro_f1": best_word["model"] if best_word else None,
            "fastest_local_model": fastest_local["model"] if fastest_local else None,
            "lowest_local_p95_model": lowest_p95_local["model"] if lowest_p95_local else None,
            "statistical_significance_claimed": False,
            "best_overall_tradeoff": tradeoff,
        },
        "metadata": metadata,
    }
    _write_summary(output / "summary.json", summary)
    _write_summary(output / "run_metadata.json", metadata)
    _markdown(output, metric_rows, metadata, comparisons)
    _chart_pngs(output, metric_rows, combined, comparison_predictions)
    _dashboard(output, metric_rows, combined, predictions, comparison_predictions, metadata)


def _write_summary(path: Path, content: dict) -> None:
    path.write_text(json.dumps(content, ensure_ascii=False, indent=2, allow_nan=False, default=str) + "\n",
                    encoding="utf-8")


def regenerate_report(predictions_path: Path, metadata_path: Path, output: Path,
                      manifest_path: Optional[Path] = None) -> None:
    with predictions_path.open(encoding="utf-8-sig", newline="") as stream:
        predictions = list(csv.DictReader(stream))
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    manifest_samples = None
    if manifest_path:
        from evaluation.benchmark_htr import load_manifest
        manifest_samples, dataset = load_manifest(
            manifest_path, metadata.get("execution", {}).get("limit")
        )
        prediction_ids = {row["sample_id"] for row in predictions}
        manifest_ids = {row["sample_id"] for row in manifest_samples}
        if prediction_ids != manifest_ids:
            raise ValueError("The provided manifest test rows do not match the saved predictions")
        metadata["dataset"] = dataset
        manifest_by_id = {sample["sample_id"]: sample for sample in manifest_samples}
        for prediction in predictions:
            sample = manifest_by_id[prediction["sample_id"]]
            prediction.update({
                "image_path": sample["image_path"],
                "ground_truth": sample["ground_truth"],
                "writer_id": sample["writer_id"],
                "split": sample["split"],
                "source": sample["source"],
                "category": sample["category"],
            })
    samples_by_id: dict[str, dict] = (
        {sample["sample_id"]: dict(sample) for sample in manifest_samples}
        if manifest_samples else {}
    )
    for row in predictions:
        sample = samples_by_id.setdefault(row["sample_id"], {
            "sample_id": row["sample_id"],
            "image_path": row["image_path"],
            "ground_truth": row["ground_truth"],
            "writer_id": row["writer_id"],
            "split": row["split"],
            "source": row["source"],
            "category": row["category"],
            "license": "",
        })
        if row.get("prediction") is not None:
            row["prediction"] = row["prediction"]
        for key in ("latency_seconds", "network_seconds", "confidence"):
            row[key] = float(row[key]) if row.get(key) not in (None, "") else None
        row["image_data_url"] = _image_url(row["image_path"])
    generate_report(output, list(samples_by_id.values()), predictions, metadata)
