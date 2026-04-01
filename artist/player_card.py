"""Player card module for generating stylized athlete summary visuals."""

import math
import os
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image
from PIL import ImageDraw
from PIL import ImageFont
from matplotlib import pyplot as plt
from matplotlib.patches import Polygon


class PlayerCard:
    """Builds player profile card assets for Chinese social platforms."""

    def __init__(self) -> None:
        self.palette = {"primary": "#1a1a2e", "accent": "#e94560", "gold": "#ffd700"}
        self.card_size = (1080, 1080)
        self.card_style = "hupu"
        self.font_path = self._resolve_chinese_font_path()
        self.badge_colors = {"爆": "#E94560", "稳": "#2F80ED", "强": "#FFD700"}

    def _resolve_chinese_font_path(self) -> str:
        candidate_paths = [
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/STHeiti Medium.ttc",
            "/System/Library/Fonts/Hiragino Sans GB.ttc",
            "/Library/Fonts/Arial Unicode.ttf",
        ]
        for font_path in candidate_paths:
            if os.path.exists(font_path):
                return font_path
        return ""

    def _font(self, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        if self.font_path:
            return ImageFont.truetype(self.font_path, size)
        return ImageFont.load_default()

    def _safe_stat_value(self, stats: dict[str, Any], key: str) -> float:
        value = stats.get(key, 50)
        try:
            number = float(value)
        except (TypeError, ValueError):
            return 50.0
        return max(0.0, min(100.0, number))

    def _build_gradient_background(self) -> Image.Image:
        width, height = self.card_size
        top_rgb = (26, 26, 46)
        bottom_rgb = (22, 33, 62)
        image = Image.new("RGBA", (width, height))
        draw = ImageDraw.Draw(image)
        for y in range(height):
            ratio = y / max(1, height - 1)
            color = (
                int(top_rgb[0] * (1 - ratio) + bottom_rgb[0] * ratio),
                int(top_rgb[1] * (1 - ratio) + bottom_rgb[1] * ratio),
                int(top_rgb[2] * (1 - ratio) + bottom_rgb[2] * ratio),
                255,
            )
            draw.line([(0, y), (width, y)], fill=color)
        return image

    def create_stat_radar(self, stats: dict[str, Any]) -> Image.Image:
        labels = ["scoring", "defense", "playmaking", "athleticism", "efficiency"]
        values = [self._safe_stat_value(stats, label) for label in labels]
        values.append(values[0])
        angles = [n / float(len(labels)) * 2 * math.pi for n in range(len(labels))]
        angles.append(angles[0])

        fig = plt.figure(figsize=(4, 4), dpi=150)
        ax = fig.add_subplot(111, polar=True)
        fig.patch.set_alpha(0.0)
        ax.set_facecolor((0, 0, 0, 0))
        ax.set_ylim(0, 100)
        ax.grid(color="#FFFFFF", alpha=0.2, linewidth=1)
        ax.set_xticks([])
        ax.set_yticks([20, 40, 60, 80, 100])
        ax.set_yticklabels([])

        ax.plot(angles, values, color=self.palette["accent"], linewidth=3)
        ax.fill(angles, values, color=self.palette["accent"], alpha=0.35)

        outer_points = [(angle, 100) for angle in angles[:-1]]
        polygon_xy = [(r * math.cos(t), r * math.sin(t)) for t, r in outer_points]
        ax.add_patch(Polygon(polygon_xy, closed=True, fill=False, edgecolor="#FFFFFF", alpha=0.15, linewidth=1))

        for angle, label in zip(angles[:-1], labels):
            ax.text(
                angle,
                112,
                label.upper(),
                color="#F5F5F5",
                fontsize=8,
                ha="center",
                va="center",
            )

        buffer = BytesIO()
        fig.savefig(buffer, format="png", transparent=True, bbox_inches="tight", pad_inches=0.2)
        plt.close(fig)
        buffer.seek(0)
        radar = Image.open(buffer).convert("RGBA")
        return radar

    def _draw_badge(self, canvas: Image.Image, badge: str) -> None:
        draw = ImageDraw.Draw(canvas)
        badge_value = badge if badge in self.badge_colors else "稳"
        color = self.badge_colors[badge_value]
        center = (960, 120)
        radius = 52
        draw.ellipse(
            [center[0] - radius, center[1] - radius, center[0] + radius, center[1] + radius],
            fill=color,
            outline="#FFFFFF",
            width=4,
        )
        draw.text(center, badge_value, fill="#111111", font=self._font(50), anchor="mm")

    def create_player_card(self, player: dict[str, Any], badge: str, output_path: str) -> str:
        card = self._build_gradient_background()
        draw = ImageDraw.Draw(card)

        name = str(player.get("name", "未知球员")).strip() or "未知球员"
        team = str(player.get("team", "未知球队")).strip() or "未知球队"
        key_insight = str(player.get("key_insight", "暂无关键信息")).strip() or "暂无关键信息"
        comparison = str(player.get("comparison", "")).strip()
        stats = player.get("stats", {})
        if not isinstance(stats, dict):
            stats = {}

        draw.text((60, 80), name, fill="#FFFFFF", font=self._font(88))
        if comparison:
            draw.text((60, 190), comparison, fill="#E0E0E0", font=self._font(34))

        radar = self.create_stat_radar(stats).resize((560, 560))
        card.alpha_composite(radar, dest=(260, 235))

        draw.rounded_rectangle([60, 825, 1020, 950], radius=28, fill=(255, 255, 255, 24), outline="#FFFFFF", width=2)
        draw.text((90, 860), key_insight, fill="#F8F8F8", font=self._font(34))

        self._draw_badge(card, badge)

        draw.rectangle([0, 980, 1080, 1080], fill=self.palette["primary"])
        draw.text((50, 1025), team, fill="#FFFFFF", font=self._font(38), anchor="lm")
        draw.text((1030, 1025), "AI战报", fill=self.palette["gold"], font=self._font(36), anchor="rm")

        output_dir = os.path.dirname(output_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
        card.convert("RGB").save(output_path, format="PNG")
        return output_path

    def _top_stat_difference(self, stats1: dict[str, Any], stats2: dict[str, Any]) -> tuple[str, float]:
        labels = ["scoring", "defense", "playmaking", "athleticism", "efficiency"]
        diffs = []
        for label in labels:
            value1 = self._safe_stat_value(stats1, label)
            value2 = self._safe_stat_value(stats2, label)
            diffs.append((label, value1 - value2))
        diffs.sort(key=lambda item: abs(item[1]), reverse=True)
        return diffs[0]

    def create_comparison_card(
        self, player1: dict[str, Any], player2: dict[str, Any], output_path: str
    ) -> str:
        card = self._build_gradient_background()
        draw = ImageDraw.Draw(card)

        name1 = str(player1.get("name", "球员A")).strip() or "球员A"
        name2 = str(player2.get("name", "球员B")).strip() or "球员B"
        team1 = str(player1.get("team", "球队A")).strip() or "球队A"
        team2 = str(player2.get("team", "球队B")).strip() or "球队B"
        stats1 = player1.get("stats", {})
        stats2 = player2.get("stats", {})
        if not isinstance(stats1, dict):
            stats1 = {}
        if not isinstance(stats2, dict):
            stats2 = {}

        radar1 = self.create_stat_radar(stats1).resize((380, 380))
        radar2 = self.create_stat_radar(stats2).resize((380, 380))
        card.alpha_composite(radar1, dest=(110, 260))
        card.alpha_composite(radar2, dest=(590, 260))

        draw.text((180, 120), name1, fill="#FFFFFF", font=self._font(56), anchor="mm")
        draw.text((900, 120), name2, fill="#FFFFFF", font=self._font(56), anchor="mm")
        draw.text((180, 180), team1, fill="#E0E0E0", font=self._font(30), anchor="mm")
        draw.text((900, 180), team2, fill="#E0E0E0", font=self._font(30), anchor="mm")

        draw.ellipse([480, 430, 600, 550], fill=self.palette["accent"])
        draw.text((540, 490), "VS", fill="#FFFFFF", font=self._font(52), anchor="mm")

        top_label, diff = self._top_stat_difference(stats1, stats2)
        if diff > 0:
            summary = f"{name1} 在 {top_label.upper()} 领先 {abs(diff):.0f} 分"
        elif diff < 0:
            summary = f"{name2} 在 {top_label.upper()} 领先 {abs(diff):.0f} 分"
        else:
            summary = f"双方在 {top_label.upper()} 持平"

        draw.rounded_rectangle([90, 760, 990, 930], radius=28, fill=(255, 255, 255, 24), outline="#FFFFFF", width=2)
        draw.text((540, 845), summary, fill="#F8F8F8", font=self._font(42), anchor="mm")

        draw.rectangle([0, 980, 1080, 1080], fill=self.palette["primary"])
        draw.text((540, 1025), "AI战报 对位对比", fill=self.palette["gold"], font=self._font(36), anchor="mm")

        output_dir = os.path.dirname(output_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
        card.convert("RGB").save(output_path, format="PNG")
        return output_path

    def main(self, player_data: dict[str, Any]) -> str:
        output_file = Path("player_card.png").as_posix()
        return self.create_player_card(player_data, "稳", output_file)
