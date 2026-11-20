#!/usr/bin/env python3
"""Run independent, same-sample HTR evaluations and export reproducible results."""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import math
import os
import platform
import random
import sys
import time
import threading
from pathlib import Path
from typing import Any, Optional

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

from evaluation.metrics import character_confusion, evaluate_sequences, top_substitutions

MODEL_IDS = {
    "trocr": "configured checkpoint or microsoft/trocr-small-handwritten",
    "kraken": "small-models-for-glam/kraken-ppocrv6-small",
}
ALIASES = {
    "image_path": ("image_path", "image", "path"),
    "ground_truth": ("ground_truth", "text", "transcription", "label"),
    "sample_id": ("sample_id", "id"),
    "writer_id": ("writer_id", "writer"),
    "split": ("split", "set"),
    "source": ("source", "dataset"),
    "category": ("category", "type"),
}


def _column(row: dict[str, str], field: str, required: bool = False) -> str:
    for name in ALIASES[field]:
        if name in row:
            return (row.get(name) or "").strip()
    if required:
        raise ValueError(f"Manifest is missing required column '{field}'")
    return ""


def _resolve_path(path: str, manifest: Path) -> Path:
    resolved = Path(path).expanduser()
    return resolved.resolve() if resolved.is_absolute() else (manifest.parent / resolved).resolve()


def load_manifest(manifest_path: Path, limit: Optional[int] = None) -> tuple[list[dict], dict]:
    """Validate labels, split, paths, IDs and duplicate image content."""
    manifest_path = manifest_path.expanduser().resolve()
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")
    with manifest_path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames:
            raise ValueError("Manifest has no CSV header")
        rows = list(reader)
        columns = reader.fieldnames
    seen_ids: set[str] = set()
    seen_paths: dict[str, str] = {}
    normalized: list[dict] = []
    for line_number, row in enumerate(rows, start=2):
        image_value = _column(row, "image_path", required=True)
        label = _column(row, "ground_truth", required=True)
        if not image_value:
            raise ValueError(f"Empty image_path at manifest line {line_number}")
        if not label:
            raise ValueError(f"Empty ground_truth at manifest line {line_number}")
        image_path = _resolve_path(image_value, manifest_path)
        if not image_path.is_file():
            raise FileNotFoundError(f"Image at manifest line {line_number} does not exist: {image_path}")
        try:
            with Image.open(image_path) as image:
                image.verify()
        except Exception as exc:
            raise ValueError(f"Invalid image at manifest line {line_number}: {image_path}: {exc}") from exc
        sample_id = _column(row, "sample_id") or hashlib.sha256(
            f"{image_path}\0{label}".encode("utf-8")).hexdigest()[:16]
        if str(image_path) in seen_paths:
            raise ValueError(f"Duplicate image path: {seen_paths[str(image_path)]} and {sample_id}")
        seen_paths[str(image_path)] = sample_id
        if sample_id in seen_ids:
            raise ValueError(f"Duplicate sample_id '{sample_id}' at manifest line {line_number}")
        seen_ids.add(sample_id)
        split = _column(row, "split").lower()
        if split not in ("train", "validation", "test"):
            raise ValueError(
                f"Manifest line {line_number} has no valid train/validation/test split. "
                "Run prepare-manifest first; do not evaluate an unassigned split."
            )
        if split != "test":
            continue
        normalized.append({
            "sample_id": sample_id,
            "image_path": str(image_path),
            "ground_truth": label,
            "writer_id": _column(row, "writer_id") or "unknown",
            "split": split,
            "source": _column(row, "source") or manifest_path.stem,
            "category": _column(row, "category") or "handwriting",
            "license": (row.get("license") or "").strip(),
        })
    if not normalized:
        raise ValueError("Manifest contains no test samples")
    if limit is not None:
        if limit < 1:
            raise ValueError("--limit must be a positive integer")
        normalized = normalized[:limit]
    image_hashes: dict[str, str] = {}
    for sample in normalized:
        digest = hashlib.sha256(Path(sample["image_path"]).read_bytes()).hexdigest()
        if digest in image_hashes:
            raise ValueError(
                f"Duplicate test images: {image_hashes[digest]} and {sample['sample_id']}"
            )
        image_hashes[digest] = sample["sample_id"]
    assigned = [(_column(row, "split") or "unassigned").lower() for row in rows]
    counts = {name: assigned.count(name) for name in ("train", "validation", "test", "unassigned")}
    writer_ids = {_column(row, "writer_id").lower() for row in rows}
    writer_disjoint = bool(writer_ids and "unknown" not in writer_ids and "" not in writer_ids)
    declared_methods = {row.get("split_method", "").strip() for row in rows if row.get("split_method", "").strip()}
    if len(declared_methods) > 1:
        raise ValueError("Manifest contains conflicting split_method values")
    declared_seeds = {row.get("split_seed", "").strip() for row in rows if row.get("split_seed", "").strip()}
    if len(declared_seeds) > 1:
        raise ValueError("Manifest contains conflicting split_seed values")
    if writer_disjoint:
        split_writers = {
            split: {_column(row, "writer_id") for row in rows if _column(row, "split").lower() == split}
            for split in ("train", "validation", "test")
        }
        for first, second in (("train", "validation"), ("train", "test"), ("validation", "test")):
            if split_writers[first] & split_writers[second]:
                raise ValueError(f"Writer leakage between {first} and {second} splits")
    return normalized, {
        "manifest": str(manifest_path), "columns": columns, "manifest_rows": len(rows),
        "split_counts": counts,
        "split_method": next(iter(declared_methods), (
            "writer-disjoint" if writer_disjoint else "line-level (writer IDs unavailable)"
        )),
        "split_seed": next(iter(declared_seeds), None),
        "writer_disjoint": writer_disjoint,
        "test_samples": len(normalized),
        "source": normalized[0]["source"],
        "license": next((sample["license"] for sample in normalized if sample["license"]), "not specified in manifest"),
    }


