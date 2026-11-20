import csv
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from evaluation.benchmark_htr import load_manifest, prepare_manifest
from evaluation.metrics import align_sequences, character_confusion, evaluate_sequences
from evaluation.report import generate_report


class SequenceMetricTests(unittest.TestCase):
    def test_exact_and_substitution_metrics(self):
        result = evaluate_sequences(["cat"], ["cut"])
        self.assertAlmostEqual(result["cer"], 1 / 3)
        self.assertAlmostEqual(result["character_alignment_accuracy"], 2 / 3)
        self.assertAlmostEqual(result["character_micro_precision"], 2 / 3)
        self.assertAlmostEqual(result["character_micro_recall"], 2 / 3)
        self.assertAlmostEqual(result["character_micro_f1"], 2 / 3)
        self.assertEqual(result["character_substitutions"], 1)
        self.assertEqual(result["exact_line_match_accuracy"], 0)

    def test_insertions_and_deletions_are_aligned(self):
        insertion = align_sequences(list("ab"), list("axb"))
        deletion = align_sequences(list("axb"), list("ab"))
        self.assertEqual(insertion.edits, 1)
        self.assertIn((None, "x"), insertion.pairs)
        self.assertEqual(deletion.edits, 1)
        self.assertIn(("x", None), deletion.pairs)
        self.assertEqual(character_confusion(["ab"], ["axb"])[("<INSERTION>", "x")], 1)
        self.assertEqual(character_confusion(["axb"], ["ab"])[("x", "<DELETION>")], 1)

    def test_word_metrics_use_token_alignment_not_sentence_classes(self):
        result = evaluate_sequences(["one two"], ["one too"])
        self.assertEqual(result["wer"], 0.5)
        self.assertEqual(result["word_substitutions"], 1)
        self.assertEqual(result["word_micro_f1"], 1 / 2)

    def test_unicode_punctuation_and_empty_hypothesis(self):
        result = evaluate_sequences(["café, 世界!"], ["café 世界!"])
        self.assertEqual(result["character_deletions"], 1)
        self.assertGreater(result["cer"], 0)
        empty = evaluate_sequences(["handwriting"], [""])
        self.assertEqual(empty["character_deletions"], len("handwriting"))
        self.assertEqual(empty["character_micro_f1"], 0)

    def test_reference_hypothesis_length_mismatch_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "equal lengths"):
            evaluate_sequences(["a"], [])


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for index, name in enumerate(("a.png", "b.png", "c.png", "d.png")):
            Image.new("RGB", (10, 10), (index * 50, 0, 0)).save(self.root / name)

    def tearDown(self):
        self.temp.cleanup()

    def write_source(self, writer_ids):
        path = self.root / "source.csv"
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=("image_path", "text", "writer_id"))
            writer.writeheader()
            for index, name in enumerate(("a.png", "b.png", "c.png", "d.png")):
                writer.writerow({"image_path": name, "text": f"line {index}", "writer_id": writer_ids[index]})
        return path

    def test_manifest_prepare_uses_line_split_when_writers_unknown(self):
        source = self.write_source(["unknown"] * 4)
        original = source.read_bytes()
        output = self.root / "prepared.csv"
        summary = prepare_manifest(source, output, seed=7)
        self.assertEqual(summary["split_method"], "line-level (writer IDs unavailable)")
        self.assertEqual(sum(summary["split_counts"].values()), 4)
        self.assertEqual(load_manifest(output)[1]["writer_disjoint"], False)
        self.assertEqual(source.read_bytes(), original)

    def test_manifest_prepare_keeps_writers_in_one_split(self):
        source = self.write_source(["alice", "bob", "carol", "dave"])
        output = self.root / "prepared.csv"
        summary = prepare_manifest(source, output, seed=4)
        self.assertEqual(summary["split_method"], "writer-disjoint")
        _, info = load_manifest(output)
        self.assertTrue(info["writer_disjoint"])

    def test_evaluation_requires_explicit_test_split(self):
        source = self.write_source(["unknown"] * 4)
        with self.assertRaisesRegex(ValueError, "prepare-manifest"):
            load_manifest(source)

    def test_missing_image_is_an_error(self):
        source = self.root / "bad.csv"
        source.write_text("image_path,text,split\nmissing.png,label,test\n", encoding="utf-8")
        with self.assertRaisesRegex(FileNotFoundError, "does not exist"):
            load_manifest(source)

    def test_empty_ground_truth_is_rejected(self):
        source = self.root / "empty.csv"
        source.write_text("image_path,text,split\na.png,,test\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Empty ground_truth"):
            load_manifest(source)

    def test_duplicate_sample_ids_are_rejected(self):
        source = self.root / "duplicate-id.csv"
        source.write_text(
            "sample_id,image_path,text,split\nsame,a.png,first,test\nsame,b.png,second,train\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "Duplicate sample_id"):
            load_manifest(source)

    def test_same_image_cannot_leak_across_splits(self):
        source = self.root / "duplicate-image.csv"
        source.write_text(
            "sample_id,image_path,text,split\none,a.png,first,test\ntwo,a.png,second,train\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "Duplicate image path"):
            load_manifest(source)

    def test_writer_leakage_across_existing_splits_is_rejected(self):
        source = self.root / "writer-leak.csv"
        source.write_text(
            "sample_id,image_path,text,writer_id,split\n"
            "one,a.png,first,alice,train\ntwo,b.png,second,alice,test\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "Writer leakage"):
            load_manifest(source)


class ReportTests(unittest.TestCase):
    def test_report_outputs_are_created_and_not_zero_filled_for_not_run_model(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "line.png"
            Image.new("RGB", (30, 12), "white").save(image)
            samples = [{
                "sample_id": "sample-1", "image_path": str(image), "ground_truth": "Hello!",
                "writer_id": "writer", "split": "test", "source": "fixture",
                "category": "handwriting", "license": "test fixture",
            }]
            predictions = [
                {"sample_id": "sample-1", "image_path": str(image), "ground_truth": "Hello!",
                 "writer_id": "writer", "split": "test", "source": "fixture", "category": "handwriting",
                 "model": "trocr", "model_id": "fixture/trocr", "prediction": "Hello!",
                 "status": "success", "latency_seconds": 0.1, "network_seconds": None,
                 "confidence": None, "confidence_status": "unavailable",
                 "confidence_details_json": None, "error": None, "image_data_url": "data:image/png;base64,",
                 },
                {"sample_id": "sample-1", "image_path": str(image), "ground_truth": "Hello!",
                 "writer_id": "writer", "split": "test", "source": "fixture", "category": "handwriting",
                 "model": "kraken", "model_id": "NOT RUN", "prediction": None,
                 "status": "error", "latency_seconds": None, "network_seconds": None,
                 "confidence": None, "confidence_status": "unavailable",
                 "confidence_details_json": None, "error": "dependency unavailable", "image_data_url": None,
                 },
            ]
            metadata = {
                "dataset": {"source": "fixture", "test_samples": 1, "split_method": "line-level",
                            "writer_disjoint": False, "license": "test", "split_counts": {"test": 1}},
                "engines": [
                    {"model": "trocr", "model_id": "fixture/trocr", "model_source": "baseline",
                     "status": "ready", "loading_seconds": 0.01, "model_size_bytes": None},
                    {"model": "kraken", "model_id": "NOT RUN", "model_source": None,
                     "status": "not_run", "error": "dependency unavailable",
                     "loading_seconds": 0, "model_size_bytes": None},
                ],
                "system": {"os": "test", "python": "3", "cpu": "test", "ram_total_bytes": 1000},
                "library_versions": {},
            }
            generate_report(root, samples, predictions, metadata)
            self.assertTrue((root / "index.html").is_file())
            self.assertTrue((root / "report.md").is_file())
            self.assertTrue((root / "summary.json").is_file())
            with (root / "metrics.csv").open(encoding="utf-8-sig", newline="") as stream:
                rows = {row["model"]: row for row in csv.DictReader(stream)}
            self.assertEqual(rows["trocr"]["cer"], "0.0")
            self.assertTrue(rows["trocr"]["cer_bootstrap_95ci"])
            self.assertEqual(rows["kraken"]["cer"], "")
            self.assertEqual(rows["kraken"]["run_status"], "not_run")


if __name__ == "__main__":
    unittest.main()
