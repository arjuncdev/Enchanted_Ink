# Enchanted Ink — AI-Powered Infinite Whiteboard

**Enchanted Ink** is a modern, high-productivity AI whiteboard where users write, draw, think, and interact with artificial intelligence directly on an infinite canvas.

Instead of a conventional chatbot trapped in a sidebar, **the whiteboard is the product**. When you type or write an instruction containing `@board`, the AI interprets your request and canvas context, generating editable native whiteboard objects—block diagrams, interactive flowcharts, circuit schematics, mind maps, formula cards, and structured sticky notes—placed directly onto your board.

---

## Key Features

1. **Infinite Spatial Canvas (Fabric.js 5.3):**
   - Smooth viewport pan & zoom (15% to 400%) with mouse wheel, gestures, or Hand tool (`H` / Spacebar drag).
   - Dynamic dot-grid background synchronized with viewport transforms.
   - High-DPI crisp rendering on retina and 4K displays.
2. **Comprehensive Drawing & Visual Tools:**
   - **Select & Move (`V`):** Multi-object marquee selection, bounding boxes, 8 scale handles, rotation, and contextual styling toolbar.
   - **Pen / Freehand (`P`):** Smooth vector stroke drawing with pressure sensitivity and multi-color palette.
   - **Eraser (`E`):** Direct click or drag object removal.
   - **Text (`T`):** Inline editable typography with auto-wrapping.
   - **Sticky Notes (`S`):** Soft pastel cards with titles and formatted note text.
   - **Shapes (`R`, `O`):** Rounded rectangles and ellipses with clean borders and subtle drop shadows.
   - **Connectors & Arrows (`A`):** Directional lines with arrowheads and optional connector labels.
3. **The `@board` Native AI Engine:**
   - Floating command bar (`Ctrl+K` or bottom center) accepting natural language instructions.
   - **Context-Aware:** Analyzes existing notes, selected objects, and spatial viewport bounds.
   - **Native Object Synthesis:** Generates individual editable nodes, cards, and connectors—never a flat image or non-interactive bubble.
   - **Deterministic Spatial Layout:** Non-overlapping layouts for block diagrams, flowcharts, and mind maps.
   - **Undo AI Insert:** One-click removal of an entire AI insertion batch without disturbing earlier work.
4. **Uncertainty-Aware Handwriting (TrOCR):**
   - Diary canvas images are read by the configured local TrOCR checkpoint (`POST /api/v1/process-turn`).
   - Decoder token log-probabilities form a length-normalized sequence score; validation-fitted temperature and threshold determine whether to ask for confirmation.
   - If the checkpoint or calibration is missing, the diary reports that state and asks for confirmation; no handwriting phrase or confidence is fabricated.
5. **Persistence & Export:**
   - Autosaves state to local storage and backend SQLite (`data/enchanted_diary.db`).
   - Multiple board management (create, switch, delete boards).
   - High-resolution **Export to PNG** and **Export to JSON**.
   - **Import JSON** to restore editable canvas boards.

---

## Quickstart & Setup

### 1. Requirements
- Python 3.10+
- Modern Web Browser (Chrome, Firefox, Safari, Edge)

### 2. Configure Environment
Copy the example environment file and configure your Gemini API Key:

```bash
cp .env.example .env
```

Edit `.env` and provide your Google Gemini API key:
```ini
GEMINI_API_KEY=your_gemini_api_key_here
```
*(Alternatively, configure the API key directly in the web UI via the **AI Ready** settings modal).*