def prepare_manifest(source_path: Path, output_path: Path, seed: int = 42,
                     provenance: Optional[str] = None, license_name: Optional[str] = None) -> dict:
    """Create a deterministic 80/10/10 split without modifying the source CSV."""
    source_path = source_path.expanduser().resolve()
    with source_path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames:
            raise ValueError("Source manifest has no CSV header")
        source_rows, fieldnames = list(reader), list(reader.fieldnames)
    if any(_column(row, "split") for row in source_rows):
        raise ValueError("Source already contains split assignments; refusing to overwrite or reassign them")
    source_ids: set[str] = set()
    source_paths: set[str] = set()
    image_column = next((name for name in ALIASES["image_path"] if name in fieldnames), None)
    if image_column is None:
        raise ValueError("Source manifest is missing required column 'image_path'")
    for index, row in enumerate(source_rows, start=2):
        image_value = _column(row, "image_path")
        if not image_value or not _column(row, "ground_truth"):
            raise ValueError(f"Missing image_path or ground_truth at source line {index}")
        image_path = _resolve_path(image_value, source_path)
        if not image_path.is_file():
            raise FileNotFoundError(f"Image at source line {index} does not exist: {image_path}")
        try:
            with Image.open(image_path) as image:
                image.verify()
        except Exception as exc:
            raise ValueError(f"Invalid image at source line {index}: {image_path}: {exc}") from exc
        if str(image_path) in source_paths:
            raise ValueError(f"Duplicate image path at source line {index}: {image_path}")
        source_paths.add(str(image_path))
        sample_id = _column(row, "sample_id") or hashlib.sha256(
            f"{image_path}\0{_column(row, 'ground_truth')}".encode("utf-8")
        ).hexdigest()[:16]
        if sample_id in source_ids:
            raise ValueError(f"Duplicate sample_id '{sample_id}' at source line {index}")
        source_ids.add(sample_id)
        row[image_column] = str(image_path)
    writers = [_column(row, "writer_id") for row in source_rows]
    writer_disjoint = all(writer and writer.lower() != "unknown" for writer in writers)
    rng = random.Random(seed)
    assignments = [""] * len(source_rows)
    if writer_disjoint:
        groups: dict[str, list[int]] = {}
        for index, writer in enumerate(writers):
            groups.setdefault(writer, []).append(index)
        group_names = list(groups)
        if len(group_names) < 3:
            raise ValueError("A writer-disjoint train/validation/test split requires at least three writers")
        rng.shuffle(group_names)
        total = len(source_rows)
        targets = {"train": total * 0.8, "validation": total * 0.1, "test": total * 0.1}
        counts = {"train": 0, "validation": 0, "test": 0}
        for group_index, writer in enumerate(group_names):
            group = groups[writer]
            remaining = {split: target - counts[split] for split, target in targets.items()}
            groups_left = len(group_names) - group_index
            unassigned_holdouts = [split for split in ("validation", "test") if counts[split] == 0]
            if groups_left <= len(unassigned_holdouts):
                split = unassigned_holdouts[0]
            else:
                split = max(("train", "validation", "test"), key=lambda item: remaining[item])
            for index in group:
                assignments[index] = split
            counts[split] += len(group)
        method = "writer-disjoint"
    else:
        if len(source_rows) < 3:
            raise ValueError("A train/validation/test line split requires at least three samples")
        indices = list(range(len(source_rows)))
        rng.shuffle(indices)
        train_end = min(len(indices) - 2, max(1, int(len(indices) * 0.8)))
        validation_end = min(len(indices) - 1, train_end + max(1, int(len(indices) * 0.1)))
        for position, index in enumerate(indices):
            assignments[index] = "train" if position < train_end else (
                "validation" if position < validation_end else "test")
        method = "line-level (writer IDs unavailable)"
    if "sample_id" not in fieldnames:
        fieldnames.insert(0, "sample_id")
    if "split" not in fieldnames:
        fieldnames.append("split")
    for column in ("split_method", "split_seed", "source", "license"):
        if column not in fieldnames:
            fieldnames.append(column)
    output_path = output_path.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for index, row in enumerate(source_rows):
            sample_id = _column(row, "sample_id") or hashlib.sha256(
                f"{_column(row, 'image_path')}\0{_column(row, 'ground_truth')}".encode("utf-8")
            ).hexdigest()[:16]
            row["sample_id"], row["split"] = sample_id, assignments[index]
            row["split_method"], row["split_seed"] = method, seed
            row["source"] = row.get("source") or provenance or source_path.stem
            row["license"] = row.get("license") or license_name or "not specified in source manifest"
            writer.writerow(row)
    return {
        "output": str(output_path), "samples": len(source_rows), "split_method": method,
        "split_counts": {split: assignments.count(split) for split in ("train", "validation", "test")},
        "seed": seed,
    }


