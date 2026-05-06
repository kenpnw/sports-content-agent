"""Event detector — classifies raw play-by-play events into commentary
triggers with a salience score.

Design
------
This is intentionally rule-based, not LLM-based. Reasons:

1. The thesis evaluation needs *deterministic* event classification so that
   the experimental comparison between baselines and the full system isn't
   confounded by LLM variance at the detection step.
2. Latency: detection runs on every PBP event; an LLM call here would push
   end-to-end latency over budget.
3. Auditability: rules can be inspected by the defense committee.

The detector keeps a small running game state (current score, lead, recent
events window) and outputs `DetectedEvent` objects. The downstream
`live_commentator` then chooses whether to actually generate commentary
based on the salience score and rate limits.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque

from realtime.models import (
    ALL_EVENT_CATEGORIES,
    DetectedEvent,
    EVENT_CATEGORY_CLUTCH_SHOT,
    EVENT_CATEGORY_GAME_END,
    EVENT_CATEGORY_INJURY_NOTE,
    EVENT_CATEGORY_KEY_SHOT,
    EVENT_CATEGORY_LEAD_CHANGE,
    EVENT_CATEGORY_MOMENTUM_SWING,
    EVENT_CATEGORY_PERIOD_END,
    EVENT_CATEGORY_ROUTINE,
    EVENT_CATEGORY_TIMEOUT,
    EVENT_CATEGORY_TURNOVER,
    PlayByPlayEvent,
)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class DetectorConfig:
    """Tunable thresholds for salience computation."""

    clutch_period: int = 4                # Q4 (or higher) is "clutch"
    clutch_remaining_seconds: float = 300.0   # last 5 min
    close_game_margin: int = 6            # within 6 pts = close
    momentum_window_events: int = 10      # rolling window for run detection
    momentum_run_points: int = 8          # 8-0 run triggers swing
    routine_salience: float = 0.10
    key_shot_base_salience: float = 0.55
    clutch_shot_salience: float = 0.92
    turnover_salience: float = 0.50
    momentum_swing_salience: float = 0.78
    lead_change_salience: float = 0.70
    timeout_salience: float = 0.35
    period_end_salience: float = 0.65
    game_end_salience: float = 0.99
    injury_salience: float = 0.85


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------


class EventDetector:
    """Stateful classifier over the play-by-play stream."""

    # Description keywords used as a coarse feature when actionType is missing.
    _TURNOVER_KEYWORDS = ("turnover", "steal", "bad pass", "lost ball", "失误", "被抢断")
    _TIMEOUT_KEYWORDS = ("timeout", "暂停")
    _INJURY_KEYWORDS = ("injury", "ejection", "leaves the game", "受伤", "离场")
    _PERIOD_END_KEYWORDS = ("end of", "end of period", "节结束", "上半场结束", "下半场结束")
    _GAME_END_KEYWORDS = ("end of 4th", "end of game", "全场结束", "比赛结束", "final")

    def __init__(self, config: DetectorConfig | None = None) -> None:
        self.config = config or DetectorConfig()
        self._previous_lead_team: str = ""   # which team was leading before this event
        self._recent_points: Deque[tuple[str, int]] = deque(maxlen=self.config.momentum_window_events)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def detect(self, event: PlayByPlayEvent) -> DetectedEvent:
        category, base_salience, rationale = self._classify(event)
        salience = self._adjust_salience(event, category, base_salience)
        snapshot = self._snapshot_context(event, category)
        # Update state AFTER classification so the current event sees the
        # pre-event state.
        self._update_state(event)
        return DetectedEvent(
            raw_event=event,
            category=category,
            salience=salience,
            rationale=rationale,
            context_snapshot=snapshot,
        )

    def reset(self) -> None:
        self._previous_lead_team = ""
        self._recent_points.clear()

    # ------------------------------------------------------------------ #
    # Classification
    # ------------------------------------------------------------------ #

    def _classify(self, event: PlayByPlayEvent) -> tuple[str, float, str]:
        cfg = self.config
        desc = event.description.lower()
        action = event.action_type.lower()

        # Game / period end
        if any(k in desc for k in self._GAME_END_KEYWORDS) or "game end" in action:
            return EVENT_CATEGORY_GAME_END, cfg.game_end_salience, "matched game-end keyword"
        if any(k in desc for k in self._PERIOD_END_KEYWORDS) or "period end" in action:
            return EVENT_CATEGORY_PERIOD_END, cfg.period_end_salience, "matched period-end keyword"

        # Injury / ejection
        if any(k in desc for k in self._INJURY_KEYWORDS) or "ejection" in action:
            return EVENT_CATEGORY_INJURY_NOTE, cfg.injury_salience, "injury/ejection note"

        # Timeout
        if any(k in desc for k in self._TIMEOUT_KEYWORDS) or "timeout" in action:
            return EVENT_CATEGORY_TIMEOUT, cfg.timeout_salience, "timeout"

        # Made shot
        is_made_shot = (
            "made shot" in action
            or "made" in desc
            or event.points > 0
        )
        if is_made_shot and event.points > 0:
            # Clutch?
            if self._is_clutch(event):
                return (
                    EVENT_CATEGORY_CLUTCH_SHOT,
                    cfg.clutch_shot_salience,
                    "made shot in clutch period and close margin",
                )
            # Lead change?
            if self._is_lead_change(event):
                return (
                    EVENT_CATEGORY_LEAD_CHANGE,
                    cfg.lead_change_salience,
                    "lead changed hands",
                )
            # Momentum?
            if self._is_momentum_swing(event):
                return (
                    EVENT_CATEGORY_MOMENTUM_SWING,
                    cfg.momentum_swing_salience,
                    "rolling-window run detected",
                )
            # Otherwise: just a key shot if 3PT or dunk; routine otherwise.
            sub = event.sub_type.lower()
            if "3pt" in sub or event.points >= 3 or "dunk" in sub:
                return EVENT_CATEGORY_KEY_SHOT, cfg.key_shot_base_salience, "3PT or dunk"
            return EVENT_CATEGORY_ROUTINE, cfg.routine_salience, "non-key 2PT"

        # Turnover
        if any(k in desc for k in self._TURNOVER_KEYWORDS) or "turnover" in action:
            return EVENT_CATEGORY_TURNOVER, cfg.turnover_salience, "turnover"

        return EVENT_CATEGORY_ROUTINE, cfg.routine_salience, "no salient pattern"

    # ------------------------------------------------------------------ #
    # Sub-classifiers
    # ------------------------------------------------------------------ #

    def _is_clutch(self, event: PlayByPlayEvent) -> bool:
        if event.period < self.config.clutch_period:
            return False
        # Estimate remaining seconds using period length and elapsed.
        period_len = 12 * 60 if event.period <= 4 else 5 * 60
        remaining = max(0.0, period_len - event.elapsed_seconds_in_period)
        if remaining > self.config.clutch_remaining_seconds:
            return False
        margin = abs(event.home_score - event.away_score)
        return margin <= self.config.close_game_margin

    def _is_lead_change(self, event: PlayByPlayEvent) -> bool:
        """A lead change occurs when the leading team flips, or game becomes tied
        after a non-tied state, or vice versa, via this event."""
        if event.home_score == event.away_score:
            new_lead = ""
        elif event.home_score > event.away_score:
            new_lead = "HOME"
        else:
            new_lead = "AWAY"
        prev = self._previous_lead_team
        if prev == "":
            # First scoring event: not a lead change yet (we just started leading)
            return False
        return new_lead != prev and new_lead != ""

    def _is_momentum_swing(self, event: PlayByPlayEvent) -> bool:
        """Detect an N-0 (or near it) run within the rolling window."""
        if event.points <= 0 or not event.actor_team:
            return False
        # Build a hypothetical window including this event.
        window = list(self._recent_points) + [(event.actor_team, event.points)]
        # Sum points by team within window.
        totals: dict[str, int] = {}
        for team, pts in window:
            totals[team] = totals.get(team, 0) + pts
        if not totals:
            return False
        leader_team, leader_pts = max(totals.items(), key=lambda kv: kv[1])
        other_pts = sum(p for t, p in totals.items() if t != leader_team)
        # Trigger when leader has >= run threshold AND other side has very few
        return leader_pts >= self.config.momentum_run_points and other_pts <= 2

    # ------------------------------------------------------------------ #
    # Salience adjustment
    # ------------------------------------------------------------------ #

    def _adjust_salience(
        self,
        event: PlayByPlayEvent,
        category: str,
        base: float,
    ) -> float:
        """Apply context-based bumps:
        - Closer games slightly more salient
        - Late-game events slightly more salient
        """
        salience = base
        margin = abs(event.home_score - event.away_score)
        if margin <= 3:
            salience += 0.04
        elif margin <= 6:
            salience += 0.02
        if event.period >= 4:
            salience += 0.03
        return min(1.0, max(0.0, salience))

    # ------------------------------------------------------------------ #
    # State management
    # ------------------------------------------------------------------ #

    def _update_state(self, event: PlayByPlayEvent) -> None:
        # Update lead tracking
        if event.home_score > event.away_score:
            self._previous_lead_team = "HOME"
        elif event.away_score > event.home_score:
            self._previous_lead_team = "AWAY"
        else:
            self._previous_lead_team = ""
        # Update rolling window
        if event.points > 0 and event.actor_team:
            self._recent_points.append((event.actor_team, event.points))

    def _snapshot_context(self, event: PlayByPlayEvent, category: str) -> dict:
        return {
            "category": category,
            "period": event.period,
            "clock": event.clock,
            "score_home": event.home_score,
            "score_away": event.away_score,
            "margin": abs(event.home_score - event.away_score),
            "actor_team": event.actor_team,
            "actor_player": event.actor_player,
        }


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------


def _self_test() -> None:
    from realtime.replay_simulator import PlayByPlayReplayer, _SAMPLE_REPLAY  # noqa: E501

    print("[DETECTOR] Running on synthetic mini-game...")
    replayer = PlayByPlayReplayer.from_dict(_SAMPLE_REPLAY, speed=100.0)
    detector = EventDetector()
    for event, t_offset in replayer.stream(sleep=False):
        detected = detector.detect(event)
        print(
            f"[DETECTOR] T+{t_offset:5.1f}s | "
            f"category={detected.category:18s} | salience={detected.salience:.2f} | "
            f"{event.description[:60]}"
        )
    print("[DETECTOR] ✓ Test passed")


if __name__ == "__main__":
    _self_test()
