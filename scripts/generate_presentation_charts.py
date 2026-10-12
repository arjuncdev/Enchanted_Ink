import matplotlib.pyplot as plt
import numpy as np

# Set dark academic styling matching Enchanted Ink aesthetic
plt.rcParams['font.sans-serif'] = 'DejaVu Sans'
plt.rcParams['axes.edgecolor'] = '#8c6d32'
plt.rcParams['axes.linewidth'] = 1.2
plt.rcParams['text.color'] = '#f7ecd5'
plt.rcParams['axes.labelcolor'] = '#eeddbb'
plt.rcParams['xtick.color'] = '#eeddbb'
plt.rcParams['ytick.color'] = '#eeddbb'

BG_COLOR = '#160c07'
PANEL_COLOR = '#20120a'
GOLD_COLOR = '#d4af37'
EMERALD_COLOR = '#2ec4b6'
CORAL_COLOR = '#e76f51'
LIGHT_CREAM = '#f7ecd5'

# -------------------------------------------------------------------------
# Chart 1: Proposed HTR CER & WER Comparison
# -------------------------------------------------------------------------
def generate_htr_chart():
    fig, ax = plt.subplots(figsize=(6.2, 4.2), facecolor=BG_COLOR)
    ax.set_facecolor(PANEL_COLOR)

    models = ['CNN-LSTM\nCTC [3]', 'TrOCR\nBase [1]', 'Online BiLSTM\n(Bézier) [2]', 'Enchanted Ink\nHybrid (Prop.)']
    cer_scores = [6.4, 2.9, 3.8, 3.2]
    wer_scores = [14.8, 6.7, 8.5, 7.1]

    x = np.arange(len(models))
    width = 0.35

    rects1 = ax.bar(x - width/2, cer_scores, width, label='CER (%)', color='#e29578', edgecolor='#8c6d32', linewidth=1)
    rects2 = ax.bar(x + width/2, wer_scores, width, label='WER (%)', color=GOLD_COLOR, edgecolor='#fff2a8', linewidth=1)

    ax.set_ylabel('Error Rate (%) — Lower is Better', fontsize=10, fontweight='bold', color=LIGHT_CREAM)
    ax.set_title('Proposed HTR Accuracy Benchmark\n[IAM Handwriting Database — Illustrative]', fontsize=11, fontweight='bold', pad=12, color='#ffd166')
    ax.set_xticks(x)
    ax.set_xticklabels(models, fontsize=9)
    ax.legend(facecolor=PANEL_COLOR, edgecolor='#8c6d32', fontsize=9, labelcolor=LIGHT_CREAM)
    ax.grid(axis='y', linestyle='--', alpha=0.25, color='#eeddbb')
    ax.set_ylim(0, 18)

    # Bar value labels
    for rect in rects1:
        height = rect.get_height()
        ax.annotate(f'{height}%', xy=(rect.get_x() + rect.get_width()/2, height), xytext=(0, 3),
                    textcoords="offset points", ha='center', va='bottom', fontsize=8, color='#ffddd2')
    for rect in rects2:
        height = rect.get_height()
        ax.annotate(f'{height}%', xy=(rect.get_x() + rect.get_width()/2, height), xytext=(0, 3),
                    textcoords="offset points", ha='center', va='bottom', fontsize=8, color='#fff3b0')

    ax.text(0.5, -0.22, '*PROPOSED EVALUATION PROTOCOL (ILLUSTRATIVE TARGETS)*',
            transform=ax.transAxes, ha='center', fontsize=8, fontstyle='italic', color='#a48259')

    plt.tight_layout()
    plt.savefig('presentation_assets/chart_htr_benchmark.png', dpi=300, facecolor=fig.get_facecolor(), edgecolor='none')
    plt.close()
    print("Created presentation_assets/chart_htr_benchmark.png")