def image_data_url(image_path: str) -> str:
    with Image.open(image_path) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        stream = io.BytesIO()
        image.save(stream, format="PNG")
    return "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode("ascii")


def _file_size(path: Optional[Path]) -> Optional[int]:
    if not path or not path.exists():
        return None
    if path.is_file():
        return path.stat().st_size
    return sum(entry.stat().st_size for entry in path.rglob("*") if entry.is_file())


def _huggingface_model_size(repo_id: str) -> Optional[int]:
    try:
        from huggingface_hub import hf_hub_download
        config = Path(hf_hub_download(repo_id, "config.json", local_files_only=True))
        return _file_size(config.parent)
    except Exception:
        return None


class TrOCREngine:
    name = "trocr"

    def initialize(self):
        from models.trocr_htr import TrOCRService
        checkpoint = os.getenv("TROCR_CHECKPOINT", "./models/trocr-iam")
        self.service = TrOCRService(checkpoint=checkpoint, allow_baseline=True)
        self.service.device = "cpu"
        started = time.perf_counter()
        if not self.service.initialize():
            raise RuntimeError(self.service.load_error or "TrOCR model is unavailable")
        self.loading_seconds = time.perf_counter() - started
        self.download_seconds = None
        self.model_load_seconds = self.loading_seconds
        self.model_id = self.service.model_name or MODEL_IDS[self.name]
        self.model_source = self.service.model_source
        self.model_size_bytes = (
            _file_size(Path(self.service.checkpoint)) if self.model_source == "fine_tuned"
            else _huggingface_model_size(self.model_id)
        )
        from PIL import ImageDraw
        image = Image.new("RGB", (320, 80), "white")
        ImageDraw.Draw(image).line((12, 40, 300, 40), fill="black", width=4)
        self.recognize(image)

    def recognize(self, image: Image.Image) -> dict:
        stream = io.BytesIO()
        image.save(stream, format="PNG")
        encoded = "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode("ascii")
        result = self.service.recognize(encoded)
        return {
            "text": result.get("transcription", ""),
            "confidence": result.get("raw_confidence"),
            "confidence_status": result.get("confidence_status", "unavailable"),
            "confidence_details": {
                "sequence_log_probability": result.get("sequence_log_probability"),
                "token_count": result.get("token_count"),
                "calibrated_confidence": result.get("calibrated_confidence"),
            },
            "model_id": result.get("model_name") or self.model_id,
            "model_source": result.get("model_source"),
        }


