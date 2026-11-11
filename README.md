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
4. **Handwriting to Text (HTR):**
   - Freehand strokes can be selected and converted into editable digital text via the calibrated online stroke HTR engine (`POST /api/board/htr`).
   - If handwritten text includes an `@board` instruction, the system can execute it directly on the canvas!
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

### 3. Launch Application
Run the startup script:

```bash
./run_prototype.sh
```

Or run via the virtual environment directly:
```bash
./venv/bin/python backend/app.py
```

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
│   │   ├── htr_calibration.py      # Calibrated online handwriting recognition engine
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
├── run_prototype.sh                # Application launch script
├── .env.example                    # Environment configuration template
└── README.md                       # Documentation
```
