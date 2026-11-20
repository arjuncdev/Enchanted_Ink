"""Sequence-alignment metrics for handwriting recognition."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence


@dataclass(frozen=True)
class Alignment:
    edits: int
    pairs: tuple[tuple[Optional[str], Optional[str]], ...]


def align_sequences(reference: Sequence[str], hypothesis: Sequence[str]) -> Alignment:
    """Return a deterministic Levenshtein alignment (reference, hypothesis)."""
    rows, columns = len(reference) + 1, len(hypothesis) + 1
    costs = [[0] * columns for _ in range(rows)]
    back: list[list[str]] = [[""] * columns for _ in range(rows)]
    for i in range(1, rows):
        costs[i][0], back[i][0] = i, "delete"
    for j in range(1, columns):
        costs[0][j], back[0][j] = j, "insert"
    for i in range(1, rows):
        for j in range(1, columns):
            same = reference[i - 1] == hypothesis[j - 1]
            choices = (
                (costs[i - 1][j - 1] + (not same), "match" if same else "substitute", 0),
                (costs[i - 1][j] + 1, "delete", 1),
                (costs[i][j - 1] + 1, "insert", 2),
            )
            cost, operation, _ = min(choices, key=lambda item: (item[0], item[2]))
            costs[i][j], back[i][j] = int(cost), operation

    pairs: list[tuple[Optional[str], Optional[str]]] = []
    i, j = len(reference), len(hypothesis)
    while i or j:
        operation = back[i][j]
        if operation in ("match", "substitute"):
            pairs.append((reference[i - 1], hypothesis[j - 1]))
            i, j = i - 1, j - 1
        elif operation == "delete":
            pairs.append((reference[i - 1], None))
            i -= 1
        else:
            pairs.append((None, hypothesis[j - 1]))
            j -= 1
    pairs.reverse()
    return Alignment(costs[-1][-1], tuple(pairs))


def _edit_counts(pairs: Iterable[tuple[Optional[str], Optional[str]]]) -> dict[str, int]:
    result = Counter()
    for reference, hypothesis in pairs:
        if reference is None:
            result["insertions"] += 1
        elif hypothesis is None:
            result["deletions"] += 1
        elif reference != hypothesis:
            result["substitutions"] += 1
        else:
            result["matches"] += 1
    return {name: result[name] for name in ("matches", "substitutions", "insertions", "deletions")}


def _classification_scores(
    pairs: Iterable[tuple[Optional[str], Optional[str]]],
) -> tuple[dict[str, Optional[float]], dict[str, Counter]]:
    true_positive, false_positive, false_negative = Counter(), Counter(), Counter()
    support = Counter()
    for reference, hypothesis in pairs:
        if reference is not None:
            support[reference] += 1
        if reference == hypothesis and reference is not None:
            true_positive[reference] += 1
        elif reference is None:
            if hypothesis is not None:
                false_positive[hypothesis] += 1
        elif hypothesis is None:
            false_negative[reference] += 1
        else:
            false_positive[hypothesis] += 1
            false_negative[reference] += 1

    labels = sorted(set(support) | set(true_positive) | set(false_positive) | set(false_negative))
    per_class: dict[str, tuple[float, float, float]] = {}
    for label in labels:
        tp = true_positive[label]
        precision = tp / (tp + false_positive[label]) if tp + false_positive[label] else 0.0
        recall = tp / (tp + false_negative[label]) if tp + false_negative[label] else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class[label] = precision, recall, f1
    tp_total = sum(true_positive.values())
    fp_total = sum(false_positive.values())
    fn_total = sum(false_negative.values())
    micro_precision = tp_total / (tp_total + fp_total) if tp_total + fp_total else None
    micro_recall = tp_total / (tp_total + fn_total) if tp_total + fn_total else None
    micro_f1 = (2 * tp_total / (2 * tp_total + fp_total + fn_total)
                if 2 * tp_total + fp_total + fn_total else None)
    support_total = sum(support.values())
    scores: dict[str, Optional[float]] = {
        "micro_precision": micro_precision,
        "micro_recall": micro_recall,
        "micro_f1": micro_f1,
        "macro_f1": (sum(score[2] for score in per_class.values()) / len(per_class)
                     if per_class else None),
        "weighted_f1": (sum(per_class[label][2] * support[label] for label in per_class) / support_total
                        if support_total else None),
    }
    return scores, {
        "tp": true_positive, "fp": false_positive, "fn": false_negative,
        "support": support, "per_class_f1": Counter({key: value[2] for key, value in per_class.items()}),
    }


def _scores_for_units(references: Sequence[str], hypotheses: Sequence[str], tokenizer) -> dict:
    pairs: list[tuple[Optional[str], Optional[str]]] = []
    edit_count = 0
    reference_units = 0
    exact = 0
    for reference, hypothesis in zip(references, hypotheses):
        ref_units, hyp_units = tokenizer(reference), tokenizer(hypothesis)
        alignment = align_sequences(ref_units, hyp_units)
        pairs.extend(alignment.pairs)
        edit_count += alignment.edits
        reference_units += len(ref_units)
        exact += reference == hypothesis
    scores, classes = _classification_scores(pairs)
    counts = _edit_counts(pairs)
    denominator = reference_units
    return {
        "error_rate": edit_count / denominator if denominator else (0.0 if not edit_count else None),
        "alignment_accuracy": max(0, denominator - edit_count) / denominator if denominator else None,
        "edit_count": edit_count,
        "reference_units": reference_units,
        "exact_match_accuracy": exact / len(references) if references else None,
        "precision": scores["micro_precision"],
        "recall": scores["micro_recall"],
        "micro_f1": scores["micro_f1"],
        "macro_f1": scores["macro_f1"],
        "weighted_f1": scores["weighted_f1"],
        **counts,
        "class_counts": classes,
    }


def evaluate_sequences(references: Sequence[str], hypotheses: Sequence[str]) -> dict:
    """Compute CER/WER, exact line rate, sequence-F1 and edit operations."""
    if len(references) != len(hypotheses):
        raise ValueError("References and hypotheses must have equal lengths")
    chars = _scores_for_units(references, hypotheses, list)
    words = _scores_for_units(references, hypotheses, str.split)
    return {
        "cer": chars["error_rate"],
        "wer": words["error_rate"],
        "exact_line_match_accuracy": chars["exact_match_accuracy"],
        "character_alignment_accuracy": chars["alignment_accuracy"],
        "word_alignment_accuracy": words["alignment_accuracy"],
        "character_micro_precision": chars["precision"],
        "character_micro_recall": chars["recall"],
        "character_micro_f1": chars["micro_f1"],
        "character_macro_f1": chars["macro_f1"],
        "character_weighted_f1": chars["weighted_f1"],
        "word_micro_precision": words["precision"],
        "word_micro_recall": words["recall"],
        "word_micro_f1": words["micro_f1"],
        "character_substitutions": chars["substitutions"],
        "character_insertions": chars["insertions"],
        "character_deletions": chars["deletions"],
        "word_substitutions": words["substitutions"],
        "word_insertions": words["insertions"],
        "word_deletions": words["deletions"],
        "_character_classes": chars["class_counts"],
    }


def character_confusion(references: Sequence[str], hypotheses: Sequence[str]) -> Counter:
    """Count aligned character pairs, plus explicit insertion/deletion cells."""
    matrix: Counter = Counter()
    for reference, hypothesis in zip(references, hypotheses):
        for expected, predicted in align_sequences(list(reference), list(hypothesis)).pairs:
            if expected is None:
                matrix[("<INSERTION>", predicted)] += 1
            elif predicted is None:
                matrix[(expected, "<DELETION>")] += 1
            else:
                matrix[(expected, predicted)] += 1
    return matrix


def top_substitutions(references: Sequence[str], hypotheses: Sequence[str], limit: int = 20) -> list[dict]:
    substitutions: Counter = Counter()
    for reference, hypothesis in zip(references, hypotheses):
        for expected, predicted in align_sequences(list(reference), list(hypothesis)).pairs:
            if expected is not None and predicted is not None and expected != predicted:
                substitutions[(expected, predicted)] += 1
    return [
        {"ground_truth": expected, "prediction": predicted, "count": count}
        for (expected, predicted), count in substitutions.most_common(limit)
    ]