class KrakenEngine:
    name = "kraken"

    def initialize(self):
        try:
            from huggingface_hub import hf_hub_download
            from kraken import rpred
            from kraken.containers import BBoxLine, Segmentation
            from kraken.lib.models import load_any
        except ImportError as exc:
            raise RuntimeError(
                "Kraken dependencies are missing. Install requirements-evaluation.txt."
            ) from exc
        started = time.perf_counter()
        model_path = hf_hub_download(
            repo_id="small-models-for-glam/kraken-ppocrv6-small",
            filename="small.safetensors",
        )
        self.download_seconds = time.perf_counter() - started
        load_started = time.perf_counter()
        self.model = load_any(model_path, device="cpu")
        self.model_load_seconds = time.perf_counter() - load_started
        self.rpred = rpred
        self.BBoxLine = BBoxLine
        self.Segmentation = Segmentation
        self.model_path = Path(model_path)
        self.model_id = MODEL_IDS[self.name]
        self.model_source = "pretrained"
        self.loading_seconds = time.perf_counter() - started
        self.model_size_bytes = _file_size(self.model_path)
        from PIL import ImageDraw
        image = Image.new("RGB", (320, 80), "white")
        ImageDraw.Draw(image).line((12, 40, 300, 40), fill="black", width=4)
        self.recognize(image)

    def recognize(self, image: Image.Image) -> dict:
        image = image.convert("RGB")
        segmentation = self.Segmentation(
            type="bbox",
            imagename="benchmark-line.png",
            text_direction="horizontal-lr",
            script_detection=False,
            lines=[self.BBoxLine(id="benchmark-line-0", bbox=(0, 0, image.width, image.height))],
        )
        predictions = list(self.rpred.rpred(self.model, image, segmentation))
        text = "\n".join(str(item.prediction) for item in predictions).strip()
        confidences = []
        for item in predictions:
            value = getattr(item, "confidences", None)
            if value is not None:
                try:
                    confidences.extend(float(score) for score in value)
                except (TypeError, ValueError):
                    pass
        return {
            "text": text,
            "confidence": None,
            "confidence_status": "raw_unvalidated" if confidences else "unavailable",
            "confidence_details": {"character_raw_scores": confidences or None},
            "model_id": self.model_id,
            "model_source": self.model_source,
        }


