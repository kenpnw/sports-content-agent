"""Figure 6: 5-Agent supervision protocol — sequence diagram."""
from _setup import (
    plt, save_both, COLOR_PRIMARY, COLOR_ACCENT, COLOR_WARNING,
    COLOR_DANGER, COLOR_NEUTRAL,
)
from matplotlib.patches import Rectangle, FancyBboxPatch


fig, ax = plt.subplots(figsize=(12, 7))
ax.set_xlim(0, 12)
ax.set_ylim(0, 9)
ax.axis("off")

# Title
ax.text(6.0, 8.6,
        "Figure 6.  Five-Agent Supervision Protocol  -  Sequence Diagram",
        ha="center", va="center", fontsize=12.5, color="#222", fontweight="bold")

agents = [
    ("Selector",      "#3498db"),
    ("Researcher",    "#2980b9"),
    ("Writer",        "#1abc9c"),
    ("Fact Checker",  COLOR_ACCENT),
    ("Risk Guard",    COLOR_DANGER),
]
n = len(agents)
col_x = [1.5 + i * 2.3 for i in range(n)]

# Agent headers
for x, (name, color) in zip(col_x, agents):
    ax.add_patch(FancyBboxPatch(
        (x - 0.85, 7.5), 1.7, 0.5,
        boxstyle="round,pad=0.02,rounding_size=0.04",
        facecolor=color, edgecolor="none",
    ))
    ax.text(x, 7.75, name, ha="center", va="center",
            color="white", fontsize=10, fontweight="bold")
    # Lifeline
    ax.plot([x, x], [7.5, 0.5], color="#bbb", lw=0.6, linestyle="--", zorder=0)

# Message helper
def msg(ax, y, sx, dx, label, color="#333", lw=1.4, dashed=False, italic=False):
    style = "--" if dashed else "-"
    ax.annotate("", xy=(dx, y), xytext=(sx, y),
                arrowprops=dict(arrowstyle="->", color=color, lw=lw, linestyle=style))
    mid_x = (sx + dx) / 2
    ax.text(mid_x, y + 0.08, label, ha="center", va="bottom",
            fontsize=8.5, color=color, fontweight="bold",
            style=("italic" if italic else "normal"))

# Activation boxes
def activation(ax, x, y0, y1, color):
    ax.add_patch(Rectangle((x - 0.06, y1), 0.12, y0 - y1,
                           facecolor=color, edgecolor="none", alpha=0.55))

# Step 1: orchestrator -> Selector
y = 6.9
ax.text(0.05, y + 0.08, "[trigger]", fontsize=8.5, color="#666", style="italic")
msg(ax, y, 0.6, col_x[0], "60 candidate observations", color="#444")
activation(ax, col_x[0], y, 6.4, "#3498db")

# Selector -> Researcher
y -= 0.45
msg(ax, y, col_x[0], col_x[1],
    "shortlist(top 60)\nwith evidence_ids", color="#222")
activation(ax, col_x[1], y, 5.7, "#2980b9")

# Researcher -> Fact Store + Text RAG (side note)
y -= 0.45
ax.text(col_x[1] + 0.3, y + 0.04,
        "[Fact Store + Text RAG fetch]",
        fontsize=8.0, color="#777", style="italic")

# Researcher -> Writer
y -= 0.45
msg(ax, y, col_x[1], col_x[2],
    "evidence packet\n(facts + RAG snippets)", color="#222")
activation(ax, col_x[2], y, 4.7, "#1abc9c")

# Writer -> Fact Checker
y -= 0.65
msg(ax, y, col_x[2], col_x[3],
    "draft segment\n+ evidence claims", color="#222")
activation(ax, col_x[3], y, 3.7, COLOR_ACCENT)

# Fact Checker veto returns to Writer
y -= 0.45
msg(ax, y, col_x[3], col_x[2],
    "reject (3.4%) -> revise",
    color=COLOR_DANGER, dashed=True, italic=True)

# After revise pass (loop)
y -= 0.3
ax.text(col_x[2] - 0.85, y + 0.04,
        "[revision loop, max 2 iterations]",
        fontsize=8.0, color="#777", style="italic")

# Writer -> Fact Checker (pass)
y -= 0.5
msg(ax, y, col_x[2], col_x[3], "revised draft", color="#222")

# Fact Checker -> Risk Guard
y -= 0.5
msg(ax, y, col_x[3], col_x[4],
    "verified segment\n+ confidence", color="#222")
activation(ax, col_x[4], y, 1.5, COLOR_DANGER)

# Risk Guard veto
y -= 0.45
msg(ax, y, col_x[4], col_x[2],
    "block (0.8%) -> remove",
    color=COLOR_DANGER, dashed=True, italic=True)

# Risk Guard -> orchestrator (out of frame)
y -= 0.55
msg(ax, y, col_x[4], 11.5, "final segments -> 4 publishers", color="#1f3a93", lw=1.8)
ax.text(11.5, y + 0.08, "out", fontsize=8.5, color="#1f3a93",
        style="italic", ha="left")

# Bottom: gate metadata
y_box = 0.0
ax.add_patch(Rectangle((0.5, y_box), 11, 0.5, facecolor="#f5f5f5",
                       edgecolor="#ccc", lw=0.6))
ax.text(6.0, y_box + 0.25,
        "Veto rights:  Fact Checker may force a single revise loop. "
        "Risk Guard has absolute reject -> the segment is removed from output.",
        ha="center", va="center", fontsize=9, color="#444", style="italic")

save_both(fig, "fig06_agent_sequence")
print("done.")
