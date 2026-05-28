"""End-to-end NBA game pipeline — autodetect everything from the video file.

USAGE (the one-command flow):

    python -m thesis_scripts.run_game --video "C:\\path\\to\\game.mkv"

That's it. The script will:

    1. Sniff the video filename + file mtime for team tricodes and a date.
    2. Hit the NBA Live schedule API to find the matching game.
       - If exactly one match -> auto-confirm and proceed.
       - If multiple ambiguous matches -> show a one-line numbered picker.
       - If zero matches -> print helpful diagnostics and exit.
    3. Auto-generate a slug from the matchup, e.g. "sas_okc_20260527".
    4. Fetch PBP, run ROI auto-detect + scoreboard visibility,
       build time map, snap clips, run 5-agent LLM analysis,
       package 4 platforms — the full pipeline, untouched by hand.

OVERRIDES (only if autodetect goes wrong):

    --game-id 0042500314      Force a specific game_id
    --slug my_custom_slug     Force the output folder slug
    --date 2026-05-27         Force the date used for autodetect
    --no-prompt               Fail instead of asking for picker (CI mode)
    --skip-roi                Skip auto-ROI (re-use existing JSON)
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path


# Common NBA team tricodes that may appear in filenames.
TEAM_TRICODES = {
    "ATL", "BOS", "BKN", "CHA", "CHI", "CLE", "DAL", "DEN", "DET", "GSW",
    "HOU", "IND", "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NOP", "NYK",
    "OKC", "ORL", "PHI", "PHX", "POR", "SAC", "SAS", "TOR", "UTA", "WAS",
}
# Common nicknames -> tricode mapping (case-insensitive substring match)
TEAM_NICKNAMES = {
    "spurs": "SAS", "thunder": "OKC", "lakers": "LAL", "warriors": "GSW",
    "celtics": "BOS", "knicks": "NYK", "heat": "MIA", "bucks": "MIL",
    "nuggets": "DEN", "76ers": "PHI", "sixers": "PHI", "raptors": "TOR",
    "clippers": "LAC", "suns": "PHX", "mavs": "DAL", "mavericks": "DAL",
    "rockets": "HOU", "grizzlies": "MEM", "kings": "SAC", "blazers": "POR",
    "trailblazers": "POR", "jazz": "UTA", "pelicans": "NOP", "magic": "ORL",
    "wizards": "WAS", "hornets": "CHA", "bulls": "CHI", "cavs": "CLE",
    "cavaliers": "CLE", "pistons": "DET", "pacers": "IND", "wolves": "MIN",
    "timberwolves": "MIN", "nets": "BKN", "hawks": "ATL",
    # Chinese names (the user lives in Chinese, so the filename might be too)
    "马刺": "SAS", "雷霆": "OKC", "湖人": "LAL", "勇士": "GSW",
    "凯尔特人": "BOS", "尼克斯": "NYK", "热火": "MIA", "雄鹿": "MIL",
    "掘金": "DEN", "76人": "PHI", "猛龙": "TOR", "快船": "LAC", "太阳": "PHX",
    "独行侠": "DAL", "火箭": "HOU", "灰熊": "MEM", "国王": "SAC",
    "开拓者": "POR", "爵士": "UTA", "鹈鹕": "NOP", "魔术": "ORL",
    "奇才": "WAS", "黄蜂": "CHA", "公牛": "CHI", "骑士": "CLE",
    "活塞": "DET", "步行者": "IND", "森林狼": "MIN", "篮网": "BKN", "老鹰": "ATL",
}


def _load_env() -> None:
    env_path = Path(".env")
    if not env_path.exists():
        print("[error] .env not found in current dir; run from repo root.")
        sys.exit(1)
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k, v)


def _sniff_tricodes(name: str) -> set[str]:
    """Pull team tricodes out of a video filename."""
    found: set[str] = set()
    upper = name.upper()
    for tri in TEAM_TRICODES:
        # Match standalone tricodes (word boundary)
        if re.search(rf"(?<![A-Z]){tri}(?![A-Z])", upper):
            found.add(tri)
    # Also check for nicknames in original-case name
    lower = name.lower()
    for nick, tri in TEAM_NICKNAMES.items():
        if nick.lower() in lower:
            found.add(tri)
    return found


def _sniff_date(name: str, mtime: float) -> date | None:
    """Pull a date out of a filename, fall back to file mtime."""
    # Look for YYYYMMDD or YYYY-MM-DD or YYYY_MM_DD
    m = re.search(r"(20\d{2})[\-_]?(\d{2})[\-_]?(\d{2})", name)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    # Try MM-DD assuming current year
    m = re.search(r"(?<!\d)(\d{1,2})[\-_月\.]\s*(\d{1,2})(?!\d)", name)
    if m:
        try:
            year = date.today().year
            return date(year, int(m.group(1)), int(m.group(2)))
        except ValueError:
            pass
    # Fall back to file mtime
    return date.fromtimestamp(mtime)


def _autodetect_game(video_path: Path, override_date: date | None) -> dict | None:
    """Return the single matching NBA game dict, or None if ambiguous/missing."""
    from ingestion.nba_live import list_recent_finals

    name = video_path.stem
    tricodes = _sniff_tricodes(name)
    sniffed_date = override_date or _sniff_date(name, video_path.stat().st_mtime)

    print(f"[autodetect] video stem: {name!r}")
    print(f"[autodetect] sniffed tricodes: {sorted(tricodes) or '(none)'}")
    print(f"[autodetect] sniffed date:     {sniffed_date}")

    # Look back from sniffed date +/- 2 days to absorb timezone slop
    today = date.today()
    lookback = max(7, (today - sniffed_date).days + 5)
    print(f"[autodetect] querying NBA schedule, lookback={lookback} days...")
    games = list_recent_finals(lookback_days=lookback)
    print(f"[autodetect] {len(games)} completed games in window")

    # Score each game: +5 for matching date, +3 per matching tricode
    def score(g: dict) -> int:
        s = 0
        gd_raw = g.get("gameDateUTC") or g.get("gameDate") or g.get("gameEt") or ""
        try:
            gd = datetime.fromisoformat(gd_raw.replace("Z", "+00:00")).date()
        except (ValueError, TypeError):
            gd = None
        if gd and sniffed_date and abs((gd - sniffed_date).days) <= 1:
            s += 5
        home_t = (g.get("homeTeam", {}).get("teamTricode") or "").upper()
        away_t = (g.get("awayTeam", {}).get("teamTricode") or "").upper()
        if home_t in tricodes:
            s += 3
        if away_t in tricodes:
            s += 3
        return s

    scored = sorted(games, key=score, reverse=True)
    top_score = score(scored[0]) if scored else 0

    if top_score == 0:
        return None
    candidates = [g for g in scored if score(g) == top_score]

    if len(candidates) == 1:
        g = candidates[0]
        print(f"[autodetect] unique match  -> "
              f"{g['awayTeam']['teamTricode']} @ {g['homeTeam']['teamTricode']} "
              f"({g.get('gameDateUTC', g.get('gameEt', ''))[:10]}) "
              f"game_id={g['gameId']}  [score {top_score}]")
        return g

    # Multiple candidates; let the user pick.
    print(f"[autodetect] {len(candidates)} candidate matches (top score = {top_score}):")
    for i, g in enumerate(candidates, 1):
        date_str = (g.get("gameDateUTC") or g.get("gameEt") or "")[:10]
        print(f"  [{i}] {g['awayTeam']['teamTricode']} @ {g['homeTeam']['teamTricode']}  "
              f"{date_str}  {g.get('awayTeam', {}).get('score', 0)}-{g.get('homeTeam', {}).get('score', 0)}  "
              f"game_id={g['gameId']}")
    try:
        choice = input("Pick number (or Enter to abort): ").strip()
    except EOFError:
        choice = ""
    if not choice or not choice.isdigit():
        return None
    idx = int(choice) - 1
    if 0 <= idx < len(candidates):
        return candidates[idx]
    return None


def _slugify(g: dict) -> str:
    """Generate a stable slug from a game dict, e.g. 'sas_okc_20260527'."""
    away = (g.get("awayTeam", {}).get("teamTricode") or "X").lower()
    home = (g.get("homeTeam", {}).get("teamTricode") or "X").lower()
    date_str = (g.get("gameDateUTC") or g.get("gameEt") or "")[:10].replace("-", "")
    return f"{away}_{home}_{date_str}"


def _run(cmd: list[str], desc: str) -> bool:
    print(f"\n[{desc}]")
    print(f"  $ {' '.join(cmd)}")
    r = subprocess.run(cmd)
    if r.returncode != 0:
        print(f"  [FAIL] rc={r.returncode}")
        return False
    return True


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True, help="Path to the downloaded video file")
    ap.add_argument("--game-id", default="", help="Override autodetect")
    ap.add_argument("--slug", default="", help="Override slug")
    ap.add_argument("--date", default="", help="Override date (YYYY-MM-DD) for autodetect")
    ap.add_argument("--no-prompt", action="store_true",
                    help="Fail instead of asking for picker (CI mode)")
    ap.add_argument("--skip-roi", action="store_true",
                    help="Skip ROI auto-detect; reuse existing JSON")
    args = ap.parse_args()

    _load_env()

    video_path = Path(args.video).expanduser().resolve()
    if not video_path.exists():
        print(f"[error] video not found: {video_path}")
        sys.exit(1)
    print(f"[info] video: {video_path}  ({video_path.stat().st_size / 1e9:.1f} GB)")

    # ---- Stage 0: autodetect or take overrides ----
    game_id = args.game_id.strip()
    slug = args.slug.strip()

    if not game_id:
        override_date = None
        if args.date:
            try:
                override_date = datetime.strptime(args.date, "%Y-%m-%d").date()
            except ValueError:
                print(f"[error] bad --date format: {args.date}")
                sys.exit(1)
        if args.no_prompt:
            # In CI/--no-prompt mode, only auto-accept unique matches
            sys.stdin = open(os.devnull)  # so input() raises EOFError instantly
        g = _autodetect_game(video_path, override_date)
        if g is None:
            print("\n[error] could not autodetect a single matching game.")
            print("        Either pass --game-id <id> directly, or check the filename")
            print("        contains team tricodes (SAS, OKC, etc) or a date (YYYYMMDD).")
            sys.exit(1)
        game_id = g["gameId"]
        if not slug:
            slug = _slugify(g)
    else:
        if not slug:
            slug = f"game_{game_id}"
        print(f"[info] override game_id={game_id} slug={slug}")

    print(f"\n[plan] game_id={game_id}  slug={slug}")
    out_root = Path(f"data/generated/video_scout/real_{slug}_v1")
    out_root.mkdir(parents=True, exist_ok=True)
    print(f"[plan] output dir: {out_root}")

    # ---- Stage 1: PBP ----
    pbp_path = out_root / "pbp.json"
    ok = _run(
        [sys.executable, "-m", "ingestion.nba_pbp_fetcher",
         "--game-id", game_id, "--output", str(pbp_path)],
        "1/5  PBP fetch",
    )
    if not ok:
        sys.exit(1)
    print(f"  -> {pbp_path}")

    # ---- Stage 2: ROI ----
    roi_path = video_path.with_suffix(".scoreboard_roi.json")
    if not args.skip_roi and not roi_path.exists():
        _run(
            [sys.executable, "-m", "video_scout.auto_roi_detector",
             "--video", str(video_path), "--output", str(roi_path)],
            "2/5  Auto-ROI detection",
        )
        if not roi_path.exists():
            print(f"  [warn] ROI auto-detect failed; downstream will use heuristic defaults")
    else:
        print(f"\n[2/5  ROI]  re-using {roi_path}")

    # ---- Stage 3: Scoreboard visibility (dense v2) ----
    vis_path = video_path.with_suffix(".scoreboard_visibility_v2.json")
    cmd3 = [sys.executable, "-m", "video_scout.scoreboard_visibility_detector",
            "--video", str(video_path), "--output", str(vis_path), "--mode", "dense_v2"]
    if roi_path.exists():
        cmd3.extend(["--roi", str(roi_path)])
    _run(cmd3, "3/5  Scoreboard visibility detection")

    # ---- Stage 4: OCR time map ----
    tmap_path = video_path.with_suffix(".time_map.json")
    cmd4 = [sys.executable, "-m", "video_scout.video_time_mapper",
            "--video", str(video_path), "--output", str(tmap_path)]
    if roi_path.exists():
        cmd4.extend(["--roi", str(roi_path)])
    _run(cmd4, "4/5  OCR time map")

    # ---- Stage 5: full 5-Agent pipeline ----
    cmd5 = [sys.executable, "-m", "video_scout.demo_runner",
            "--video", str(video_path),
            "--replay", str(pbp_path),
            "--auto-observations",
            "--auto-periods", "1,2,3,4",
            "--use-llm",
            "--output-dir", str(out_root)]
    if tmap_path.exists():
        cmd5.extend(["--apply-time-map", "--time-map", str(tmap_path)])
    if roi_path.exists():
        cmd5.extend(["--refine-events", "--roi", str(roi_path)])
    if vis_path.exists():
        cmd5.extend(["--play-segments", str(vis_path)])

    t0 = time.time()
    ok = _run(cmd5, "5/5  Full 5-Agent pipeline (DeepSeek)")
    elapsed = time.time() - t0
    if not ok:
        sys.exit(1)

    print(f"\n[DONE] full pipeline in {elapsed:.1f}s")
    print(f"       output:   {out_root}")
    print(f"       inspect:  {out_root/'report.json'} / {out_root/'clips'}/")
    print(f"       webapp:   /tactical?report={slug}_v1")


if __name__ == "__main__":
    main()
