# Enchanted Ink — The AI Diary That Writes Back

An interactive digital diary inspired by Tom Riddle's diary from *Harry Potter and the Chamber of Secrets*. The user writes freehand with a stylus, touchscreen, or mouse; the diary absorbs the ink, calibrates recognition confidence, retrieves long-term episodic memories across sessions, and writes back in a living, animated cursive hand.

---

## Deliverables in this Directory

1. **Research Plan & Specification:**
   - [`ENCHANTED_INK_RESEARCH_PLAN.md`](./ENCHANTED_INK_RESEARCH_PLAN.md) — 20-section comprehensive research and technical plan grounded in 30 verified academic papers across 6 domains.
2. **IEEE Research Papers Excel Spreadsheet:**
   - [`Enchanted_Ink_Research_Papers_IEEE.xlsx`](./Enchanted_Ink_Research_Papers_IEEE.xlsx) — Professional multi-sheet workbook containing all 30 research papers formatted in official IEEE citation standard, plus an architectural evidence matrix and IEEE style guidelines.
3. **Working Prototype:**
   - Complete local-first prototype running on FastAPI, HTML5 Canvas, Web Audio API, and SQLite.

---

## Quickstart: Running the Prototype

To launch the prototype application:

```bash
cd /home/silversoul/Documents/projects/Enchanted_Ink
./run_prototype.sh
```

Or manually using the virtual environment:

```bash
./venv/bin/python backend/app.py
```

Open your browser and navigate to:
👉 **[http://localhost:8000](http://localhost:8000)**

---

## Interactive Features in the Prototype

- **Skeuomorphic Antique Parchment:** Double-page leather-bound book layout with edge aging and flickering candlelight overlay.
- **Natural Inking Canvas:** Freehand stylus/mouse drawing with Bézier curve smoothing and pressure sensitivity.
- **Living Ink Absorption:** Ink dynamically absorbs and fades into the parchment as you rest your quill.
- **Calibrated Uncertainty & Diegetic Clarification:** Evaluates handwriting confidence; if ambiguous or messy ($c_{\text{cal}} < 0.65$), the diary politely asks for clarification in character.
- **Animated Cursive Responses:** The diary writes back character-by-character and stroke-by-stroke in real time, accompanied by procedural quill scratch audio generated via the Web Audio API.
- **Episodic Memory & Ebbinghaus Forgetting:** Remembers autobiographical facts across pages and sessions, decaying older memories according to the cognitive forgetting curve.
- **Memory Sanctum (Privacy Control):** Click **✦ Memory Sanctum** in the top bar to inspect all stored propositions, view retention salience badges, delete individual memories, or purge the diary completely.
- **Configurable Personas:** Switch between *Tom Riddle*, *The Hermetic Alchemist*, and *The Gentle Confidant*.
