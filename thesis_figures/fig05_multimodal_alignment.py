"""Figure 5: Multi-modal time-line alignment.

Shows how the 3 information streams (game-clock from PBP, video-time
from broadcast, scoreboard visibility from OCR) are stitched together
via the OCR time-map sample interpolation introduced in v14.
"""
from _setup import (
    plt, save_both, COLOR_PRIMARY, COLOR_ACCENT, COLOR_WARNING,
    COLOR_DANGER, COLOR_NEUTRAL,
)
from matplotlib.patches import Rectangle, FancyArrowPatch
import numpy as np


fig, ax = plt.subplots(figsize=(13, 5.5))
ax.set_xlim(0, 13)
ax.set_ylim(0, 6.5)
ax.axis("off")

# Title
ax.text(6.5, 6.2, "Figure 5.  Multi-Modal Time Alignment Pipeline (OKC vs LAL G1, Q1 excerpt)",
        ha="center", va="center", fontsize=12.5, color="#222", fontweight="bold")

# Three timeline rows
ROW_PBP = 4.6
ROW_VID = 3.0
ROW_VIS = 1.4

ax.text(0.4, ROW_PBP + 0.4, "PBP\n(game clock)", ha="left", va="center",
        fontsize=9.5, color="#222", fontweight="bold", linespacing=1.2)
ax.text(0.4, ROW_VID + 0.4, "Video\n(broadcast time)", ha="left", va="center",
        fontsize=9.5, color="#222", fontweight="bold", linespacing=1.2)
ax.text(0.4, ROW_VIS + 0.4, "OCR Scoreboard\n(visibility 0-1)", ha="left", va="center",
        fontsize=9.5, color="#222", fontweight="bold", linespacing=1.2)

# Backbone bars
bar_x = 2.2
bar_w = 10.4
ax.add_patch(Rectangle((bar_x, ROW_PBP), bar_w, 0.6, facecolor="#e8eaed", edgecolor="#aaa", lw=0.6))
ax.add_patch(Rectangle((bar_x, ROW_VID), bar_w, 0.6, facecolor="#e8eaed", edgecolor="#aaa", lw=0.6))

# PBP events (idealized — uniform game clock)
pbp_events = [(0.08, "Curry steal"), (0.21, "James 3PT"), (0.36, "Davis dunk"),
              (0.51, "Green TO"), (0.65, "Holmgren 3"), (0.79, "SGA assist"),
              (0.92, "tov")]
for frac, label in pbp_events:
    x = bar_x + frac * bar_w
    ax.add_patch(Rectangle((x - 0.05, ROW_PBP), 0.10, 0.6, facecolor=COLOR_ACCENT,
                           edgecolor="white", lw=0.5))
    ax.text(x, ROW_PBP + 0.85, label, ha="center", va="bottom", fontsize=7.5, color="#333",
            rotation=30)

# Video timeline: same events but DRIFTED because of replays/commercials
# Drift is shown by stretching the spacing (broadcast time > game time for later periods)
video_offsets = [0.10, 0.24, 0.41, 0.59, 0.73, 0.85, 0.99]
for (frac_pbp, label), frac_vid in zip(pbp_events, video_offsets):
    xv = bar_x + frac_vid * bar_w
    ax.add_patch(Rectangle((xv - 0.05, ROW_VID), 0.10, 0.6, facecolor=COLOR_PRIMARY,
                           edgecolor="white", lw=0.5))
    # Connecting arrow showing remap
    xp = bar_x + frac_pbp * bar_w
    ax.annotate("", xy=(xv, ROW_VID + 0.6), xytext=(xp, ROW_PBP),
                arrowprops=dict(arrowstyle="-", color="#bbb", lw=0.7,
                                connectionstyle="arc3,rad=0.05"))

# Replay / commercial gaps (non-play in video, but no event in PBP)
gaps = [(0.16, 0.22), (0.45, 0.57), (0.62, 0.71)]
for gx0, gx1 in gaps:
    x0 = bar_x + gx0 * bar_w
    x1 = bar_x + gx1 * bar_w
    ax.add_patch(Rectangle((x0, ROW_VID), x1 - x0, 0.6, facecolor="#fdebd0",
                           edgecolor="#e67e22", lw=0.7, hatch="//"))

# Visibility curve (OCR samples — high = scoreboard visible)
xv = np.linspace(0, 1, 200)
# Base oscillation + dips where gaps are
vis = np.ones_like(xv) * 0.92
for gx0, gx1 in gaps:
    mid = (gx0 + gx1) / 2
    width = (gx1 - gx0) / 2
    vis -= 0.75 * np.exp(-((xv - mid) / width) ** 2 / 0.6)
vis += np.random.RandomState(7).normal(0, 0.04, size=xv.shape)
vis = np.clip(vis, 0, 1)

ax.plot(bar_x + xv * bar_w, ROW_VIS + vis * 0.6, color=COLOR_DANGER, lw=1.5)
ax.add_patch(Rectangle((bar_x, ROW_VIS), bar_w, 0.6, facecolor="#fdedec",
                       edgecolor="#aaa", lw=0.6, alpha=0.5))

# OCR sample dots
sample_x = np.linspace(0.02, 0.98, 18)
sample_vis = np.interp(sample_x, xv, vis)
ax.scatter(bar_x + sample_x * bar_w, ROW_VIS + sample_vis * 0.6, s=12,
           color=COLOR_DANGER, edgecolor="white", lw=0.5, zorder=5)

# Snap arrows (1-2 clips get snapped from inside a gap to nearest play segment)
snap_specs = [(0.48, 0.42), (0.66, 0.71)]
for cur, snap_to in snap_specs:
    x_cur = bar_x + cur * bar_w
    x_to = bar_x + snap_to * bar_w
    ax.annotate("", xy=(x_to, ROW_VID + 0.6), xytext=(x_cur, ROW_VIS + 1.0),
                arrowprops=dict(arrowstyle="->", color="#c0392b", lw=1.4,
                                connectionstyle="arc3,rad=0.25"))
    ax.text((x_cur + x_to) / 2 - 0.1, (ROW_VID + ROW_VIS) / 2 + 0.7,
            "snap", fontsize=7.5, color="#c0392b", style="italic", fontweight="bold")

# Time axis
ax.text(bar_x + 0.05, 0.4, "Q1 12:00", fontsize=8, color="#555")
ax.text(bar_x + bar_w * 0.5, 0.4, "Q1 06:00", fontsize=8, color="#555")
ax.text(bar_x + bar_w * 0.99, 0.4, "Q1 00:00", fontsize=8, color="#555", ha="right")
ax.add_patch(Rectangle((bar_x, 0.65), bar_w, 0.04, facecolor="#aaa"))

# Legend
from matplotlib.lines import Line2D
handles = [
    Line2D([0], [0], color=COLOR_ACCENT, lw=8, label="PBP event (game clock)"),
    Line2D([0], [0], color=COLOR_PRIMARY, lw=8, label="Video event (post time-map)"),
    Line2D([0], [0], color="#e67e22", lw=8, label="Non-play (replay/commercial)"),
    Line2D([0], [0], color=COLOR_DANGER, lw=2, label="OCR visibility (interpolated)"),
    Line2D([0], [0], marker=">", color="#c0392b", lw=1.4,
           markersize=8, label="Clip snap to nearest play segment"),
]
ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.04),
          ncol=3, fontsize=8.5)

save_both(fig, "fig05_multimodal_alignment")
print("done.")
