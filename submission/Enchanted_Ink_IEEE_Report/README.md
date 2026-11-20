# Enchanted Ink — IEEE Conference Submission Report

This folder contains the current two-column report and editable IEEE conference LaTeX source.

- `Submission_Report.pdf`: print and submission copy.
- `main.tex` and `references.bib`: editable manuscript source for Overleaf.
- `IEEEtran.cls` and `IEEEtran.bst`: IEEE conference class and bibliography style.
- `figures/`: measured TrOCR evaluation figures.
- `supporting_data/`: aggregate metrics, sanitized run summary, and checkpoint training arguments.

The evaluation reports the fine-tuned Hugging Face TrOCR checkpoint on 35 held-out line images. It does not contain source images, raw per-line predictions, or the dataset manifest. Writer IDs were unavailable; the report identifies this as a line-level, non-writer-disjoint evaluation.
