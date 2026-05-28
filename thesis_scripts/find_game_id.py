"""Find an NBA game_id by team filter and/or date.

Run from repo root (your network must reach cdn.nba.com — Windows is fine):

    # Most common: find any recent game involving the Spurs
    python -m thesis_scripts.find_game_id --team SAS

    # Narrower: find Spurs vs OKC games in the last 14 days
    python -m thesis_scripts.find_game_id --team SAS --opp OKC --lookback 14

    # Or just dump everything in the last 7 days
    python -m thesis_scripts.find_game_id --lookback 7
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--team", default="", help="Team filter (tricode like SAS, OKC, LAL, GSW, etc.)")
    ap.add_argument("--opp", default="", help="Opponent filter (also a tricode)")
    ap.add_argument(
        "--lookback", type=int, default=30,
        help="Days to look back from today (default 30)",
    )
    args = ap.parse_args()

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from ingestion.nba_live import list_recent_finals

    print(f"[info] fetching schedule, lookback={args.lookback} days...")
    games = list_recent_finals(lookback_days=args.lookback)
    print(f"[info] {len(games)} completed games found")

    # Apply filters
    team = args.team.strip().upper()
    opp = args.opp.strip().upper()
    if team or opp:
        filtered = []
        for g in games:
            home = (g.get("homeTeam", {}).get("teamTricode") or "").upper()
            away = (g.get("awayTeam", {}).get("teamTricode") or "").upper()
            tricodes = {home, away}
            if team and team not in tricodes:
                continue
            if opp and opp not in tricodes:
                continue
            filtered.append(g)
        games = filtered
        print(f"[info] after filter: {len(games)} games")

    if not games:
        print("[empty] no matching games")
        return

    # Pretty print: date, matchup, game_id
    print()
    print(f"{'date':<12} {'matchup':<20} {'game_id':<14} {'final':<14}")
    print("-" * 64)
    for g in games:
        gid = g.get("gameId", "")
        away = g.get("awayTeam", {})
        home = g.get("homeTeam", {})
        away_t = away.get("teamTricode", "?")
        home_t = home.get("teamTricode", "?")
        away_s = away.get("score", "")
        home_s = home.get("score", "")
        date = g.get("gameDateUTC", g.get("gameDate", ""))[:10]
        matchup = f"{away_t} @ {home_t}"
        final = f"{away_s}-{home_s}" if away_s != "" else ""
        print(f"{date:<12} {matchup:<20} {gid:<14} {final:<14}")


if __name__ == "__main__":
    main()
