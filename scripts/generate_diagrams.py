import matplotlib.pyplot as plt
import matplotlib.patches as patches
import numpy as np

BG_COLOR = '#140a05'
PANEL_COLOR = '#1c0f08'
GOLD_COLOR = '#d4af37'
GOLD_LIGHT = '#fceecf'
GOLD_BORDER = '#8c6d32'
EMERALD_COLOR = '#2ec4b6'
CORAL_COLOR = '#e76f51'
BLUE_COLOR = '#457b9d'
PURPLE_COLOR = '#7209b7'
TEXT_LIGHT = '#f7ecd5'
TEXT_MUTED = '#a48259'

plt.rcParams['font.sans-serif'] = 'DejaVu Sans'

# -------------------------------------------------------------------------
# 1. System Architecture Diagram (Slide 4)
# -------------------------------------------------------------------------
def generate_architecture_diagram():
    fig, ax = plt.subplots(figsize=(12, 6.8), facecolor=BG_COLOR)
    ax.set_facecolor(BG_COLOR)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis('off')

    # Title Banner
    ax.text(50, 96, "ENCHANTED INK — MULTIMODAL SYSTEM ARCHITECTURE", 
            ha='center', va='center', fontsize=14, fontweight='bold', color='#ffd166')
    ax.text(50, 92.5, "5-Tier Decoupled Pipeline: Stylus Input → Calibrated Inference → Cognitive Memory → Skeuomorphic Output",
            ha='center', va='center', fontsize=9, fontstyle='italic', color=TEXT_MUTED)

    # Tier Definitions: [x, y, w, h, title, fill, border]
    tiers = [
        (4, 50, 16.5, 38, "TIER 1: INTERACTION CANVAS", "#26140b", GOLD_BORDER),
        (23.5, 50, 16.5, 38, "TIER 2: PREPROCESSING", "#1e140d", '#e76f51'),
        (43, 50, 18, 38, "TIER 3: HTR & UNCERTAINTY", "#1a190f", EMERALD_COLOR),
        (64, 50, 18, 38, "TIER 4: COGNITIVE DIALOGUE", "#171520", '#457b9d'),
        (85, 50, 12, 38, "TIER 5: PERSISTENCE", "#1a0d0a", '#b5838d')
    ]

    for tx, ty, tw, th, title, bg, border in tiers:
        # Tier Outer Box
        box = patches.FancyBboxPatch((tx, ty), tw, th, boxstyle="round,pad=0.8,rounding_size=1.5",
                                     facecolor=bg, edgecolor=border, linewidth=1.5)
        ax.add_patch(box)
        ax.text(tx + tw/2, ty + th - 2.8, title, ha='center', va='center',
                fontsize=7.8, fontweight='bold', color='#fff3b0')

    # Tier 1 Components
    t1_boxes = [
        (5.5, 76, 13.5, 7, "Pointer Events Canvas\nTouch / Stylus Pressure (ρ)", '#381c10'),
        (5.5, 66, 13.5, 7, "Dual HTML5 Canvases\n#inkCanvas & #calligraphy", '#381c10'),
        (5.5, 54, 13.5, 8.5, "Web Audio Procedural\nQuill Scratch Synthesis", '#381c10')
    ]
    # Tier 2 Components
    t2_boxes = [
        (25, 76, 13.5, 7, "Vector Trajectory Sampling\ns_i = [x, y, t, ρ]", '#331e13'),
        (25, 66, 13.5, 7, "Cubic Bézier Spline\nDenoising & Smoothing", '#331e13'),
        (25, 54, 13.5, 8.5, "Bounding-Box Rescaling\n& Aspect Normalization", '#331e13')
    ]
    # Tier 3 Components
    t3_boxes = [
        (44.5, 76, 15, 7, "Online BiLSTM-CTC\nOffline TrOCR ViT", '#22281a'),
        (44.5, 66, 15, 7, "Temperature Scaling\nT = 1.45 Calibration", '#22281a'),
        (44.5, 54, 15, 8.5, "Diegetic Uncertainty Gate\nc_cal ≥ τ=0.82 Clarification", '#22281a')
    ]
    # Tier 4 Components
    t4_boxes = [
        (65.5, 76, 15, 7, "Ebbinghaus Memory Recall\nS = Semantic + Decay + Sal.", '#1d2230'),
        (65.5, 66, 15, 7, "Dual Persona Engine\nTom Riddle vs. Regular Q&A", '#1d2230'),
        (65.5, 54, 15, 8.5, "Google Gemini LLM Core\nContext & Safety Guard", '#1d2230')
    ]
    # Tier 5 Components
    t5_boxes = [
        (86.2, 74, 9.6, 10, "SQLite DB\nMemories & Turns", '#2c1514'),
        (86.2, 56, 9.6, 12, "Privacy Engine\nEbbinghaus Forgetting\n& Reset Purge", '#2c1514')
    ]

    all_components = t1_boxes + t2_boxes + t3_boxes + t4_boxes + t5_boxes
    for cx, cy, cw, ch, label, cbg in all_components:
        cbox = patches.FancyBboxPatch((cx, cy), cw, ch, boxstyle="round,pad=0.3,rounding_size=1",
                                      facecolor=cbg, edgecolor=GOLD_BORDER, linewidth=0.8)
        ax.add_patch(cbox)
        ax.text(cx + cw/2, cy + ch/2, label, ha='center', va='center',
                fontsize=7.2, color=TEXT_LIGHT, multialignment='center')

    # Horizontal Flow Arrows between Tiers
    arrow_y = 69.5
    arrows = [(20.5, 23.5), (40, 43), (61, 64), (82, 85)]
    for x1, x2 in arrows:
        ax.annotate('', xy=(x2, arrow_y), xytext=(x1, arrow_y),
                    arrowprops=dict(facecolor=GOLD_COLOR, edgecolor='#fff2a8', arrowstyle="->", lw=2, mutation_scale=14))

    # Bottom Feedback / Output Banner
    fb_box = patches.FancyBboxPatch((4, 10), 93, 34, boxstyle="round,pad=0.8,rounding_size=1.5",
                                    facecolor='#180e08', edgecolor=GOLD_COLOR, linewidth=1.2)
    ax.add_patch(fb_box)
    ax.text(50, 40, "OUTPUT SYNTHESIS & SKEUOMORPHIC EMBODIMENT (FEEDBACK TO USER)", 
            ha='center', va='center', fontsize=9.5, fontweight='bold', color='#ffd166')

    fb_sub_boxes = [
        (8, 15, 26, 20, "1. INK ABSORPTION ENGINE\nUser's handwriting dissolves smoothly\nover 20 frames (600ms) into parchment,\ncreating magical disappearance sensation.", '#26140b', '#e76f51'),
        (37, 15, 26, 20, "2. PROCEDURAL CALLIGRAPHY\nCharacter-by-character Bézier cursive animation;\nadaptive font scaling (23px → 12px) to prevent\nclipping; fluid quill stroke timing (18-28ms).", '#26140b', EMERALD_COLOR),
        (66, 15, 26, 20, "3. BIPARTITE CHRONICLE LOGGING\nImmediate timestamped inscription on Left Page\nChronicle; simultaneous visual handwriting\nappearance on Right Page in real time.", '#26140b', BLUE_COLOR)
    ]

    for fx, fy, fw, fh, flabel, fbg, fborder in fb_sub_boxes:
        fbox = patches.FancyBboxPatch((fx, fy), fw, fh, boxstyle="round,pad=0.5,rounding_size=1",
                                      facecolor=fbg, edgecolor=fborder, linewidth=1)
        ax.add_patch(fbox)
        ax.text(fx + fw/2, fy + fh/2, flabel, ha='center', va='center',
                fontsize=7.5, color=TEXT_LIGHT, multialignment='center')

    # Flow from Tier 4 down to Output
    ax.annotate('', xy=(50, 44), xytext=(73, 50),
                arrowprops=dict(facecolor=EMERALD_COLOR, edgecolor=EMERALD_COLOR, arrowstyle="->", lw=2, mutation_scale=14))

    plt.tight_layout()
    plt.savefig('presentation_assets/diagram_system_architecture.png', dpi=300, facecolor=BG_COLOR)
    plt.close()
    print("Created presentation_assets/diagram_system_architecture.png")

