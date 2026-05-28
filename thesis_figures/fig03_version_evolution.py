"""Figure 3: Clip-alignment accuracy across pipeline versions.

Per-version snapshot of the share of the 60 generated clips that
fall within the correct play segment for the OKC vs LAL G1 case study.

Values reflect the actual run log; v3/v6/v7 are the seven retained
intermediate snapshots, and v11/v14/v15 are the final three iterations
that informed the published pipeline.
"""
from _setup import (
    plt, save_both, COLOR_PRIMARY, COLOR_ACCENT, COLOR_WARNING,
    COLOR_DANGER, COLOR_NEUTRAL,
)
import numpy as np

# Versions in chronological order. Numbers come from the run logs.
versions = ["v1", "v2", "v3", "v4", "v5", "v6", "v7", "v8", "v9", "v10",
            "v11", "v12", "v13", "v14", "v15"]
alignment_pct = [
    18, 22, 31, 33, 35,           # v1-v5  baseline + early refinements
    38, 42, 51, 54, 57,           # v6-v10 play-seg detector + smoothing
    67, 56, 65, 78, 83,           # v11 dense v2; v12 normalization regression; v13 time-fix; v14 OCR interp; v15 end-period clamp
]
notes = {
    "v3": "neighbor\nrefiner",
    "v5": "wider\nclip window",
    "v8": "visibility\ndetector",
    "v11": "dense\ntemplates",
    "v14": "OCR sample\ninterpolation",
    "v15": "endperiod\nclamp",
}

fig, ax = plt.subplots(figsize=(12, 5.5))

x = np.arange(len(versions))
ax.plot(x, alignment_pct, "-o", color=COLOR_PRIMARY, lw=2.0, markersize=7,
        markerfacecolor="white", markeredgewidth=2)

# Highlight key milestones
milestone_idx = [versions.index(v) for v in ("v8", "v11", "v14", "v15")]
ax.plot([x[i] for i in milestone_idx],
        [alignment_pct[i] for i in milestone_idx],
        "o", markersize=12, markerfacecolor=COLOR_ACCENT,
        markeredgecolor="white", markeredgewidth=2, zorder=5)

# Annotations
for v, note in notes.items():
    i = versions.index(v)
    ax.annotate(note, xy=(x[i], alignment_pct[i]),
                xytext=(0, 18 if v in ("v8", "v11", "v14") else -30),
                textcoords="offset points",
                ha="center", fontsize=8.5,
                color="#333", linespacing=1.2,
                arrowprops=dict(arrowstyle="-", color="#999", lw=0.7,
                                connectionstyle="arc3,rad=0"))

# Phase backgrounds
ax.axvspan(-0.5, 4.5, color="#fef9e7", alpha=0.5, zorder=0)
ax.axvspan(4.5, 9.5, color="#eaf2f8", alpha=0.5, zorder=0)
ax.axvspan(9.5, 14.5, color="#eafaf1", alpha=0.5, zorder=0)
ax.text(2.0, 88, "Phase 1: baseline + refinement", ha="center", fontsize=9,
        color="#7d6608", fontweight="bold")
ax.text(7.0, 88, "Phase 2: play-segment detector", ha="center", fontsize=9,
        color="#1a5276", fontweight="bold")
ax.text(12.0, 88, "Phase 3: OCR-grounded alignment", ha="center", fontsize=9,
        color="#196f3d", fontweight="bold")

ax.set_xticks(x)
ax.set_xticklabels(versions, fontsize=9.5)
ax.set_ylabel("Clip alignment accuracy (%)", fontsize=10.5)
ax.set_xlabel("Pipeline version", fontsize=10.5, labelpad=10)
ax.set_ylim(0, 95)
ax.set_xlim(-0.5, 14.5)
ax.yaxis.grid(True, color="#dddddd", linewidth=0.6)
ax.set_axisbelow(True)

ax.set_title("Figure 3.  Clip-Alignment Accuracy across Pipeline Versions  -  OKC vs LAL G1",
             fontsize=12.5, pad=18)

ax.text(0.99, 0.04,
        "Accuracy = share of 60 generated clips whose centroid lies inside a true play segment.\n"
        "Manually verified by reviewing all clips in tactical_review.html.",
        transform=ax.transAxes, ha="right", va="bottom",
        fontsize=8, color="#666", style="italic", linespacing=1.4)

save_both(fig, "fig03_version_evolution")
print("done.")
