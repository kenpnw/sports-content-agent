"""Figure 1: System architecture — 4 layers, 5 Agents, dual knowledge."""
from _setup import (
    plt, save_both,
    COLOR_PRIMARY, COLOR_ACCENT, COLOR_WARNING, COLOR_DANGER,
    COLOR_NEUTRAL, COLOR_PURPLE,
)
from matplotlib.patches import FancyBboxPatch
from matplotlib.lines import Line2D


def draw_box(ax, x, y, w, h, text, fc, ec="#222", fontsize=9.5, tc="white"):
    box = FancyBboxPatch(
        (x, y), w, h,
        boxstyle="round,pad=0.02,rounding_size=0.04",
        linewidth=1.2, facecolor=fc, edgecolor=ec,
    )
    ax.add_patch(box)
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center",
            fontsize=fontsize, color=tc, fontweight="bold", linespacing=1.3)


def arrow(ax, x1, y1, x2, y2, color="#888", lw=0.9):
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle="->", color=color, lw=lw,
                                connectionstyle="arc3,rad=0"))


fig, ax = plt.subplots(figsize=(12.5, 8))
ax.set_xlim(0, 12.5)
ax.set_ylim(0, 8.5)
ax.axis("off")

# Layer labels
for y, label in [
    (7.2, "Data Layer"),
    (5.5, "Knowledge Layer"),
    (3.0, "Agent Layer"),
    (0.7, "Output Layer"),
]:
    ax.text(0.15, y, label, ha="left", va="center", fontsize=8.5,
            color="#444", fontweight="bold", rotation=90)

# Layer 1: Data inputs
draw_box(ax, 1.4, 6.8, 2.2, 0.9, "NBA Live API\n(play-by-play)", COLOR_NEUTRAL)
draw_box(ax, 3.9, 6.8, 2.2, 0.9, "Full-Game Video\n(broadcast feed)", COLOR_NEUTRAL)
draw_box(ax, 6.4, 6.8, 2.2, 0.9, "Tactical Glossary\n(30+ basketball terms)", COLOR_NEUTRAL)
draw_box(ax, 8.9, 6.8, 2.6, 0.9, "Player & History\nMetadata", COLOR_NEUTRAL)

# Visibility / time_map between data and knowledge
draw_box(ax, 0.7, 6.0, 1.2, 0.45, "OCR\ntime_map", "#f0c419", tc="#222", fontsize=8.0)
draw_box(ax, 10.6, 6.0, 1.5, 0.45, "Scoreboard\nVisibility", "#f0c419", tc="#222", fontsize=8.0)

# Layer 2: Dual-Layer Knowledge
draw_box(ax, 2.0, 5.1, 3.8, 0.9,
         "Fact Store (SQLite)\nscores · timestamps · players · events",
         COLOR_PRIMARY, fontsize=9.5)
draw_box(ax, 6.5, 5.1, 4.5, 0.9,
         "Text RAG (Vector Index)\nplayer profiles · tactics notes · history",
         COLOR_PRIMARY, fontsize=9.5)

# Prompt Contract umbrella
draw_box(ax, 1.0, 4.35, 10.5, 0.4,
         "Prompt Contract  ·  task / source_scope / evidence / forbidden / output_contract / review_gate",
         "#ffffff", ec="#222", tc="#222", fontsize=8.5)

# Layer 3: Five Agents
agent_y = 2.5
agent_w = 2.0
agents = [
    ("Selector", "#3498db"),
    ("Researcher", "#2980b9"),
    ("Writer", "#1abc9c"),
    ("Fact Checker", COLOR_ACCENT),
    ("Risk Guard", COLOR_DANGER),
]
for i, (eng, color) in enumerate(agents):
    x = 0.9 + i * 2.27
    draw_box(ax, x, agent_y, agent_w, 1.0, eng, color, fontsize=10.5)

# Layer 4: Outputs
out_y = 0.2
out_w = 2.0
outputs = [
    ("Hupu Post\n(tactical thread)", "#d35400"),
    ("Douyin Script\n(short video)", "#000000"),
    ("Weibo Post\n(microblog)", "#e74c3c"),
    ("Xiaohongshu\n(visual feed)", "#ff478f"),
    ("Tactical GIFs\n(60 highlights)", COLOR_PURPLE),
]
for i, (label, color) in enumerate(outputs):
    x = 0.9 + i * 2.27
    draw_box(ax, x, out_y, out_w, 1.0, label, color, fontsize=9.5)

# Connectors data -> knowledge (consolidated)
for src_x in [2.5, 5.0, 7.5, 10.2]:
    arrow(ax, src_x, 6.8, src_x - 0.2, 6.0, color="#bbb")
arrow(ax, 1.3, 6.0, 2.0, 5.6, color="#bbb")
arrow(ax, 11.2, 6.0, 11.0, 5.6, color="#bbb")

# Knowledge -> Agents (via Prompt Contract)
for src_x in [3.9, 8.75]:
    arrow(ax, src_x, 5.1, src_x, 4.75, color="#777", lw=1.0)

# Prompt Contract -> Agents
for i in range(5):
    sx = 0.9 + i * 2.27 + agent_w / 2
    arrow(ax, sx, 4.35, sx, 3.5, color="#444", lw=1.0)

# Agent chain horizontal: review_gate goes left
for i in range(4):
    ax.annotate("", xy=(0.9 + (i + 1) * 2.27 - 0.05, agent_y + 0.5),
                xytext=(0.9 + i * 2.27 + agent_w + 0.05, agent_y + 0.5),
                arrowprops=dict(arrowstyle="->", color="#333", lw=1.5))

# Writer -> Outputs (fan out)
sx = 0.9 + 2 * 2.27 + agent_w / 2
for i in range(5):
    dx = 0.9 + i * 2.27 + out_w / 2
    arrow(ax, sx, agent_y, dx, out_y + 1.0, color="#bbb")

# Title
ax.text(6.25, 8.2,
        "Figure 1.  Multi-Agent Architecture for NBA Tactical Content Generation",
        ha="center", va="center", fontsize=12.5, color="#222", fontweight="bold")

# Legend
handles = [
    Line2D([0], [0], color=COLOR_NEUTRAL, lw=6, label="Data"),
    Line2D([0], [0], color=COLOR_PRIMARY, lw=6, label="Knowledge"),
    Line2D([0], [0], color="#3498db", lw=6, label="Agents"),
    Line2D([0], [0], color="#d35400", lw=6, label="Outputs"),
    Line2D([0], [0], color="#f0c419", lw=6, label="Alignment"),
]
ax.legend(handles=handles, loc="lower center", ncol=5,
          bbox_to_anchor=(0.5, -0.04), fontsize=8.5)

save_both(fig, "fig01_system_architecture")
print("done.")
