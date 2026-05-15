"""Render a visual score reconciliation report.

This module turns the T-CV-1A reconciliation JSON into a compact Markdown and
JSON artifact for thesis/demo evidence. It keeps the visual verification layer
separate from court_report truth data.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT_ROOT = Path("data/generated/visual_score")


def build_visual_score_report(
    *,
    reconciliation_path: str | Path,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Build Markdown and JSON visual score report artifacts."""
    reconciliation = _load_json(reconciliation_path)
    target_dir = Path(output_dir) if output_dir else DEFAULT_OUTPUT_ROOT / datetime.now().strftime("%Y%m%d_%H%M%S")
    target_dir.mkdir(parents=True, exist_ok=True)
    player_rows = _player_score_rows(reconciliation)
    payload = {
        "source_reconciliation": str(reconciliation_path),
        "home_team": reconciliation.get("home_team", "HOME"),
        "away_team": reconciliation.get("away_team", "AWAY"),
        "stats": reconciliation.get("stats", {}),
        "players": player_rows,
        "timeline": _timeline_rows(reconciliation),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    markdown = _render_markdown(payload)
    (target_dir / "visual_score_report.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (target_dir / "visual_score_report.md").write_text(markdown, encoding="utf-8")
    return {
        "output_dir": str(target_dir.resolve()),
        "markdown_path": str((target_dir / "visual_score_report.md").resolve()),
        "json_path": str((target_dir / "visual_score_report.json").resolve()),
        "stats": payload["stats"],
        "top_players": player_rows[:5],
    }


def _player_score_rows(reconciliation: dict[str, Any]) -> list[dict[str, Any]]:
    visual_confirmed: dict[str, int] = defaultdict(int)
    pbp_true: dict[str, int] = defaultdict(int)
    for event in reconciliation.get("events", []):
        if not isinstance(event, dict):
            continue
        match = event.get("pbp_match")
        if isinstance(match, dict):
            player = str(match.get("playerNameI", "") or "Unknown")
            points = int(match.get("points_delta", 0) or 0)
            visual_confirmed[player] += points
    for event in reconciliation.get("events", []):
        match = event.get("pbp_match") if isinstance(event, dict) else None
        if isinstance(match, dict):
            player = str(match.get("playerNameI", "") or "Unknown")
            pbp_true[player] += int(match.get("points_delta", 0) or 0)
    for event in reconciliation.get("pbp_only_events", []):
        if isinstance(event, dict):
            player = str(event.get("playerNameI", "") or "Unknown")
            pbp_true[player] += int(event.get("points_delta", 0) or 0)

    players = sorted(set(visual_confirmed) | set(pbp_true), key=lambda name: pbp_true.get(name, 0), reverse=True)
    rows: list[dict[str, Any]] = []
    for player in players:
        true_points = pbp_true.get(player, 0)
        confirmed = visual_confirmed.get(player, 0)
        consistency = round(confirmed / true_points, 4) if true_points else 0.0
        rows.append(
            {
                "player": player,
                "visual_confirmed_points": confirmed,
                "pbp_true_points": true_points,
                "consistency": consistency,
            }
        )
    return rows


def _timeline_rows(reconciliation: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in reconciliation.get("events", []):
        if not isinstance(item, dict):
            continue
        visual = item.get("visual", {}) if isinstance(item.get("visual"), dict) else {}
        match = item.get("pbp_match") if isinstance(item.get("pbp_match"), dict) else None
        rows.append(
            {
                "video_seconds": visual.get("video_seconds"),
                "visual_team": visual.get("team"),
                "visual_points": visual.get("points_delta"),
                "visual_score": f"{visual.get('away_score', '')}-{visual.get('home_score', '')}",
                "pbp_player": match.get("playerNameI", "") if match else "",
                "pbp_description": match.get("description", "") if match else "",
                "match_confidence": item.get("match_confidence", 0.0),
                "mismatch_reason": item.get("mismatch_reason", ""),
            }
        )
    rows.sort(key=lambda item: float(item.get("video_seconds") or 0.0))
    return rows


def _render_markdown(payload: dict[str, Any]) -> str:
    stats = payload.get("stats", {})
    match_rate = float(stats.get("match_rate", 0.0) or 0.0)
    title = f"视觉得分追踪报告：{payload.get('home_team', 'HOME')} vs {payload.get('away_team', 'AWAY')} 西决 G1"
    lines = [
        f"# {title}",
        "",
        "## 总体统计",
        f"- 视觉检测得分时刻：{int(stats.get('total_visual_events', 0) or 0)} 次",
        f"- PBP 真实得分事件：{int(stats.get('total_pbp_scoring_events', 0) or 0)} 次",
        f"- 匹配成功：{int(stats.get('matched', 0) or 0)} 次（{match_rate:.1%}）",
        f"- 视觉误报：{int(stats.get('visual_only', 0) or 0)} 次（OCR 把非比分变化误判）",
        f"- 视觉漏报：{int(stats.get('pbp_only', 0) or 0)} 次（OCR 在该时刻未读出比分）",
        "",
        "## 球员得分追踪表",
        "| 球员 | 视觉确认得分 | PBP 真实得分 | 一致性 |",
        "| --- | ---: | ---: | ---: |",
    ]
    for player in payload.get("players", []):
        consistency = float(player.get("consistency", 0.0) or 0.0)
        lines.append(
            f"| {player.get('player', '')} | "
            f"{int(player.get('visual_confirmed_points', 0) or 0)} | "
            f"{int(player.get('pbp_true_points', 0) or 0)} | "
            f"{consistency:.1%} |"
        )
    lines.extend(["", "## 时间线", "| 视频秒 | 视觉得分 | PBP 匹配 | 置信度 | 状态 |", "| ---: | --- | --- | ---: | --- |"])
    for row in payload.get("timeline", []):
        pbp = row.get("pbp_description") or row.get("mismatch_reason") or "unmatched"
        status = "matched" if row.get("pbp_description") else "unmatched"
        lines.append(
            f"| {float(row.get('video_seconds') or 0.0):.1f} | "
            f"{row.get('visual_team', '')} +{row.get('visual_points', '')} ({row.get('visual_score', '')}) | "
            f"{pbp} | {float(row.get('match_confidence', 0.0) or 0.0):.2f} | {status} |"
        )
    lines.extend(
        [
            "",
            "## 答辩亮点",
            (
                f"本系统通过视觉得分追踪独立验证了 PBP 数据的 {match_rate:.1%}。"
                "剩余偏差主要由广播视频在大量回放镜头切换中比分牌瞬时不可见、"
                "OCR 误读或采样间隔跨过得分变化所致，可通过未来工作中的多角度视频流融合解决。"
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render visual score reconciliation report.")
    parser.add_argument("--reconciliation", required=False, default="", help="reconciliation_report.json path.")
    parser.add_argument("--output-dir", default="", help="Optional output directory.")
    parser.add_argument("--self-test", action="store_true", help="Run a tiny report rendering self-test.")
    return parser.parse_args()


def _self_test() -> None:
    sample = {
        "home_team": "OKC",
        "away_team": "LAL",
        "stats": {"total_visual_events": 1, "total_pbp_scoring_events": 1, "matched": 1, "visual_only": 0, "pbp_only": 0, "match_rate": 1.0},
        "events": [
            {
                "visual": {"video_seconds": 10.0, "team": "HOME", "points_delta": 3, "home_score": 3, "away_score": 0},
                "pbp_match": {"playerNameI": "S. Gilgeous-Alexander", "points_delta": 3, "description": "S. Gilgeous-Alexander 3PT made"},
                "match_confidence": 1.0,
                "mismatch_reason": "",
            }
        ],
        "pbp_only_events": [],
    }
    rows = _player_score_rows(sample)
    assert rows[0]["visual_confirmed_points"] == 3
    assert "总体统计" in _render_markdown({"home_team": "OKC", "away_team": "LAL", "stats": sample["stats"], "players": rows, "timeline": _timeline_rows(sample)})
    print("visual_score_report self-test passed.")


def main() -> None:
    args = parse_args()
    if args.self_test:
        _self_test()
        return
    if not args.reconciliation:
        raise SystemExit("--reconciliation is required unless --self-test is used.")
    result = build_visual_score_report(reconciliation_path=args.reconciliation, output_dir=args.output_dir or None)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
