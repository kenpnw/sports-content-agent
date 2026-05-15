"""Reconcile visual score-change events against official NBA PBP scoring.

The reconciler is the bridge between the new visual evidence chain and the
existing PBP truth source. It does not mutate court reports or demo artifacts;
it writes a standalone JSON report for analysis and thesis evidence.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


REGULATION_PERIOD_SECONDS = 720.0
MATCH_WINDOW_SECONDS = 10.0
STRATEGY_WINDOWS = {
    "A": 10.0,
    "B": 20.0,
    "C": 30.0,
    "D": 15.0,
}


@dataclass
class ReconciledScoreEvent:
    """One visual score event with its best PBP match, if any."""

    visual: dict[str, Any]
    pbp_match: dict[str, Any] | None
    match_confidence: float
    mismatch_reason: str
    strategy_used: str = "unmatched"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def reconcile_score_events(
    *,
    score_events_path: str | Path,
    replay_path: str | Path,
    time_map_path: str | Path,
) -> dict[str, Any]:
    """Load visual score events, map PBP scoring events, and reconcile them."""
    score_payload = _load_json(score_events_path)
    replay = _load_json(replay_path)
    time_map = _load_json(time_map_path)
    visual_events = [item for item in score_payload.get("events", []) if isinstance(item, dict)]
    pbp_events = _extract_pbp_scoring_events(replay, time_map)
    matched_pbp_ids: set[str] = set()
    reconciled: list[ReconciledScoreEvent] = []
    matched_by_strategy = {"A": 0, "B": 0, "C": 0, "D": 0}

    for visual in visual_events:
        match, confidence, reason, strategy, consumed_ids = _match_visual_event(visual, pbp_events, matched_pbp_ids)
        if match:
            matched_pbp_ids.update(consumed_ids)
            if strategy in matched_by_strategy:
                matched_by_strategy[strategy] += 1
        reconciled.append(
            ReconciledScoreEvent(
                visual=visual,
                pbp_match=match,
                match_confidence=confidence,
                mismatch_reason=reason,
                strategy_used=strategy,
            )
        )

    pbp_only = [event for event in pbp_events if str(event.get("actionId", "")) not in matched_pbp_ids]
    matched = sum(1 for item in reconciled if item.pbp_match is not None)
    visual_only = len(reconciled) - matched
    return {
        "score_events_path": str(score_events_path),
        "replay_path": str(replay_path),
        "time_map_path": str(time_map_path),
        "home_team": replay.get("home_team", score_payload.get("home_team", "HOME")),
        "away_team": replay.get("away_team", score_payload.get("away_team", "AWAY")),
        "total_visual_events": len(visual_events),
        "total_pbp_scoring_events": len(pbp_events),
        "matched": matched,
        "visual_only": visual_only,
        "pbp_only": len(pbp_only),
        "match_rate": round(matched / len(pbp_events), 4) if pbp_events else 0.0,
        "matched_by_strategy": matched_by_strategy,
        "events": [item.to_dict() for item in reconciled],
        "pbp_only_events": pbp_only,
        "stats": {
            "total_visual_events": len(visual_events),
            "total_pbp_scoring_events": len(pbp_events),
            "matched": matched,
            "visual_only": visual_only,
            "pbp_only": len(pbp_only),
            "match_rate": round(matched / len(pbp_events), 4) if pbp_events else 0.0,
            "matched_by_strategy": matched_by_strategy,
        },
    }


def _extract_pbp_scoring_events(replay: dict[str, Any], time_map: dict[str, Any]) -> list[dict[str, Any]]:
    home_team = str(replay.get("home_team", ""))
    away_team = str(replay.get("away_team", ""))
    events: list[dict[str, Any]] = []
    for event in replay.get("events", []):
        if not isinstance(event, dict):
            continue
        points = _scoring_points(event)
        if points <= 0:
            continue
        period = _safe_int(event.get("period"))
        clock_remaining = _clock_to_seconds(str(event.get("clock", "")))
        if period <= 0 or clock_remaining is None:
            continue
        team_code = str(event.get("teamTricode", ""))
        team_side = "HOME" if team_code == home_team else "AWAY" if team_code == away_team else ""
        if not team_side:
            continue
        mapped_seconds = _map_pbp_to_video_seconds(period, clock_remaining, time_map)
        enriched = dict(event)
        enriched.update(
            {
                "points_delta": int(points),
                "team_side": team_side,
                "mapped_video_seconds": round(float(mapped_seconds), 3) if mapped_seconds is not None else None,
                "game_seconds": round(_game_seconds(period, clock_remaining), 3),
            }
        )
        events.append(enriched)
    events.sort(key=lambda item: float(item.get("mapped_video_seconds") or math.inf))
    return events


def _match_visual_event(
    visual: dict[str, Any],
    pbp_events: list[dict[str, Any]],
    matched_pbp_ids: set[str],
) -> tuple[dict[str, Any] | None, float, str, str, set[str]]:
    try:
        visual_seconds = float(visual.get("video_seconds"))
        visual_team = str(visual.get("team", ""))
        visual_points = int(visual.get("points_delta", 0))
    except (TypeError, ValueError):
        return None, 0.0, "invalid_visual_event", "unmatched", set()

    for strategy, window, delta_tolerance, require_delta in [
        ("A", 10.0, 0, True),
        ("B", 20.0, 1, True),
        ("C", 30.0, 0, False),
    ]:
        match = _best_single_event_match(
            visual_seconds=visual_seconds,
            visual_team=visual_team,
            visual_points=visual_points,
            pbp_events=pbp_events,
            matched_pbp_ids=matched_pbp_ids,
            window_seconds=window,
            delta_tolerance=delta_tolerance,
            require_delta=require_delta,
        )
        if match is not None:
            delta, event = match
            confidence = _strategy_confidence(delta, window, strategy)
            return event, confidence, "", strategy, {str(event.get("actionId", ""))}

    aggregate = _best_aggregate_match(
        visual_seconds=visual_seconds,
        visual_team=visual_team,
        visual_points=visual_points,
        pbp_events=pbp_events,
        matched_pbp_ids=matched_pbp_ids,
        window_seconds=STRATEGY_WINDOWS["D"],
    )
    if aggregate is not None:
        delta, events = aggregate
        payload = _aggregate_match_payload(events, visual_points=visual_points)
        confidence = _strategy_confidence(delta, STRATEGY_WINDOWS["D"], "D")
        consumed = {str(event.get("actionId", "")) for event in events}
        return payload, confidence, "", "D", consumed

    return None, 0.0, _nearest_mismatch_reason(visual, pbp_events, matched_pbp_ids), "unmatched", set()


def _best_single_event_match(
    *,
    visual_seconds: float,
    visual_team: str,
    visual_points: int,
    pbp_events: list[dict[str, Any]],
    matched_pbp_ids: set[str],
    window_seconds: float,
    delta_tolerance: int,
    require_delta: bool,
) -> tuple[float, dict[str, Any]] | None:
    candidates: list[tuple[float, int, dict[str, Any]]] = []
    for event in pbp_events:
        action_id = str(event.get("actionId", ""))
        if action_id in matched_pbp_ids:
            continue
        mapped = event.get("mapped_video_seconds")
        if mapped is None:
            continue
        if str(event.get("team_side", "")) != visual_team:
            continue
        event_points = int(event.get("points_delta", 0) or 0)
        point_gap = abs(event_points - visual_points)
        if require_delta and point_gap > int(delta_tolerance):
            continue
        delta = abs(float(mapped) - visual_seconds)
        if delta <= float(window_seconds):
            candidates.append((delta, point_gap, event))
    if not candidates:
        return None
    delta, _point_gap, event = min(candidates, key=lambda item: (item[0], item[1]))
    return delta, event


def _best_aggregate_match(
    *,
    visual_seconds: float,
    visual_team: str,
    visual_points: int,
    pbp_events: list[dict[str, Any]],
    matched_pbp_ids: set[str],
    window_seconds: float,
) -> tuple[float, list[dict[str, Any]]] | None:
    window_events = [
        event
        for event in pbp_events
        if str(event.get("actionId", "")) not in matched_pbp_ids
        and event.get("mapped_video_seconds") is not None
        and str(event.get("team_side", "")) == visual_team
        and abs(float(event.get("mapped_video_seconds")) - visual_seconds) <= float(window_seconds)
    ]
    if len(window_events) < 2:
        return None
    best: tuple[float, list[dict[str, Any]]] | None = None
    count = len(window_events)
    for start in range(count):
        total = 0
        selected: list[dict[str, Any]] = []
        for event in window_events[start:]:
            total += int(event.get("points_delta", 0) or 0)
            selected.append(event)
            if total == visual_points and len(selected) >= 2:
                avg_delta = sum(abs(float(item.get("mapped_video_seconds")) - visual_seconds) for item in selected) / len(selected)
                if best is None or avg_delta < best[0]:
                    best = (avg_delta, list(selected))
                break
            if total > visual_points:
                break
    return best


def _aggregate_match_payload(events: list[dict[str, Any]], *, visual_points: int) -> dict[str, Any]:
    first = dict(events[0])
    first["actionId"] = "+".join(str(event.get("actionId", "")) for event in events)
    first["description"] = " + ".join(str(event.get("description", "")) for event in events)
    first["playerNameI"] = ", ".join(str(event.get("playerNameI", "")) for event in events if event.get("playerNameI"))
    first["points_delta"] = int(visual_points)
    first["accumulated_delta"] = int(visual_points)
    first["aggregated_event_count"] = len(events)
    first["aggregated_events"] = events
    first["mapped_video_seconds"] = round(
        sum(float(event.get("mapped_video_seconds")) for event in events) / len(events),
        3,
    )
    return first


def _strategy_confidence(delta_seconds: float, window_seconds: float, strategy: str) -> float:
    base = {"A": 1.0, "B": 0.86, "C": 0.72, "D": 0.8}.get(strategy, 0.5)
    penalty = min(0.5, (float(delta_seconds) / max(1.0, float(window_seconds))) * 0.5)
    return round(max(0.0, base - penalty), 4)


def _nearest_mismatch_reason(visual: dict[str, Any], pbp_events: list[dict[str, Any]], matched_pbp_ids: set[str]) -> str:
    try:
        visual_seconds = float(visual.get("video_seconds"))
    except (TypeError, ValueError):
        return "invalid_visual_timestamp"
    nearest = [
        abs(float(event.get("mapped_video_seconds")) - visual_seconds)
        for event in pbp_events
        if event.get("mapped_video_seconds") is not None and str(event.get("actionId", "")) not in matched_pbp_ids
    ]
    if not nearest:
        return "no_unmatched_pbp_events"
    best = min(nearest)
    if best > MATCH_WINDOW_SECONDS:
        return f"no_pbp_score_within_{MATCH_WINDOW_SECONDS:.0f}s"
    return "nearby_pbp_team_or_points_mismatch"


def _map_pbp_to_video_seconds(period: int, clock_remaining: float, time_map: dict[str, Any]) -> float | None:
    sample_estimate = _estimate_from_time_map_samples(period, clock_remaining, time_map.get("samples", []))
    if sample_estimate is not None:
        return sample_estimate
    anchors = time_map.get("period_anchors", {})
    anchor = anchors.get(str(period), anchors.get(period))
    if anchor is None:
        return None
    return float(anchor) + (float(_period_length(period)) - float(clock_remaining))


def _estimate_from_time_map_samples(period: int, target_clock_remaining: float, samples: list[Any]) -> float | None:
    valid: list[dict[str, float]] = []
    for sample in samples:
        if not isinstance(sample, dict):
            continue
        try:
            if int(sample.get("period")) != int(period) or bool(sample.get("is_outlier", False)):
                continue
            valid.append(
                {
                    "clock": float(sample.get("clock_remaining_seconds")),
                    "video": float(sample.get("video_seconds")),
                }
            )
        except (TypeError, ValueError):
            continue
    if not valid:
        return None
    above = [item for item in valid if item["clock"] >= target_clock_remaining]
    below = [item for item in valid if item["clock"] <= target_clock_remaining]
    high = min(above, key=lambda item: abs(item["clock"] - target_clock_remaining)) if above else None
    low = min(below, key=lambda item: abs(item["clock"] - target_clock_remaining)) if below else None
    if high and low and abs(high["clock"] - low["clock"]) > 1e-6:
        ratio = (target_clock_remaining - high["clock"]) / (low["clock"] - high["clock"])
        return high["video"] + ratio * (low["video"] - high["video"])
    nearest = min(valid, key=lambda item: abs(item["clock"] - target_clock_remaining))
    return nearest["video"]


def _scoring_points(event: dict[str, Any]) -> int:
    action_type = str(event.get("actionType", "")).lower()
    shot_result = str(event.get("shotResult", "")).lower()
    if shot_result != "made":
        return 0
    if "freethrow" in action_type or str(event.get("subType", "")).lower() == "free throw":
        return 1
    return int(event.get("shotValue", 0) or 0)


def _game_seconds(period: int, clock_remaining: float) -> float:
    return (int(period) - 1) * REGULATION_PERIOD_SECONDS + (_period_length(period) - float(clock_remaining))


def _period_length(period: int) -> float:
    return 300.0 if int(period) > 4 else REGULATION_PERIOD_SECONDS


def _clock_to_seconds(value: str) -> float | None:
    text = str(value or "").strip().upper()
    if text.startswith("PT"):
        minutes = _regex_int(text, r"(\d+)M")
        seconds = _regex_float(text, r"(\d+(?:\.\d+)?)S")
        return float(minutes * 60) + float(seconds)
    parts = text.replace(".", ":").split(":")
    if len(parts) >= 2:
        try:
            return int(parts[0]) * 60 + float(parts[1])
        except ValueError:
            return None
    return None


def _regex_int(text: str, pattern: str) -> int:
    import re

    match = re.search(pattern, text)
    return int(match.group(1)) if match else 0


def _regex_float(text: str, pattern: str) -> float:
    import re

    match = re.search(pattern, text)
    return float(match.group(1)) if match else 0.0


def _safe_int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_reconciliation_report(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reconcile visual score changes with official PBP scoring events.")
    parser.add_argument("--score-events", required=False, default="", help="score_events.json from scoreboard_score_tracker.")
    parser.add_argument("--replay", required=False, default="", help="Normalized NBA replay/PBP JSON.")
    parser.add_argument("--time-map", required=False, default="", help="video_time_map.json.")
    parser.add_argument("--output", default="", help="Output reconciliation_report.json path.")
    parser.add_argument("--self-test", action="store_true", help="Run a synthetic reconciliation self-test.")
    return parser.parse_args()


def _self_test() -> None:
    event = {"period": 1, "clock": "PT11M30.00S", "teamTricode": "OKC", "shotResult": "Made", "shotValue": 3}
    replay = {"home_team": "OKC", "away_team": "LAL", "events": [event]}
    time_map = {"period_anchors": {"1": 100.0}, "samples": []}
    mapped = _extract_pbp_scoring_events(replay, time_map)
    assert mapped[0]["mapped_video_seconds"] == 130.0
    assert mapped[0]["points_delta"] == 3
    print("pbp_score_reconciler self-test passed.")


def main() -> None:
    args = parse_args()
    if args.self_test:
        _self_test()
        return
    if not args.score_events or not args.replay or not args.time_map:
        raise SystemExit("--score-events, --replay, and --time-map are required unless --self-test is used.")
    payload = reconcile_score_events(score_events_path=args.score_events, replay_path=args.replay, time_map_path=args.time_map)
    output = Path(args.output) if args.output else Path(args.score_events).with_name("reconciliation_report.json")
    save_reconciliation_report(output, payload)
    print(json.dumps(payload["stats"], ensure_ascii=False, indent=2))
    print(f"Reconciliation report saved to: {output.resolve()}")


if __name__ == "__main__":
    main()