Diary and board Gemini models are configurable as `GEMINI_DIARY_MODEL` and `GEMINI_BOARD_MODEL`. The default is `gemini-3.8-flash`; select a model available to your API project if access differs. Structured output uses the current `responseMimeType` JSON field. For TrOCR, see [Training and deployment](#training-and-deployment). At startup, the service tries the configured Enchanted Ink checkpoint first, then the optional upstream handwritten baseline. The UI and status endpoint identify which model actually loaded.

### 3. Launch Application
Run the startup script:

```bash
./run_prototype.sh
```

Or run via the virtual environment directly:
```bash
./venv/bin/python backend/app.py
```

For an existing virtual environment, install dependencies with `./venv/bin/pip install -r requirements.txt`.

Open your browser and navigate to:
👉 **[http://localhost:8000](http://localhost:8000)**

---

## Example `@board` Interactions

Try typing these in the `@board` command bar:

- `@board Explain how a DC-DC buck converter works`
  *Generates a complete circuit block diagram (Input $\to$ Switch $\to$ Inductor $\to$ Capacitor $\to$ Load), key equations ($V_{out} \approx D \times V_{in}$), and operational phase sticky notes.*
- `@board create a flowchart for user login`
  *Generates sequential start/end ellipses, credential validation steps, decision branches, error retries, and connecting arrows.*
- `@board summarize these notes`
  *Extracts key takeaways from notes on your canvas and organizes them into categorized sticky notes.*
- `@board create a mind map for deep learning architectures`
  *Creates a central topic node with radiating branches for CNNs, Transformers, and RNNs.*
- `@board compare TrOCR vs CRNN`
  *Draws a structured comparison matrix with architecture, CER benchmarks, and trade-offs.*

---

## Keyboard Shortcuts

| Shortcut | Action |
|:---|:---|
| `V` | Select & Move Tool |
| `H` / `Space + Drag` | Pan / Hand Tool |
| `P` | Freehand Pen Drawing |
| `E` | Eraser Tool |
| `T` | Text Object |
| `S` | Sticky Note |
| `R` | Rectangle Shape |
| `O` | Ellipse Shape |
| `A` | Connector Arrow |
| `Ctrl + K` | Focus `@board` AI Command Bar |
| `Ctrl + Z` | Undo |
| `Ctrl + Y` / `Ctrl + Shift + Z` | Redo |
| `Ctrl + D` | Duplicate Selected Objects |
| `Del` / `Backspace` | Delete Selected Objects |
| Mouse Wheel | Zoom in / Zoom out toward cursor |

---

## Architecture

```
Enchanted_Ink/
├── backend/
│   ├── app.py                      # FastAPI application & REST endpoints
│   ├── models/
│   │   ├── board_ai_service.py     # Provider abstraction & Gemini structured JSON generation
│   │   ├── board_storage.py        # SQLite persistent storage for named boards
│   │   ├── trocr_htr.py            # Local TrOCR inference and calibrated sequence confidence
│   │   ├── memory_engine.py        # Episodic memory engine
│   │   └── persona_engine.py       # Conversational persona engine
│   └── data/
│       └── enchanted_diary.db      # SQLite relational database
├── static/
│   ├── index.html                  # Modern whiteboard application UI
│   ├── css/
│   │   └── whiteboard.css          # Modern productivity design system & layout
│   ├── js/
│   │   └── whiteboard.js           # Fabric.js canvas controller, spatial engine & AI connector
│   └── vendor/
│       └── fabric.min.js           # Fabric.js 5.3 canvas library
├── training/trocr_iam.py           # IAM writer-split training/evaluation workflow
├── run_prototype.sh                # Application launch script
├── .env.example                    # Environment configuration template
└── README.md                       # Documentation
```

## Training and deployment

The current repository provides the TrOCR inference and calibration integration, but does not include trained weights or claim measured accuracy. The IAM dataset requires registration and manual download. Do not commit downloaded data, model weights, or calibration files.

In Google Colab, install a CUDA-compatible PyTorch build and the training packages (`pip install -r requirements-htr.txt`), then:

```bash
python training/trocr_iam.py prepare --iam-root /content/iam --manifest /content/iam-lines.csv
python training/trocr_iam.py train --manifest /content/iam-lines.csv --output /content/trocr-output --base-model microsoft/trocr-small-stage1
```

The manifest contains image path, transcript, and writer ID. The preparation command reads IAM `lines.txt`; verify the resulting manifest and image paths against the registered archive before training. The default is TrOCR `small-stage1` (pretrained only); it avoids starting from Microsoft's `small-handwritten` checkpoint, which is already fine-tuned on IAM and would contaminate a writer-held-out evaluation. Splitting is writer-disjoint (80/10/10); the script reports the number of writers and lines in each split, evaluates the pretrained baseline, fine-tunes with AdamW, gradient accumulation, mixed precision when CUDA is available, checkpoint resume and validation CER early stopping. It fits sequence-score temperature on validation data, evaluates CER/WER/ECE and risk/coverage on the untouched test split, and writes reliability and risk-coverage plots plus `calibration.json`.

Copy the saved model directory and `calibration.json` to a local path outside Git, then set:

```ini
TROCR_CHECKPOINT=/absolute/path/to/trocr-output
TROCR_CALIBRATION=/absolute/path/to/trocr-output/calibration.json
HTR_ACCEPTANCE_THRESHOLD=0.72
```

Install CPU PyTorch and `requirements-htr.txt` in the same environment used to run the app:

```bash
./venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu
./venv/bin/pip install -r requirements-htr.txt
```

At startup the service loads the configured local checkpoint first. If it is absent or fails to load and `TROCR_ALLOW_BASELINE_FALLBACK=true`, it downloads/caches `TROCR_BASELINE_MODEL` from Hugging Face (default `microsoft/trocr-small-handwritten`). This is a pretrained upstream model fine-tuned on IAM, not an Enchanted Ink fine-tuned checkpoint; the UI labels it `PRETRAINED BASELINE — NOT ENCHANTED INK FINE-TUNED`. Set `TROCR_ALLOW_BASELINE_FALLBACK=false` to disable network fallback. HTR status reports loaded model, source, calibration, and load error; retry explicitly from the handwriting panel after correcting setup. The line-oriented model may need better segmentation for full-page diary writing. Baseline confidence is uncalibrated, so every transcription requires confirmation and is not research evaluation.

### Implemented status

- Implemented: local checkpoint loading, shared processor preprocessing, token log-probability sequence scoring, explicit empty/error states, validation calibration file loading, confidence threshold clarification, automatic debounced pen-stroke collection and crop rasterization, constrained `@board` trigger extraction, editable confirmation/retry UI, typed/handwritten command routing, visible Gemini/fallback status, and safeguards against dissolving unrelated selected objects.
- Implemented but not yet trained/evaluated: the IAM training, writer split, calibration and evaluation pipeline. No model metrics are available until the registered IAM data is processed and the Colab run completes.
- The Enchanted Ink fine-tuned TrOCR checkpoint/calibration is not included in this checkout. When HTR dependencies and network access are available, the upstream IAM handwritten baseline can recognize pen ink, but is clearly labeled and always requires correction/confirmation because its confidence is uncalibrated. The UI preserves strokes and offers manual transcription if no model loads. The recognizer receives a crop of recent nearby strokes as one image, so multi-line commands may need user confirmation. Offline diary replies are local templates and rule-based `@board` content is limited and labeled as fallback.

## API behavior

- `GET /api/v1/htr/status`: checkpoint/calibration availability and acceptance threshold.
- `POST /api/v1/process-turn`: TrOCR transcription, clarification gate, memory retrieval, persona reply and persistence. Low confidence never reaches memory or response generation until the user confirms/corrects.
- `POST /api/board/htr`: TrOCR raster transcription for a crop built from recent pen strokes or selected canvas handwriting; response includes request ID, confidence/calibration status, and extracted command fields. No external handwriting API is used.
- `POST /api/board/command`: provider-labelled editable canvas objects. Invalid structured output returns an HTTP error without inserting partial objects; offline rule responses include provider/model/fallback status and a warning.

Automatic whiteboard recognition waits for `HTR_INACTIVITY_MS` (default 2200 ms) after the latest nearby pen stroke. It groups nearby strokes into one bounded crop, which also supports a command written across close lines. The canvas shows recognition, clarification, provider and completion states. On successful generation, only the strokes in that recognized command group are removed; Undo AI Insert restores those strokes and removes only that generated batch.

### Try handwritten `@board` locally

Open `http://localhost:8000`, choose the pen, and write `@board create a flowchart for user login` on the canvas. Pause for the configured inactivity interval. A calibrated Enchanted Ink checkpoint can run high-confidence commands immediately; the upstream baseline always asks you to confirm or correct the recognized instruction before execution. If no model loads, the panel reports the cause, preserves the ink, and offers retry or manual transcription. If Gemini is unavailable, the rule-based response is visibly identified as fallback.
