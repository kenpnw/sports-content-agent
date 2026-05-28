"""Figure 4: Ablation across three systems — real numbers.

Numbers come from the actual thesis_scripts/run_ablation.py run on the
LAL vs GSW gold set, and thesis_scripts/eval_hallucination.py on the
OKC vs LAL G1 v16 report.
"""
from _setup import (
    plt, save_both, COLOR_PRIMARY, COLOR_ACCENT, COLOR_NEUTRAL, COLOR_DANGER,
)
import numpy as np


# Real numbers — run_ablation on LAL vs GSW gold set.
#   coverage      = share of gold claims the system *covered* (key contribution)
#   accuracy      = share of system-emitted claims that match gold (precision)
#   hallucination = share of system-emitted claims that don't match gold
#   trace_rate    = share of generated sentences carrying evidence_id
DATA = {
    "gpt_only":       {"coverage": 0.10, "accuracy": 1.00, "hallucination": 0.00, "trace": 0.18, "latency_s": 28.7},
    "highlight_only": {"coverage": 0.40, "accuracy": 1.00, "hallucination": 0.00, "trace": 0.61, "latency_s": 3.2},
    "main":           {"coverage": 0.73, "accuracy": 0.89, "hallucination": 0.11, "trace": 1.00, "latency_s": 53.6},
}

systems = ["GPT-only", "Highlight-only", "Ours"]
keys = ["gpt_only", "highlight_only", "main"]
bar_colors = [COLOR_NEUTRAL, "#3498db", COLOR_PRIMARY]
x = np.arange(3)

fig, axes = plt.subplots(1, 4, figsize=(16.5, 4.8))
ax1, ax2, ax3, ax4 = axes
plt.subplots_adjust(wspace=0.5)


def bar_panel(ax, values, title, fmt="{:.0%}", ylim_max=None, colors=None):
    cols = colors or bar_colors
    bars = ax.bar(x, values, color=cols, edgecolor="white", linewidth=1.5)
    for b, v in zip(bars, values):
        ax.text(b.get_x() + b.get_width() / 2,
                v + (max(values) - 0) * 0.025,
                fmt.format(v), ha="center", fontsize=10.5,
                fontweight="bold", color="#222")
    ax.set_title(title, fontsize=10.5, color="#222")
    ax.set_xticks(x)
    ax.set_xticklabels(systems, fontsize=9)
    ax.yaxis.grid(True, color="#dddddd", linewidth=0.6)
    ax.set_axisbelow(True)
    if ylim_max is not None:
        ax.set_ylim(0, ylim_max)


bar_panel(ax1, [DATA[k]["coverage"] for k in keys],
          "(a) Claim Coverage  $\\uparrow$\n(of gold claims covered)",
          fmt="{:.0%}", ylim_max=1.10)

bar_panel(ax2, [DATA[k]["accuracy"] for k in keys],
          "(b) Claim Accuracy  $\\uparrow$\n(precision of emitted claims)",
          fmt="{:.0%}", ylim_max=1.15)

bar_panel(ax3, [DATA[k]["hallucination"] for k in keys],
          "(c) Hallucination Rate  $\\downarrow$\n(unsupported emitted claims)",
          fmt="{:.0%}", ylim_max=0.35,
          colors=[COLOR_ACCENT, COLOR_ACCENT, "#e67e22"])

bar_panel(ax4, [DATA[k]["trace"] for k in keys],
          "(d) Sentence-Level Trace  $\\uparrow$\n(evidence_id coverage)",
          fmt="{:.0%}", ylim_max=1.15)

for ax in axes:
    ax.set_ylabel("")

fig.suptitle(
    "Figure 4.  Three-System Ablation on LAL vs GSW Gold Set  -  "
    "Coverage / Accuracy / Hallucination / Trace",
    fontsize=12.5, y=1.04, fontweight="bold")

# Subtitle: the key insight about gpt_only "100% accuracy"
fig.text(0.5, -0.04,
         "Note: GPT-only and Highlight-only achieve 100% accuracy by emitting very few claims "
         "(10% and 40% coverage respectively). Ours emits 7.3× more claims than GPT-only "
         "while accepting an 11% hallucination cost.",
         ha="center", fontsize=9, color="#666", style="italic")

save_both(fig, "fig04_ablation")
print("done.")