# -------------------------------------------------------------------------
# 2. Complete Interaction Flowchart (Slide 5)
# -------------------------------------------------------------------------
def generate_flowchart_diagram():
    fig, ax = plt.subplots(figsize=(12, 6.8), facecolor=BG_COLOR)
    ax.set_facecolor(BG_COLOR)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis('off')

    # Title Banner
    ax.text(50, 96, "ENCHANTED INK — END-TO-END INTERACTION FLOWCHART", 
            ha='center', va='center', fontsize=14, fontweight='bold', color='#ffd166')
    ax.text(50, 92.5, "Closed-Loop Decision Logic with Diegetic Uncertainty Gating & Multi-Turn Persistence",
            ha='center', va='center', fontsize=9, fontstyle='italic', color=TEXT_MUTED)

    # Main Horizontal / Vertical Flow Nodes
    # Row 1: Input to HTR (y = 78)
    r1_nodes = [
        (4, 73, 14, 10, "1. USER WRITES\nPen strokes on\nparchment canvas", '#2d180d'),
        (22, 73, 14, 10, "2. PEN UP EVENT\n1.2s Rest Timer or\nSubmit Ink Pressed", '#2d180d'),
        (40, 73, 14, 10, "3. STROKE HARVEST\nExport Base64 & Bézier\ns_i = [x, y, t, ρ]", '#2d180d'),
        (58, 73, 14, 10, "4. VANISH INK\nUser ink dissolves\ninto paper (600ms)", '#3d1c10'),
        (76, 73, 18, 10, "5. SEQUENCE HTR\nBiLSTM / TrOCR yields\nunnormalized logits z", '#1f291a')
    ]

    for nx, ny, nw, nh, nlabel, nbg in r1_nodes:
        box = patches.FancyBboxPatch((nx, ny), nw, nh, boxstyle="round,pad=0.3,rounding_size=1",
                                     facecolor=nbg, edgecolor=GOLD_COLOR, linewidth=1.2)
        ax.add_patch(box)
        ax.text(nx + nw/2, ny + nh/2, nlabel, ha='center', va='center', fontsize=7.5, color=TEXT_LIGHT, multialignment='center')

    # Arrows Row 1
    ax.annotate('', xy=(22, 78), xytext=(18, 78), arrowprops=dict(facecolor=GOLD_COLOR, arrowstyle="->", lw=1.5))
    ax.annotate('', xy=(40, 78), xytext=(36, 78), arrowprops=dict(facecolor=GOLD_COLOR, arrowstyle="->", lw=1.5))
    ax.annotate('', xy=(58, 78), xytext=(54, 78), arrowprops=dict(facecolor=GOLD_COLOR, arrowstyle="->", lw=1.5))
    ax.annotate('', xy=(76, 78), xytext=(72, 78), arrowprops=dict(facecolor=GOLD_COLOR, arrowstyle="->", lw=1.5))

    # Flow down to Decision Diamond (y = 52)
    # Arrow from Node 5 down to Decision
    ax.annotate('', xy=(85, 62), xytext=(85, 73), arrowprops=dict(facecolor=GOLD_COLOR, arrowstyle="->", lw=1.5))

    # Diamond 1: Confidence Gating at (85, 52)
    diamond_poly = patches.Polygon([[85, 62], [96, 52], [85, 42], [74, 52]], closed=True,
                                   facecolor='#3a2608', edgecolor='#ffd166', linewidth=1.5)
    ax.add_patch(diamond_poly)
    ax.text(85, 52, "Calibrated\nConfidence\nc_cal ≥ τ (0.82)?", ha='center', va='center', fontsize=7.2, fontweight='bold', color='#fff3b0')

    # Branch NO: Leftwards to Diegetic Clarification
    ax.text(70, 53.5, "NO (Ambiguous)", ha='right', va='bottom', fontsize=7.5, fontweight='bold', color='#e76f51')
    ax.annotate('', xy=(48, 52), xytext=(74, 52), arrowprops=dict(facecolor='#e76f51', edgecolor='#e76f51', arrowstyle="->", lw=1.8))

    # Clarification Box
    clarify_box = patches.FancyBboxPatch((20, 46), 28, 12, boxstyle="round,pad=0.4,rounding_size=1",
                                         facecolor='#33120f', edgecolor='#e76f51', linewidth=1.4)
    ax.add_patch(clarify_box)
    ax.text(34, 52, "DIEGETIC CLARIFICATION GATE\nDisplay Banner: 'Thy ink was faint and troubled...'\nUser writes revision or confirms text hint", 
            ha='center', va='center', fontsize=7.5, color='#ffddd2', multialignment='center')

    # Loop back from Clarification to Node 5
    ax.annotate('', xy=(20, 52), xytext=(12, 52), arrowprops=dict(facecolor='#e76f51', arrowstyle="-", lw=1.5))
    ax.plot([12, 12], [52, 78], color='#e76f51', lw=1.5)
    ax.annotate('', xy=(12, 78), xytext=(4, 78), arrowprops=dict(facecolor='#e76f51', edgecolor='#e76f51', arrowstyle="<-", lw=1.5))

    # Branch YES: Downwards to Cognitive Engine (x = 85, y = 30)
    ax.text(86.5, 37, "YES (Confident)", ha='left', va='center', fontsize=7.5, fontweight='bold', color=EMERALD_COLOR)
    ax.annotate('', xy=(85, 32), xytext=(85, 42), arrowprops=dict(facecolor=EMERALD_COLOR, edgecolor=EMERALD_COLOR, arrowstyle="->", lw=1.8))

    # Row 3: Retrieval, LLM & Synthesis (y = 22)
    r3_nodes = [
        (76, 17, 18, 14, "6. MEMORY RECALL\nTri-Factor Salience:\nSemantic Cosine +\nEbbinghaus Decay e^(-λΔt)", '#171e2b'),
        (54, 17, 18, 14, "7. LLM DIALOGUE\nPrompt Assembly +\nPersona Constraints\n(2-3 Poetic Sentences)", '#171e2b'),
        (32, 17, 18, 14, "8. CALLIGRAPHY\nProcedural Quill Draw;\nAdaptive Font (23→12px)\nAudio Scratch Feedback", '#1b2b1a'),
        (8, 17, 20, 14, "9. COMMIT & CHRONICLE\nLog Turn to SQLite;\nExtract Proposition;\nUpdate Chronicle Page", '#2d180d')
    ]

    for nx, ny, nw, nh, nlabel, nbg in r3_nodes:
        box = patches.FancyBboxPatch((nx, ny), nw, nh, boxstyle="round,pad=0.3,rounding_size=1",
                                     facecolor=nbg, edgecolor=GOLD_BORDER, linewidth=1.2)
        ax.add_patch(box)
        ax.text(nx + nw/2, ny + nh/2, nlabel, ha='center', va='center', fontsize=7.2, color=TEXT_LIGHT, multialignment='center')

    # Arrows in Row 3 (Right to Left)
    ax.annotate('', xy=(72, 24), xytext=(76, 24), arrowprops=dict(facecolor=GOLD_COLOR, arrowstyle="<-", lw=1.5))
    ax.annotate('', xy=(50, 24), xytext=(54, 24), arrowprops=dict(facecolor=GOLD_COLOR, arrowstyle="<-", lw=1.5))
    ax.annotate('', xy=(28, 24), xytext=(32, 24), arrowprops=dict(facecolor=GOLD_COLOR, arrowstyle="<-", lw=1.5))

    # Terminal Loop Back to Waiting
    ax.text(18, 8, "Status: 'The page has spoken' ➔ Diary awaits next inscription stroke",
            ha='center', va='center', fontsize=8, fontstyle='italic', color='#ffd166')

    plt.tight_layout()
    plt.savefig('presentation_assets/diagram_interaction_flowchart.png', dpi=300, facecolor=BG_COLOR)
    plt.close()
    print("Created presentation_assets/diagram_interaction_flowchart.png")

