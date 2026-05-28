"""Regenerate all 60 tactical segments on the OKC-LAL G1 v15 run using the
latest 'do-not-force-tactical-name' prompt.

Output: data/generated/video_scout/real_okc_lal_g1_v16_full_llm/
  - observations.normalized.json (copied from v15)
  - report.json (60 LLM-generated segments)
  - report.md
  - clip_manifest.json (copied from v15 -- clips themselves unchanged)
  - clips/ (symlinked or copied from v15)

Run from repo root:
    python -m thesis_scripts.rerun_v15_llm

Requires:
    .env with LLM_API_KEY (DeepSeek) reachable from this machine.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path


def _load_env() -> None:
    env_path = Path(".env")
    if not env_path.exists():
        print("[ERROR] .env not found in current dir. Run from repo root.")
        sys.exit(1)
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k, v)


def main() -> None:
    _load_env()

    # Import after env is loaded so VideoScoutAnalyzer picks up the key.
    from video_scout.tactic_analyzer import VideoScoutAnalyzer
    from video_scout.models import VisualObservation

    src = Path("data/generated/video_scout/real_okc_lal_g1_v15_endperiodfix")
    dst = Path("data/generated/video_scout/real_okc_lal_g1_v16_full_llm")
    dst.mkdir(parents=True, exist_ok=True)

    obs_path = src / "observations.normalized.json"
    if not obs_path.exists():
        print(f"[ERROR] {obs_path} missing. Check v15 run exists.")
        sys.exit(1)

    raw_observations = json.loads(obs_path.read_text(encoding="utf-8"))
    # Convert dicts to VisualObservation dataclasses (analyzer expects attribute access)
    observations = [VisualObservation.from_dict(o) for o in raw_observations]
    print(f"[info] loaded {len(observations)} observations from v15")

    # Copy normalized observations as-is (input is unchanged).
    shutil.copy(obs_path, dst / "observations.normalized.json")

    # Game context for the analyzer.
    game_context = {
        "title": "OKC Thunder vs Los Angeles Lakers — 2025 NBA Playoffs G1",
        "date": "2025-04-19",
        "teams": ["OKC", "LAL"],
        "final_score": {"OKC": 119, "LAL": 102},
        "venue": "Paycom Center",
    }

    print("[info] calling DeepSeek (deepseek-chat) for 4-stage analysis...")
    t0 = time.time()
    analyzer = VideoScoutAnalyzer(enable_llm=True)
    report = analyzer.analyze(
        observations,
        game_context=game_context,
        play_by_play_context=None,
        court_report_context=None,
        use_reasoning_model=False,
        target_chars=2000,
    )
    elapsed = time.time() - t0
    print(f"[info] LLM pipeline finished in {elapsed:.1f}s")

    # Persist report. analyze() returns a VideoScoutReport dataclass.
    report_dict = report.to_dict() if hasattr(report, "to_dict") else dict(report)
    (dst / "report.json").write_text(
        json.dumps(report_dict, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if "full_analysis" in report_dict:
        (dst / "report.md").write_text(
            report_dict.get("full_analysis", "") or "", encoding="utf-8"
        )

    # Reuse existing clips manifest + clip files (clips are video, prompt-independent).
    if (src / "clip_manifest.json").exists():
        shutil.copy(src / "clip_manifest.json", dst / "clip_manifest.json")
    if (src / "clips").exists() and not (dst / "clips").exists():
        # Use a directory symlink on POSIX; on Windows the script will copy instead.
        try:
            (dst / "clips").symlink_to(
                Path("..") / src.name / "clips", target_is_directory=True
            )
            print(f"[info] symlinked clips/ -> {src.name}/clips")
        except (OSError, NotImplementedError):
            print(f"[info] copying clips/ ({src/'clips'} -> {dst/'clips'})")
            shutil.copytree(src / "clips", dst / "clips")

    segs = report_dict.get("key_segments", []) or []
    print(f"\n[done] {len(segs)} key_segments written -> {dst/'report.json'}")
    print(f"       elapsed: {elapsed:.1f}s, model: deepseek-chat")
    print(f"       use this as v16 in tactical_review.html")


if __name__ == "__main__":
    main()