def _redact_error(error: str) -> str:
    key = os.getenv("GEMINI_API_KEY", "").strip()
    return error.replace(key, "[REDACTED]") if len(key) > 5 else error


class _PeakMemoryMonitor:
    def __init__(self):
        self.peak_bytes = None
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        try:
            import psutil
        except ImportError:
            return
        process = psutil.Process()

        def sample():
            while not self._stop.is_set():
                try:
                    value = process.memory_info().rss
                    self.peak_bytes = max(value, self.peak_bytes or 0)
                except psutil.Error:
                    pass
                self._stop.wait(0.1)

        self._thread = threading.Thread(target=sample, name="htr-peak-memory", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)


def run_benchmark(args: argparse.Namespace) -> Path:
    names = [name.strip().lower() for name in args.models.split(",") if name.strip()]
    if not names or any(name not in MODEL_IDS for name in names) or len(set(names)) != len(names):
        raise ValueError("--models must be a unique comma-separated subset of trocr,kraken")
    if args.cpu_threads < 1:
        raise ValueError("--cpu-threads must be at least one")
    os.environ["TROCR_DEVICE"] = "cpu"
    try:
        import torch
        torch.set_num_threads(max(1, args.cpu_threads))
    except ImportError:
        pass
    samples, dataset = load_manifest(Path(args.manifest), args.limit)
    output = Path(args.output).expanduser().resolve()
    plots_dir = output / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)
    predictions: list[dict] = []
    engine_metadata = []
    memory_monitor = _PeakMemoryMonitor()
    memory_monitor.start()
    for name in names:
        engine = _engine(name)
        start = time.perf_counter()
        try:
            engine.initialize()
            initialization_error = None
        except Exception as exc:
            initialization_error = _redact_error(f"{type(exc).__name__}: {exc}")
            print(f"{name}: NOT RUN: {initialization_error}", file=sys.stderr)
        loading_seconds = getattr(engine, "loading_seconds", time.perf_counter() - start)
        engine_metadata.append({
            "model": name,
            "model_id": getattr(engine, "model_id", MODEL_IDS[name]),
            "model_source": getattr(engine, "model_source", None),
            "status": "ready" if initialization_error is None else "not_run",
            "error": initialization_error,
            "loading_seconds": loading_seconds,
            "download_seconds": getattr(engine, "download_seconds", None),
            "model_load_seconds": getattr(engine, "model_load_seconds", loading_seconds),
            "model_size_bytes": getattr(engine, "model_size_bytes", None),
            "runtime": "local CPU",
        })
        for sample in samples:
            record = {
                **sample,
                "model": name,
                "model_id": getattr(engine, "model_id", MODEL_IDS[name]),
                "prediction": None,
                "status": "error" if initialization_error else "pending",
                "latency_seconds": None,
                "network_seconds": None,
                "confidence": None,
                "confidence_status": "unavailable",
                "confidence_details_json": None,
                "error": initialization_error,
                "image_data_url": None,
            }
            try:
                record["image_data_url"] = image_data_url(sample["image_path"])
            except Exception:
                pass
            if initialization_error is None:
                try:
                    with Image.open(sample["image_path"]) as image:
                        image = ImageOps.exif_transpose(image).convert("RGB")
                        start = time.perf_counter()
                        result = engine.recognize(image)
                        elapsed = time.perf_counter() - start
                    record.update({
                        "prediction": result.get("text", ""),
                        "status": "success" if result.get("text", "").strip() else "empty",
                        "latency_seconds": result.get("network_seconds", elapsed),
                        "network_seconds": result.get("network_seconds"),
                        "confidence": result.get("confidence"),
                        "confidence_status": result.get("confidence_status", "unavailable"),
                        "confidence_details_json": json.dumps(result.get("confidence_details"), ensure_ascii=False),
                        "model_id": result.get("model_id") or record["model_id"],
                        "error": None,
                    })
                except Exception as exc:
                    record.update({
                        "status": "error",
                        "error": _redact_error(f"{type(exc).__name__}: {exc}"),
                    })
                    print(f"{name}/{sample['sample_id']}: {record['error']}", file=sys.stderr)
            predictions.append(record)
            print(f"\r{name}: {len([r for r in predictions if r['model'] == name])}/{len(samples)}", end="", flush=True)
        print()
    memory_monitor.stop()
    from evaluation.report import generate_report
    metadata = build_metadata(dataset, engine_metadata, args, memory_monitor.peak_bytes)
    generate_report(output, samples, predictions, metadata)
    print(f"Report files written to {output}")
    return output


