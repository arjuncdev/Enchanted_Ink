# Enchanted Ink

Enchanted Ink is an AI-integrated smart whiteboard. People can write, draw, place notes and shapes, or ask `@board` to create editable diagrams and content on an infinite canvas.

## How it works

1. The browser captures typed input or pen strokes on a Fabric.js canvas.
2. Google Gemini Vision externally transcribes handwritten text from a raster crop. The original ink remains available if recognition needs correction.
3. The command parser routes only instructions beginning with `@board` to the board assistant.
4. Gemini or a configured local Ollama model returns structured board objects. The API validates the objects before insertion.
5. Users can edit generated objects, undo an AI insertion batch, autosave boards, and export or import JSON and PNG.

Whiteboard handwriting recognition uses Google Gemini Vision and sends the selected handwriting crop to Google's external service. Gemini may separately generate the structured smart-board response; the recognition result is labeled as Gemini and has no confidence score.

## Run the application

```bash
./run_prototype.sh
```

The launcher creates `venv/` and installs `requirements.txt` on a fresh checkout, then starts FastAPI at `http://localhost:8000`.

Copy `.env.example` to `.env` and set `GEMINI_API_KEY`; it is required for the default external handwriting recognition and Gemini board generation. Ollama can be used locally for board response generation, but handwriting images still go to Gemini.

## Optional local TrOCR model

The fine-tuned checkpoint is available from Hugging Face for optional local inference and research:

```bash
./venv/bin/pip install -r requirements-htr.txt
./venv/bin/hf download seaandsun/enchanted-ink-trocr \
  --repo-type model \
  --include "stylus-finetuned/*" \
  --local-dir stylus-model
```

The `.env.example` setting points to `./stylus-model/stylus-finetuned`. This local checkpoint is not used by the whiteboard handwriting endpoint, which defaults to the external Google handwriting-recognition service.

## Training and evaluation

`training/trocr_iam.py` contains the data preparation, fine-tuning, and evaluation commands. The project’s held-out manifest has 336 line images (268 train, 33 validation, 35 test). It has no writer identifiers, so these results use a line-level split and may share handwriting style across subsets.

To reproduce test metrics from the installed checkpoint and local manifest:

```bash
TROCR_CHECKPOINT=./stylus-model/stylus-finetuned \
TROCR_ALLOW_BASELINE_FALLBACK=false \
./evaluation/.venv/bin/python evaluation/benchmark_htr.py run \
  --manifest evaluation/datasets/kaggle-english-lines-split.csv \
  --models trocr \
  --output "reports/Tr OCR"
```

The output includes aggregate CER/WER and aligned character metrics, an error analysis, confusion counts, PNG graphs, and an HTML dashboard. Treat results as a small-data project evaluation rather than a general handwriting benchmark. Image-level predictions and sample error files may contain dataset content; do not publish those files unless the dataset license and sharing permissions allow it.

## Project structure

- `backend/app.py`: API routes for board commands, Gemini handwriting recognition, and board persistence.
- `backend/models/trocr_htr.py`: local TrOCR checkpoint loading and inference.
- `backend/models/board_ai_service.py`: structured board generation and response validation.
- `backend/models/board_storage.py`: SQLite board persistence.
- `static/`: whiteboard interface, styles, and Fabric.js.
- `training/trocr_iam.py`: model training workflow.
- `evaluation/`: recognition metrics, benchmark runner, and report generation.
- `reports/Tr OCR/`: generated model evaluation artifacts.
- `submission/`: IEEE-style project report and Overleaf source package.

## Main dependencies

- Python 3.10 or newer
- FastAPI and Uvicorn
- For local TrOCR inference/training: PyTorch, Transformers, and image-processing dependencies from `requirements-htr.txt`
- A Gemini API key or local Ollama installation for AI board generation
