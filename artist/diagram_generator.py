"""Diagram rendering module for visualizing basketball analysis insights."""

from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image
from matplotlib import font_manager
from matplotlib import pyplot as plt
from matplotlib import rcParams
from matplotlib.patches import Arc
from matplotlib.patches import Circle
from matplotlib.patches import FancyArrowPatch
from matplotlib.patches import Rectangle


class DiagramGenerator:
    """Creates charts and diagrams from structured scouting insights."""

    def __init__(self) -> None:
        self.default_dpi = 150
        self.court_color = "#F5DEB3"
        self.line_color = "#333333"
        self.figure_size = (7.2, 7.2)
        self.font_candidates = ["PingFang SC", "Heiti SC", "STHeiti", "Arial Unicode MS", "DejaVu Sans"]
        self.chinese_font = self._load_chinese_font()
        rcParams["figure.dpi"] = self.default_dpi
        rcParams["axes.unicode_minus"] = False

    def _load_chinese_font(self) -> font_manager.FontProperties:
        for font_name in self.font_candidates:
            matches = [f.fname for f in font_manager.fontManager.ttflist if f.name == font_name]
            if matches:
                return font_manager.FontProperties(fname=matches[0])
        return font_manager.FontProperties(family="DejaVu Sans")

    def _prepare_canvas(self) -> tuple[Any, Any]:
        fig, ax = plt.subplots(figsize=self.figure_size, dpi=self.default_dpi)
        ax.set_xlim(0, 50)
        ax.set_ylim(0, 47)
        ax.set_aspect("equal")
        ax.set_facecolor(self.court_color)
        ax.set_xticks([])
        ax.set_yticks([])
        return fig, ax

    def draw_court(self, ax: Any) -> None:
        line_width = 2
        ax.set_facecolor(self.court_color)
        ax.add_patch(
            Rectangle((0, 0), 50, 47, facecolor=self.court_color, edgecolor=self.line_color, linewidth=line_width)
        )
        ax.add_patch(Rectangle((17, 28), 16, 19, fill=False, edgecolor=self.line_color, linewidth=line_width))
        ax.add_patch(Arc((25, 28), 12, 12, theta1=180, theta2=360, color=self.line_color, linewidth=line_width))
        ax.plot([3, 3], [47, 33], color=self.line_color, linewidth=line_width)
        ax.plot([47, 47], [47, 33], color=self.line_color, linewidth=line_width)
        ax.add_patch(Arc((25, 44), 47.5, 47.5, theta1=200, theta2=340, color=self.line_color, linewidth=line_width))
        ax.add_patch(Circle((25, 44), 0.75, fill=False, edgecolor=self.line_color, linewidth=line_width))
        ax.plot([22, 28], [43.2, 43.2], color=self.line_color, linewidth=line_width)
        ax.add_patch(Arc((25, 47), 12, 12, theta1=0, theta2=180, color=self.line_color, linewidth=line_width))

    def _badge_color(self, badge: str) -> str:
        return {"爆": "#E84560", "稳": "#1a6bb5", "强": "#FFD700"}.get(badge, "#1a6bb5")

    def _save_figure(self, fig: Any, output_path: str) -> str:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        buffer = BytesIO()
        fig.savefig(buffer, format="png", dpi=self.default_dpi, facecolor="white")
        plt.close(fig)
        buffer.seek(0)
        image = Image.open(buffer).convert("RGBA").resize((1080, 1080))
        image.save(output, format="PNG")
        return str(output)

    def create_tactical_diagram(self, tactic: dict[str, Any], output_path: str, badge: str = "稳") -> str:
        fig, ax = self._prepare_canvas()
        self.draw_court(ax)

        positions = tactic.get("player_positions", [])
        if isinstance(positions, list):
            for player in positions:
                if not isinstance(player, dict):
                    continue
                x = float(player.get("x", 25))
                y = float(player.get("y", 24))
                label = str(player.get("label", player.get("id", ""))).strip()
                team = str(player.get("team", "offense")).strip().lower()
                if team in {"defense", "def", "防守"}:
                    circle = Circle((x, y), 1.5, facecolor="none", edgecolor="#1a6bb5", linewidth=2.5)
                    text_color = "#1a6bb5"
                else:
                    circle = Circle((x, y), 1.5, facecolor="#E84560", edgecolor="#E84560", linewidth=2)
                    text_color = "white"
                ax.add_patch(circle)
                ax.text(
                    x,
                    y,
                    label,
                    ha="center",
                    va="center",
                    color=text_color,
                    fontsize=11,
                    fontproperties=self.chinese_font,
                )

        arrows = tactic.get("movement_arrows", [])
        if isinstance(arrows, list):
            for arrow in arrows:
                if not isinstance(arrow, dict):
                    continue
                from_pos = arrow.get("from_pos", [25, 25])
                to_pos = arrow.get("to_pos", [25, 25])
                if not isinstance(from_pos, (list, tuple)) or len(from_pos) != 2:
                    continue
                if not isinstance(to_pos, (list, tuple)) or len(to_pos) != 2:
                    continue
                start = (float(from_pos[0]), float(from_pos[1]))
                end = (float(to_pos[0]), float(to_pos[1]))
                arrow_patch = FancyArrowPatch(
                    start,
                    end,
                    arrowstyle="->",
                    color="#C0392B",
                    linewidth=2.2,
                    mutation_scale=14,
                    connectionstyle="arc3,rad=0.05",
                )
                ax.add_patch(arrow_patch)
                label = str(arrow.get("label", "")).strip()
                if label:
                    ax.text(
                        (start[0] + end[0]) / 2,
                        (start[1] + end[1]) / 2 + 0.8,
                        label,
                        fontsize=10,
                        color="#8E2A1D",
                        ha="center",
                        va="bottom",
                        fontproperties=self.chinese_font,
                    )

        title = str(tactic.get("name", "战术图")).strip() or "战术图"
        description = str(tactic.get("description", "")).strip()
        ax.set_title(title, fontsize=22, pad=12, fontproperties=self.chinese_font, color="#1f1f1f")
        if description:
            ax.text(
                1.5,
                1.2,
                description,
                fontsize=11,
                color="#2a2a2a",
                ha="left",
                va="bottom",
                fontproperties=self.chinese_font,
            )

        badge_value = badge if badge in {"爆", "稳", "强"} else "稳"
        badge_circle = Circle((46.5, 44.5), 2.0, facecolor=self._badge_color(badge_value), edgecolor="white", linewidth=2)
        ax.add_patch(badge_circle)
        ax.text(
            46.5,
            44.5,
            badge_value,
            ha="center",
            va="center",
            color="white",
            fontsize=14,
            fontproperties=self.chinese_font,
        )

        ax.text(
            49.2,
            0.8,
            "制图: AI战报",
            ha="right",
            va="bottom",
            fontsize=8.5,
            color="#7A7A7A",
            fontproperties=self.chinese_font,
        )
        return self._save_figure(fig, output_path)

    def create_simple_diagram(self, title: str, description: str, output_path: str) -> str:
        fig, ax = self._prepare_canvas()
        self.draw_court(ax)
        display_title = title.strip() if title.strip() else "战术解读"
        display_description = description.strip() if description.strip() else "暂无详细描述"
        ax.set_title(display_title, fontsize=22, pad=12, fontproperties=self.chinese_font, color="#1f1f1f")
        ax.text(
            3,
            6,
            display_description,
            fontsize=12,
            color="#1f1f1f",
            ha="left",
            va="bottom",
            fontproperties=self.chinese_font,
            bbox={"boxstyle": "round,pad=0.5", "facecolor": "white", "alpha": 0.78, "edgecolor": "#DDDDDD"},
        )
        ax.text(
            49.2,
            0.8,
            "制图: AI战报",
            ha="right",
            va="bottom",
            fontsize=8.5,
            color="#7A7A7A",
            fontproperties=self.chinese_font,
        )
        return self._save_figure(fig, output_path)


if __name__ == "__main__":
    sample_tactic = {
        "name": "高位挡拆顺下",
        "description": "1号持球发起高位挡拆，5号顺下冲击篮下，弱侧射手拉开空间。",
        "player_positions": [
            {"id": "1", "x": 25, "y": 20, "label": "1", "team": "offense"},
            {"id": "2", "x": 14, "y": 30, "label": "2", "team": "offense"},
            {"id": "3", "x": 36, "y": 30, "label": "3", "team": "offense"},
            {"id": "4", "x": 18, "y": 36, "label": "4", "team": "offense"},
            {"id": "5", "x": 25, "y": 31, "label": "5", "team": "offense"},
        ],
        "movement_arrows": [
            {"from_pos": [25, 20], "to_pos": [25, 27], "label": "借掩护推进"},
            {"from_pos": [25, 31], "to_pos": [25, 40], "label": "顺下吃饼"},
        ],
    }
    generator = DiagramGenerator()
    output = generator.create_tactical_diagram(sample_tactic, "data/outputs/test_diagram.png", badge="稳")
    print(f"✅ 战术图生成成功: {output}")
