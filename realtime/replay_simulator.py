"""Play-by-play replay simulator.

Why this exists
---------------
For thesis defense and roadshow we cannot rely on a *live* NBA broadcast
running at exactly the right moment. The replay simulator takes a recorded
play-by-play feed (saved as JSON) and emits its events at real-time speed
(or any multiplier) as if the game were happening live.

This single module is the entire "live data source" for the demo. The rest
of the realtime pipeline (event_detector, live_commentator, frontend) is
agnostic about whether the events came from a true live feed or from this
replayer.

JSON schema expected
--------------------
The replay file is a JSON object with at least:

    {
      "game_id": "0022300999",
      "home_team": "LAL",
      "away_team": "GSW",
      "events": [
        {
          "actionId": "1001",
          "period": 1,
          "clock": "PT11M42S",          # ISO-8601 game clock
          "wallClock": "2025-03-31T02:30:42Z",   # optional
          "description": "LeBron James 25' 3PT Jump Shot Made (3 PTS)",
          "scoreHome": 3,
          "scoreAway": 0,
          "playerNameI": "L. James",
          "actionType": "Made Shot",
          "subType": "3PT",
          "shotResult": "Made",
          "shotValue": 3
        },
        ...
      ]
    }

Events are assumed to be in chronological order. If `wallClock` is present
on every event, the replayer uses real time deltas between events;
otherwise it falls back to the game clock to estimate realistic spacing.

Usage
-----
    replayer = PlayByPlayReplayer.from_file("data/replays/lakers_warriors.json")
    for event, t_offset in replayer.stream():
        print(t_offset, event.description)

The `stream()` method blocks (sleeps) between events to simulate real
time. Pass `speed=10.0` to accelerate playback during development.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from realtime.models import PlayByPlayEvent


# ---------------------------------------------------------------------------
# Clock parsing helpers
# ---------------------------------------------------------------------------


_ISO_CLOCK_RE = re.compile(r"^PT(?:(\d+)M)?([\d.]+)S$")
_MMSS_RE = re.compile(r"^(\d+):([\d.]+)$")


def parse_game_clock(clock: str) -> float:
    """Parse a game clock string into remaining seconds in the period.

    Accepts:
        "PT11M42.5S"  → 702.5
        "11:42"       → 702.0
        "00:08.3"     → 8.3
    Returns 0.0 if unparseable.
    """
    if not clock:
        return 0.0
    s = clock.strip()
    m = _ISO_CLOCK_RE.match(s)
    if m:
        minutes = int(m.group(1)) if m.group(1) else 0
        seconds = float(m.group(2))
        return minutes * 60 + seconds
    m = _MMSS_RE.match(s)
    if m:
        return int(m.group(1)) * 60 + float(m.group(2))
    return 0.0


def _parse_wallclock(value: str) -> datetime | None:
    if not value:
        return None
    try:
        # Support "...Z" suffix
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Replayer
# ---------------------------------------------------------------------------


@dataclass
class ReplayMetadata:
    game_id: str
    home_team: str
    away_team: str
    event_count: int


class PlayByPlayReplayer:
    """Replays a recorded play-by-play feed at configurable speed."""

    # Period length in seconds for time-delta fallback
    PERIOD_LENGTH_SECONDS = 12 * 60        # NBA quarters are 12 minutes
    OT_LENGTH_SECONDS = 5 * 60

    # Default minimum/maximum gap between consecutive events when the wall
    # clock is missing (keeps replay watchable).
    MIN_GAP_SECONDS = 0.4
    MAX_GAP_SECONDS = 8.0

    def __init__(
        self,
        events: list[dict[str, Any]],
        meta: ReplayMetadata,
        speed: float = 1.0,
    ) -> None:
        if speed <= 0:
            raise ValueError("speed must be positive")
        self._events = events
        self._meta = meta
        self._speed = speed

    # ------------------------------------------------------------------ #
    # Construction
    # ------------------------------------------------------------------ #

    @classmethod
    def from_file(cls, path: str | Path, speed: float = 1.0) -> "PlayByPlayReplayer":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(data, speed=speed)

    @classmethod
    def from_dict(cls, payload: dict[str, Any], speed: float = 1.0) -> "PlayByPlayReplayer":
        events = list(payload.get("events", []))
        meta = ReplayMetadata(
            game_id=str(payload.get("game_id", "")),
            home_team=str(payload.get("home_team", "")),
            away_team=str(payload.get("away_team", "")),
            event_count=len(events),
        )
        return cls(events=events, meta=meta, speed=speed)

    # ------------------------------------------------------------------ #
    # Properties
    # ------------------------------------------------------------------ #

    @property
    def metadata(self) -> ReplayMetadata:
        return self._meta

    @property
    def speed(self) -> float:
        return self._speed

    # ------------------------------------------------------------------ #
    # Streaming
    # ------------------------------------------------------------------ #

    def stream(
        self,
        *,
        sleep: bool = True,
        on_progress: Any = None,
    ) -> Iterator[tuple[PlayByPlayEvent, float]]:
        """Yield `(event, t_offset)` pairs.

        Parameters
        ----------
        sleep
            If True, the iterator sleeps the appropriate amount of (real)
            time between events. Set False for offline batch processing.
        on_progress
            Optional callback `fn(event, t_offset)` invoked just before
            each yield (useful for live UI updates).
        """
        if not self._events:
            return

        gaps = self._compute_gaps()
        t0 = time.monotonic()
        cumulative = 0.0

        for idx, raw in enumerate(self._events):
            event = self._parse_event(raw, gaps, idx)
            cumulative += gaps[idx] / self._speed
            if sleep and idx > 0:
                # Wait until the cumulative real-time offset has passed.
                target = t0 + cumulative
                now = time.monotonic()
                if target > now:
                    time.sleep(target - now)
            t_offset = cumulative if idx > 0 else 0.0
            if on_progress is not None:
                try:
                    on_progress(event, t_offset)
                except Exception:
                    pass
            yield event, t_offset

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _parse_event(
        self,
        raw: dict[str, Any],
        gaps: list[float],
        idx: int,
    ) -> PlayByPlayEvent:
        evt = PlayByPlayEvent.from_nba_official(raw)
        # Compute elapsed-in-period from the game clock (period length minus
        # remaining). This is useful for the event detector's salience
        # calculation (clutch time = last 5 minutes of Q4).
        period_len = (
            self.OT_LENGTH_SECONDS
            if evt.period > 4
            else self.PERIOD_LENGTH_SECONDS
        )
        remaining = parse_game_clock(evt.clock)
        evt.elapsed_seconds_in_period = max(0.0, period_len - remaining)
        return evt

    def _compute_gaps(self) -> list[float]:
        """Return inter-event gaps in real seconds.

        Strategy
        --------
        1. If every event has a parseable `wallClock`, use real deltas.
        2. Otherwise, derive deltas from the game clock (good approximation).
        3. Clamp to [MIN_GAP, MAX_GAP] to keep playback watchable.
        """
        n = len(self._events)
        gaps = [0.0] * n
        if n <= 1:
            return gaps

        # Try wall-clock based gaps first.
        wall_clocks = [_parse_wallclock(str(e.get("wallClock", ""))) for e in self._events]
        if all(wc is not None for wc in wall_clocks):
            for i in range(1, n):
                delta = (wall_clocks[i] - wall_clocks[i - 1]).total_seconds()  # type: ignore[operator]
                gaps[i] = max(self.MIN_GAP_SECONDS, min(self.MAX_GAP_SECONDS, delta))
            return gaps

        # Fallback: game-clock-based gaps within each period.
        for i in range(1, n):
            prev = self._events[i - 1]
            cur = self._events[i]
            prev_period = int(prev.get("period", 1))
            cur_period = int(cur.get("period", 1))
            if cur_period != prev_period:
                # Crossing a period boundary — small fixed gap.
                gaps[i] = 1.5
                continue
            prev_remain = parse_game_clock(str(prev.get("clock", "")))
            cur_remain = parse_game_clock(str(cur.get("clock", "")))
            delta = max(0.0, prev_remain - cur_remain)
            gaps[i] = max(self.MIN_GAP_SECONDS, min(self.MAX_GAP_SECONDS, delta))
        return gaps


# ---------------------------------------------------------------------------
# Self-test with a synthetic mini-game
# ---------------------------------------------------------------------------


_SAMPLE_REPLAY = {
    "game_id": "demo_0001",
    "home_team": "LAL",
    "away_team": "GSW",
    "events": [
        {
            "actionId": "1",
            "period": 1,
            "clock": "PT12M00S",
            "description": "Game start",
            "scoreHome": 0,
            "scoreAway": 0,
        },
        {
            "actionId": "2",
            "period": 1,
            "clock": "PT11M42S",
            "description": "L. James 25' 3PT Jump Shot Made",
            "scoreHome": 3,
            "scoreAway": 0,
            "playerNameI": "L. James",
            "actionType": "Made Shot",
            "subType": "3PT",
            "shotResult": "Made",
            "shotValue": 3,
            "teamTricode": "LAL",
        },
        {
            "actionId": "3",
            "period": 1,
            "clock": "PT11M20S",
            "description": "S. Curry 26' 3PT Jump Shot Made",
            "scoreHome": 3,
            "scoreAway": 3,
            "playerNameI": "S. Curry",
            "actionType": "Made Shot",
            "subType": "3PT",
            "shotResult": "Made",
            "shotValue": 3,
            "teamTricode": "GSW",
        },
        {
            "actionId": "4",
            "period": 4,
            "clock": "PT00M08S",
            "description": "S. Curry 28' 3PT Jump Shot Made (clutch)",
            "scoreHome": 110,
            "scoreAway": 113,
            "playerNameI": "S. Curry",
            "actionType": "Made Shot",
            "subType": "3PT",
            "shotResult": "Made",
            "shotValue": 3,
            "teamTricode": "GSW",
        },
    ],
}


def _self_test() -> None:
    print("[REPLAY] Loading synthetic 4-event mini-game (speed=10x)...")
    replayer = PlayByPlayReplayer.from_dict(_SAMPLE_REPLAY, speed=10.0)
    meta = replayer.metadata
    print(f"[REPLAY] {meta.away_team} @ {meta.home_team} (game_id={meta.game_id})")
    print(f"[REPLAY] {meta.event_count} events queued")
    for event, t_offset in replayer.stream():
        print(
            f"[REPLAY] T+{t_offset:5.1f}s | Q{event.period} {event.clock} | "
            f"{event.description} ({event.actor_team} {event.home_score}-{event.away_score})"
        )
    print("[REPLAY] ✓ Test passed")


if __name__ == "__main__":
    _self_test()