def build_metadata(dataset: dict, engines: list[dict], args: argparse.Namespace,
                   peak_ram_bytes: Optional[int] = None) -> dict:
    try:
        import psutil
        memory_total = psutil.virtual_memory().total
        process_memory = psutil.Process().memory_info().rss
    except ImportError:
        memory_total = process_memory = None
    cpu_name = platform.processor() or platform.machine()
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if line.lower().startswith("model name"):
                cpu_name = line.split(":", 1)[-1].strip()
                break
    except OSError:
        pass
    return {
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "dataset": dataset,
        "engines": engines,
        "execution": {
            "models_requested": [item.strip() for item in args.models.split(",")],
            "limit": args.limit,
            "seed": args.seed,
            "warmup_iterations": 1,
        },
        "system": {
            "os": platform.platform(),
            "python": platform.python_version(),
            "cpu": cpu_name,
            "logical_cpu_count": os.cpu_count(),
            "ram_total_bytes": memory_total,
            "process_ram_bytes_at_end": process_memory,
            "peak_ram_bytes": peak_ram_bytes,
        },
        "library_versions": _library_versions(),
    }


def _library_versions() -> dict:
    from importlib import metadata
    names = ("torch", "transformers", "kraken", "Pillow", "numpy", "matplotlib", "psutil", "huggingface_hub")
    versions = {}
    for name in names:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def main(argv: Optional[list[str]] = None) -> int:
    # Keep manifest preparation, inference, and report-only regeneration distinct.
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare-manifest", help="Create a fixed 80/10/10 split in a new CSV")
    prepare.add_argument("--manifest", required=True, help="Source CSV; never modified")
    prepare.add_argument("--output", required=True, help="New split-assigned CSV")
    prepare.add_argument("--seed", type=int, default=42)
    prepare.add_argument("--source", help="Provenance label/URL to fill when the source has none")
    prepare.add_argument("--license", dest="license_name",
                         help="Dataset licence to fill when the source has none")
    benchmark = subparsers.add_parser("run", help="Evaluate selected engines independently on every test sample")
    benchmark.add_argument("--manifest", required=True)
    benchmark.add_argument("--models", default="trocr")
    benchmark.add_argument("--limit", type=int, help="Evaluate only the first N test samples (use 10 for a pilot)")
    benchmark.add_argument("--output", default="reports/htr_comparison")
    benchmark.add_argument("--seed", type=int, default=42)
    benchmark.add_argument("--cpu-threads", type=int, default=1)
    regenerate = subparsers.add_parser("report", help="Regenerate report from a saved predictions.csv without inference")
    regenerate.add_argument("--predictions", required=True)
    regenerate.add_argument("--metadata", required=True)
    regenerate.add_argument("--manifest", help="Optional source manifest to refresh dataset provenance")
    regenerate.add_argument("--output", default="reports/htr_comparison")
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare-manifest":
            print(json.dumps(prepare_manifest(
                Path(args.manifest), Path(args.output), args.seed, args.source, args.license_name
            ), indent=2))
        elif args.command == "run":
            run_benchmark(args)
        else:
            from evaluation.report import regenerate_report
            regenerate_report(
                Path(args.predictions), Path(args.metadata), Path(args.output),
                Path(args.manifest) if args.manifest else None,
            )
        return 0
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        parser.exit(2, f"ERROR: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