# -------------------------------------------------------------------------
# Chart 2: Calibrated Confidence Gating Simulation
# -------------------------------------------------------------------------
def generate_calibration_chart():
    fig, ax = plt.subplots(figsize=(6.2, 4.2), facecolor=BG_COLOR)
    ax.set_facecolor(PANEL_COLOR)

    taus = np.linspace(0.50, 0.95, 10)
    # Downstream conversational hallucination drops sharply with gating
    hallucination_rate = [28.5, 25.2, 21.0, 16.4, 11.2, 7.5, 4.1, 2.8, 1.9, 1.2]
    # Clarification trigger rate increases moderately
    clarification_rate = [2.0, 3.5, 5.8, 8.4, 12.0, 16.5, 22.0, 31.0, 44.0, 58.0]

    ax.plot(taus, hallucination_rate, marker='o', linewidth=2.4, color='#e63946', label='Downstream Error Rate (%)')
    ax.plot(taus, clarification_rate, marker='s', linewidth=2.4, color=EMERALD_COLOR, label='Clarification Prompt Rate (%)')

    # Highlight optimal operating threshold tau = 0.82
    ax.axvline(x=0.80, color=GOLD_COLOR, linestyle=':', linewidth=2, label=r'Operating Gate ($\tau = 0.80$)')
    ax.scatter([0.80], [4.1], color='#ffd166', s=100, zorder=5)

    ax.set_xlabel(r'Calibrated Confidence Threshold ($\tau$)', fontsize=10, fontweight='bold', color=LIGHT_CREAM)
    ax.set_ylabel('Interaction Rate (%)', fontsize=10, fontweight='bold', color=LIGHT_CREAM)
    ax.set_title('Uncertainty Gating Trade-Off\n[Error Reduction vs. User Clarification]', fontsize=11, fontweight='bold', pad=12, color='#ffd166')
    ax.legend(facecolor=PANEL_COLOR, edgecolor='#8c6d32', fontsize=8.5, labelcolor=LIGHT_CREAM, loc='center left')
    ax.grid(True, linestyle='--', alpha=0.25, color='#eeddbb')
    ax.set_ylim(0, 65)

    ax.text(0.5, -0.22, '*PROPOSED DECISION GATING SIMULATION (ILLUSTRATIVE)*',
            transform=ax.transAxes, ha='center', fontsize=8, fontstyle='italic', color='#a48259')

    plt.tight_layout()
    plt.savefig('presentation_assets/chart_calibration_tradeoff.png', dpi=300, facecolor=fig.get_facecolor(), edgecolor='none')
    plt.close()
    print("Created presentation_assets/chart_calibration_tradeoff.png")

# -------------------------------------------------------------------------
# Chart 3: Pipeline Latency Budget Breakdown
# -------------------------------------------------------------------------
def generate_latency_chart():
    fig, ax = plt.subplots(figsize=(6.2, 4.2), facecolor=BG_COLOR)
    ax.set_facecolor(PANEL_COLOR)

    stages = [
        'Stroke Vectorization\n& Normalization',
        'HTR Sequence\nInference & Calib.',
        'Tri-Factor Episodic\nMemory Retrieval',
        'LLM Streaming TTFT\n& Persona Context',
        'Procedural Quill\nCalligraphy Synthesis'
    ]
    latencies = [18, 145, 32, 480, 250]
    colors = ['#8ecae6', '#219ebc', '#023047', '#ffb703', '#fb8500']

    y_pos = np.arange(len(stages))
    bars = ax.barh(y_pos, latencies, color=colors, edgecolor='#8c6d32', linewidth=1)

    ax.set_yticks(y_pos)
    ax.set_yticklabels(stages, fontsize=8.5)
    ax.invert_yaxis()  # top-down
    ax.set_xlabel('Latency Budget (Milliseconds)', fontsize=10, fontweight='bold', color=LIGHT_CREAM)
    ax.set_title('End-to-End Pipeline Latency Budget\n[Total Budget Target: ~925 ms < 1.5s]', fontsize=11, fontweight='bold', pad=12, color='#ffd166')
    ax.grid(axis='x', linestyle='--', alpha=0.25, color='#eeddbb')
    ax.set_xlim(0, 600)

    for bar in bars:
        width = bar.get_width()
        ax.annotate(f'{width} ms', xy=(width, bar.get_y() + bar.get_height()/2), xytext=(5, 0),
                    textcoords="offset points", ha='left', va='center', fontsize=8.5, fontweight='bold', color=LIGHT_CREAM)

    ax.text(0.5, -0.22, '*TARGET LATENCY BUDGET (PROPOSED ARCHITECTURE)*',
            transform=ax.transAxes, ha='center', fontsize=8, fontstyle='italic', color='#a48259')

    plt.tight_layout()
    plt.savefig('presentation_assets/chart_latency_budget.png', dpi=300, facecolor=fig.get_facecolor(), edgecolor='none')
    plt.close()
    print("Created presentation_assets/chart_latency_budget.png")

if __name__ == '__main__':
    generate_htr_chart()
    generate_calibration_chart()
    generate_latency_chart()
