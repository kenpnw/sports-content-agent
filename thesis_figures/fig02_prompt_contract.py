"""Figure 2: Prompt Contract — the 6-field schema enforced on every LLM call."""
from _setup import plt, save_both, COLOR_PRIMARY, COLOR_ACCENT, COLOR_DANGER
from matplotlib.patches import FancyBboxPatch


def field_box(ax, x, y, w, h, name, body, color):
    box = FancyBboxPatch(
        (x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.04",
        linewidth=1.2, facecolor="#ffffff", edgecolor=color,
    )
    ax.add_patch(box)
    # Field name (colored header)
    ax.add_patch(FancyBboxPatch(
        (x, y + h - 0.4), w, 0.4,
        boxstyle="round,pad=0.02,rounding_size=0.04",
        linewidth=0, facecolor=color, edgecolor="none",
    ))
    ax.text(x + w / 2, y + h - 0.2, name, ha="center", va="center",
            color="white", fontsize=10.5, fontweight="bold")
    ax.text(x + 0.1, y + h - 0.5, body, ha="left", va="top",
            color="#222", fontsize=8.5, linespacing=1.5)


fig, ax = plt.subplots(figsize=(11.5, 8.5))
ax.set_xlim(0, 11.5)
ax.set_ylim(0, 8.5)
ax.axis("off")

# Title
ax.text(5.75, 8.2, "Figure 2.  Prompt Contract  -  6-Field Schema for Every LLM Call",
        ha="center", va="center", fontsize=12.5, color="#222", fontweight="bold")
ax.text(5.75, 7.7,
        "Each agent invocation must produce a payload that satisfies all six fields,\n"
        "enabling pre-generation policy enforcement and post-generation review.",
        ha="center", va="center", fontsize=9, color="#555", style="italic", linespacing=1.4)

fields = [
    ("task",
     "What the agent is asked to do.\n"
     "Verb-first, single-sentence intent.\n"
     "e.g. 'Generate a tactical comment\nfor possession poss_p1_e20.'",
     COLOR_PRIMARY),
    ("source_scope",
     "Whitelisted evidence sources.\n"
     "PBP slice, RAG section IDs, video\nframe range. Anything outside\nthis scope is forbidden.",
     COLOR_PRIMARY),
    ("evidence_requirements",
     "Per-assertion evidence binding.\n"
     "Every claim must cite an\nobservation_id or fact_id.\n"
     "Unsupported claims are rejected.",
     COLOR_ACCENT),
    ("forbidden_behaviors",
     "Hard-block list. e.g.:\n"
     " - inventing player names\n"
     " - injecting opinions on referees\n"
     " - forcing tactical labels onto\n   non-tactical events",
     COLOR_DANGER),
    ("output_contract",
     "Strict output shape.\n"
     "JSON schema with required keys\nand value types. Parse failure\ntriggers regeneration.",
     COLOR_PRIMARY),
    ("review_gate",
     "Downstream agents that may\nblock or amend this output.\n"
     "Typically Fact Checker, then\nRisk Guard. Each gate has\nveto rights.",
     "#2980b9"),
]

# 3 x 2 grid. y_top is the BOTTOM y of the first row; box height = cell_h.
cell_w, cell_h = 3.5, 2.7
margin_x, margin_y = 0.4, 0.4
y_top = 4.8
for i, (name, body, color) in enumerate(fields):
    row, col = divmod(i, 3)
    x = margin_x + col * (cell_w + 0.3)
    y = y_top - row * (cell_h + margin_y)
    field_box(ax, x, y, cell_w, cell_h, name, body, color)

# Footer note
ax.text(5.75, 0.15,
        "All six fields are validated by a schema gate before the LLM is invoked;\n"
        "fields are also re-checked against the generated output by Fact Checker and Risk Guard.",
        ha="center", va="center", fontsize=8.5, color="#666", style="italic", linespacing=1.4)

save_both(fig, "fig02_prompt_contract")
print("done.")
