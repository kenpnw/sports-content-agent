"""Infographic module for composing narrative sports graphics."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates: list[str] = []
    if bold:
        candidates.extend([
            "C:/Windows/Fonts/msyhbd.ttc",
            "C:/Windows/Fonts/simhei.ttf",
        ])
    candidates.extend([
        # Windows
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/simsun.ttc",
        # macOS
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
        # Linux
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ])
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


class Infographic:
    """Generates infographic assets tailored for basketball story posts."""

    # 1080x1080 square — fits Instagram / Weibo / Hupu image format
    SIZE = (1080, 1080)

    # Color palette
    BG_TOP = (18, 18, 30)
    BG_BOTTOM = (28, 24, 48)
    ACCENT = (233, 69, 96)       # red accent
    GOLD = (255, 215, 0)
    WHITE = (255, 255, 255)
    LIGHT_GRAY = (200, 200, 210)
    DARK_PANEL = (30, 30, 50)
    WIN_BLUE = (31, 75, 143)
    LOSE_RED = (181, 69, 59)

    def __init__(self) -> None:
        self.layout = "vertical"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _gradient_background(self) -> Image.Image:
        w, h = self.SIZE
        img = Image.new("RGB", (w, h))
        draw = ImageDraw.Draw(img)
        for y in range(h):
            t = y / max(h - 1, 1)
            r = int(self.BG_TOP[0] * (1 - t) + self.BG_BOTTOM[0] * t)
            g = int(self.BG_TOP[1] * (1 - t) + self.BG_BOTTOM[1] * t)
            b = int(self.BG_TOP[2] * (1 - t) + self.BG_BOTTOM[2] * t)
            draw.line([(0, y), (w, y)], fill=(r, g, b))
        return img

    def _draw_header(self, draw: ImageDraw.ImageDraw, title: str, date: str) -> None:
        # Top accent bar
        draw.rectangle([0, 0, self.SIZE[0], 8], fill=self.ACCENT)
        # Title
        draw.text((54, 30), title, fill=self.WHITE, font=_font(48, bold=True))
        # Date tag
        if date:
            draw.text((54, 94), date, fill=self.LIGHT_GRAY, font=_font(26))

    def _draw_scoreline(self, draw: ImageDraw.ImageDraw, data: dict[str, Any]) -> int:
        """Draws winner vs loser scoreline. Returns y position after the block."""
        winner = data.get("winner", "胜队")
        loser = data.get("loser", "负队")
        winner_score = str(data.get("winner_score", "—"))
        loser_score = str(data.get("loser_score", "—"))
        headline = data.get("headline", "")

        y_top = 148
        # Panel background
        draw.rounded_rectangle([40, y_top, 1040, y_top + 240], radius=20,
                                fill=self.DARK_PANEL, outline=(60, 60, 90), width=2)

        # Loser side (left)
        draw.text((80, y_top + 24), loser, fill=self.LIGHT_GRAY, font=_font(36, bold=True))
        draw.text((80, y_top + 70), loser_score, fill=self.LOSE_RED, font=_font(100, bold=True))

        # Winner side (right, mirror)
        draw.text((780, y_top + 24), winner, fill=self.WHITE, font=_font(36, bold=True))
        draw.text((760, y_top + 70), winner_score, fill=self.WIN_BLUE, font=_font(100, bold=True))

        # Center divider + FINAL label
        cx = 540
        draw.line([(cx, y_top + 30), (cx, y_top + 190)], fill=(80, 80, 110), width=2)
        draw.text((cx, y_top + 100), "FINAL", fill=self.LIGHT_GRAY,
                  font=_font(28, bold=True), anchor="mm")

        # Headline under scoreline
        if headline:
            draw.text((54, y_top + 210), headline[:32], fill=self.GOLD, font=_font(30))

        return y_top + 260

    def _draw_stats_comparison(self, draw: ImageDraw.ImageDraw,
                                stats: list[dict[str, Any]], y_start: int) -> int:
        """Draws a 2-column stat comparison table. Returns y after block."""
        if not stats:
            return y_start

        row_h = 64
        panel_h = 48 + row_h * len(stats)
        draw.rounded_rectangle([40, y_start, 1040, y_start + panel_h], radius=16,
                                fill=self.DARK_PANEL, outline=(60, 60, 90), width=2)

        # Column headers
        draw.text((200, y_start + 14), "主队", fill=self.LIGHT_GRAY, font=_font(24))
        draw.text((490, y_start + 14), "数据", fill=self.LIGHT_GRAY,
                  font=_font(24), anchor="mm")
        draw.text((840, y_start + 14), "客队", fill=self.LIGHT_GRAY, font=_font(24))

        for i, stat in enumerate(stats[:5]):
            y = y_start + 48 + i * row_h
            # Alternating row tint
            if i % 2 == 0:
                draw.rounded_rectangle([42, y - 4, 1038, y + row_h - 8],
                                       radius=8, fill=(40, 40, 65))
            label = str(stat.get("label", ""))
            winner_val = str(stat.get("winner_val", "—"))
            loser_val = str(stat.get("loser_val", "—"))
            draw.text((490, y + row_h // 2 - 16), label, fill=self.LIGHT_GRAY,
                      font=_font(28), anchor="mm")
            draw.text((240, y + row_h // 2 - 16), winner_val, fill=self.WIN_BLUE,
                      font=_font(32, bold=True), anchor="mm")
            draw.text((840, y + row_h // 2 - 16), loser_val, fill=self.LOSE_RED,
                      font=_font(32, bold=True), anchor="mm")

        return y_start + panel_h + 20

    def _draw_top_player(self, draw: ImageDraw.ImageDraw,
                         player: dict[str, Any], y_start: int) -> int:
        """Draws featured player highlight. Returns y after block."""
        if not player:
            return y_start
        name = str(player.get("name", ""))
        line = str(player.get("line", ""))
        if not name:
            return y_start

        draw.rounded_rectangle([40, y_start, 1040, y_start + 110], radius=16,
                                fill=(50, 20, 30), outline=self.ACCENT, width=2)
        draw.text((80, y_start + 18), "⭐ " + name, fill=self.GOLD, font=_font(38, bold=True))
        draw.text((80, y_start + 64), line, fill=self.WHITE, font=_font(30))
        return y_start + 128

    def _draw_insight(self, draw: ImageDraw.ImageDraw, insight: str, y_start: int) -> int:
        """Draws the key narrative insight. Returns y after block."""
        if not insight:
            return y_start
        draw.rounded_rectangle([40, y_start, 1040, y_start + 90], radius=16,
                                fill=(30, 45, 70), outline=(60, 90, 140), width=2)
        draw.text((80, y_start + 24), "📌 " + insight[:36], fill=self.WHITE, font=_font(30))
        return y_start + 108

    def _draw_footer(self, draw: ImageDraw.ImageDraw, tags: list[str]) -> None:
        draw.rectangle([0, self.SIZE[1] - 60, self.SIZE[0], self.SIZE[1]],
                       fill=(12, 12, 22))
        tag_text = "  ".join(tags[:4]) if tags else "#NBA战报"
        draw.text((54, self.SIZE[1] - 42), tag_text,
                  fill=self.ACCENT, font=_font(24), anchor="lm")
        draw.text((self.SIZE[0] - 54, self.SIZE[1] - 42), "AI战报",
                  fill=self.GOLD, font=_font(24), anchor="rm")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(self, narrative_data: dict[str, Any], output_path: str) -> str:
        """Render the infographic and save to *output_path*.

        Expected keys in *narrative_data* (all optional with sensible fallbacks):
            title (str)           — e.g. "GSW vs LAL"
            headline (str)        — punchy one-liner
            winner (str)          — winning team display name
            loser (str)           — losing team display name
            winner_score (int)    — winning score
            loser_score (int)     — losing score
            date (str)            — display date string
            stats (list[dict])    — list of {label, winner_val, loser_val}
            top_player (dict)     — {name, line}
            insight (str)         — key narrative insight
            tags (list[str])      — hashtags for footer
        """
        img = self._gradient_background()
        draw = ImageDraw.Draw(img)

        title = str(narrative_data.get("title", "NBA 战报"))
        date = str(narrative_data.get("date", ""))
        stats: list[dict] = narrative_data.get("stats", [])
        top_player: dict = narrative_data.get("top_player", {})
        insight = str(narrative_data.get("insight", ""))
        tags: list[str] = narrative_data.get("tags", ["#NBA"])

        self._draw_header(draw, title, date)
        y = self._draw_scoreline(draw, narrative_data)
        y += 16
        y = self._draw_stats_comparison(draw, stats, y)
        y = self._draw_top_player(draw, top_player, y)
        y = self._draw_insight(draw, insight, y)
        self._draw_footer(draw, tags)

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        img.save(out, format="PNG")
        return str(out)

    def main(self, narrative_data: dict) -> str:
        output_file = Path("infographic.png").as_posix()
        return self.generate(narrative_data, output_file)
