"""Shared matplotlib setup for thesis figures.

Strategy: figures use ENGLISH text only (DejaVu Sans). Both the Chinese
and English thesis docx will reference these figures and provide their
own captions in the appropriate language. This is standard academic
practice and avoids the lack of a font with both CJK + Latin coverage
in this environment.
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path

plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["font.sans-serif"] = ["DejaVu Sans", "Liberation Sans", "Arial"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["pdf.fonttype"] = 42
plt.rcParams["ps.fonttype"] = 42
plt.rcParams["savefig.dpi"] = 200
plt.rcParams["figure.dpi"] = 100
plt.rcParams["axes.spines.top"] = False
plt.rcParams["axes.spines.right"] = False
plt.rcParams["axes.edgecolor"] = "#333"
plt.rcParams["axes.labelcolor"] = "#222"
plt.rcParams["xtick.color"] = "#444"
plt.rcParams["ytick.color"] = "#444"
plt.rcParams["axes.titleweight"] = "bold"
plt.rcParams["axes.titlepad"] = 12
plt.rcParams["legend.frameon"] = False
plt.rcParams["legend.fontsize"] = 9

OUT_DIR = Path(__file__).parent / "out"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Academic palette
COLOR_PRIMARY = "#1f3a93"     # deep blue — main / our system
COLOR_ACCENT = "#27ae60"      # green — fact checker, success
COLOR_WARNING = "#e67e22"     # orange — alternative
COLOR_DANGER = "#c0392b"      # red — risk guard, hallucination
COLOR_NEUTRAL = "#7f8c8d"     # gray — data / neutral
COLOR_PURPLE = "#8e44ad"      # purple — output
COLOR_TEAL = "#16a085"
COLOR_LIGHT_BG = "#ecf0f1"


def save_both(fig, name: str) -> None:
    """Save a figure as PNG (for docx) and PDF (for archive)."""
    for ext in ("png", "pdf"):
        path = OUT_DIR / f"{name}.{ext}"
        fig.savefig(path, bbox_inches="tight", facecolor="white")
        print(f"  -> {path}")
