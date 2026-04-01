from __future__ import annotations

from pathlib import Path

from PIL import Image
from PIL import ImageDraw
from PIL import ImageFont

from core.models import NBAPostgameData


TEAM_NAME_MAP = {
    "ATL": "老鹰",
    "BOS": "凯尔特人",
    "BKN": "篮网",
    "CHA": "黄蜂",
    "CHI": "公牛",
    "CLE": "骑士",
    "DAL": "独行侠",
    "DEN": "掘金",
    "DET": "活塞",
    "GSW": "勇士",
    "HOU": "火箭",
    "IND": "步行者",
    "LAC": "快船",
    "LAL": "湖人",
    "MEM": "灰熊",
    "MIA": "热火",
    "MIL": "雄鹿",
    "MIN": "森林狼",
    "NOP": "鹈鹕",
    "NYK": "尼克斯",
    "OKC": "雷霆",
    "ORL": "魔术",
    "PHI": "76人",
    "PHX": "太阳",
    "POR": "开拓者",
    "SAC": "国王",
    "SAS": "马刺",
    "TOR": "猛龙",
    "UTA": "爵士",
    "WAS": "奇才",
}


def _team_name(short_name: str, fallback: str) -> str:
    return TEAM_NAME_MAP.get(short_name, fallback)


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = []
    if bold:
        candidates.extend(
            [
                "C:/Windows/Fonts/msyhbd.ttc",
                "C:/Windows/Fonts/simhei.ttf",
            ]
        )
    candidates.extend(
        [
            "C:/Windows/Fonts/msyh.ttc",
            "C:/Windows/Fonts/simhei.ttf",
        ]
    )
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def create_postgame_poster(game: NBAPostgameData, headline: str, output_path: str) -> str:
    width, height = 1080, 1440
    image = Image.new("RGB", (width, height), "#f4efe2")
    draw = ImageDraw.Draw(image)

    for y in range(height):
        ratio = y / max(1, height - 1)
        color = (
            int(244 * (1 - ratio) + 214 * ratio),
            int(239 * (1 - ratio) + 223 * ratio),
            int(226 * (1 - ratio) + 237 * ratio),
        )
        draw.line([(0, y), (width, y)], fill=color)

    draw.rectangle([60, 60, width - 60, height - 60], outline="#1c1c1c", width=3)
    draw.rectangle([80, 80, width - 80, 270], fill="#111111")
    draw.text((110, 110), "POSTGAME CONTROL ROOM", fill="#f6f2e8", font=_font(34, bold=True))
    draw.text((110, 170), headline, fill="#f6f2e8", font=_font(58, bold=True))

    winner = game.home_team if game.home_team.score >= game.away_team.score else game.away_team
    loser = game.away_team if winner is game.home_team else game.home_team
    winner_name = _team_name(winner.short_name, winner.name)
    loser_name = _team_name(loser.short_name, loser.name)

    draw.rounded_rectangle([90, 330, 990, 570], radius=28, fill="#f9f6ef", outline="#1b1b1b", width=3)
    draw.text((125, 360), loser_name, fill="#111111", font=_font(44, bold=True))
    draw.text((125, 430), str(loser.score), fill="#b5453b", font=_font(94, bold=True))
    draw.text((660, 360), winner_name, fill="#111111", font=_font(44, bold=True))
    draw.text((660, 430), str(winner.score), fill="#1f4b8f", font=_font(94, bold=True))

    draw.text((495, 420), "FINAL", fill="#111111", font=_font(30, bold=True))
    draw.text((430, 500), game.venue, fill="#4a4a4a", font=_font(26))

    draw.rounded_rectangle([90, 620, 990, 980], radius=28, fill="#ffffff", outline="#1b1b1b", width=3)
    draw.text((120, 655), "WHY THEY WON", fill="#111111", font=_font(34, bold=True))
    bullet_y = 720
    takeaways = list(getattr(game.analysis, "key_takeaways", [])[:3]) or ["比赛内容已生成。"]
    for takeaway in takeaways:
        draw.ellipse([125, bullet_y + 12, 141, bullet_y + 28], fill="#b5453b")
        draw.text((160, bullet_y), takeaway, fill="#222222", font=_font(28))
        bullet_y += 84

    draw.rounded_rectangle([90, 1030, 990, 1330], radius=28, fill="#111111", outline="#111111", width=2)
    draw.text((120, 1065), "STAR LINES", fill="#f4efe2", font=_font(34, bold=True))
    player_y = 1130
    for player in game.top_players[:2]:
        line = f"{player.name}  {player.points}分 {player.rebounds}板 {player.assists}助"
        draw.text((120, player_y), line, fill="#f4efe2", font=_font(30))
        player_y += 72

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG")
    return str(output)