# -------------------------------------------------------------------------
# 3. Implementation Roadmap Gantt Chart (Slide 9)
# -------------------------------------------------------------------------
def generate_roadmap_diagram():
    fig, ax = plt.subplots(figsize=(12, 6.2), facecolor=BG_COLOR)
    ax.set_facecolor(PANEL_COLOR)

    tasks = [
        "1. Lit. Review & 30-Paper IEEE Synthesis",
        "2. Stroke Vector Canvas & Normalizer",
        "3. HTR Baseline Calibration & Temp. Scaling",
        "4. LLM Persona Prompting & Guardrails",
        "5. Episodic Memory Engine & Ebbinghaus Store",
        "6. Procedural Quill Calligraphy Renderer",
        "7. Writer-Disjoint Experimental Benchmark",
        "8. Integration, UI Polish & Final Defense"
    ]
    starts = [1, 2, 3, 4, 5, 5.5, 6.5, 7.5]
    durations = [2, 2, 2.5, 2, 2, 2, 1.5, 1.5]
    colors = ['#8ecae6', '#219ebc', '#023047', '#ffb703', '#fb8500', '#d4af37', '#e76f51', '#2ec4b6']

    y_pos = np.arange(len(tasks))
    ax.barh(y_pos, durations, left=starts, color=colors, edgecolor='#8c6d32', height=0.55, linewidth=1)

    ax.set_yticks(y_pos)
    ax.set_yticklabels(tasks, fontsize=9.2, fontweight='bold', color=TEXT_LIGHT)
    ax.invert_yaxis()  # top-down

    ax.set_xlabel('Project Timeline (Weeks 1 to 8)', fontsize=11, fontweight='bold', color='#ffd166')
    ax.set_xlim(0.5, 9.5)
    ax.set_xticks(range(1, 10))
    ax.set_xticklabels([f"Week {w}" for w in range(1, 10)], fontsize=9, color=TEXT_LIGHT)
    ax.grid(axis='x', linestyle='--', alpha=0.3, color='#8c6d32')

    # Sprint markers
    sprint_divs = [2.5, 4.5, 6.5, 8.5]
    sprint_names = ["Sprint 1: Core Foundation", "Sprint 2: Inference & HTR", "Sprint 3: Memory & Synthesis", "Sprint 4: Evaluation & Defense"]
    for i, s in enumerate(sprint_divs):
        ax.axvline(x=s, color=GOLD_COLOR, linestyle=':', alpha=0.6, linewidth=1.5)
        ax.text(s - 1.0, -0.6, sprint_names[i], ha='center', fontsize=8.2, fontweight='bold', color='#fceecf')

    ax.set_title("ENCHANTED INK — 8-WEEK RESEARCH & IMPLEMENTATION ROADMAP", fontsize=12, fontweight='bold', pad=22, color='#ffd166')

    plt.tight_layout()
    plt.savefig('presentation_assets/diagram_roadmap_gantt.png', dpi=300, facecolor=BG_COLOR)
    plt.close()
    print("Created presentation_assets/diagram_roadmap_gantt.png")

if __name__ == '__main__':
    generate_architecture_diagram()
    generate_flowchart_diagram()
    generate_roadmap_diagram()
