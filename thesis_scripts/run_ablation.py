"""Run the three-system ablation experiment for the thesis Chapter 5 table.

Systems compared:
    main             -> Our full pipeline (5-Agent + Prompt Contract + Fact Store)
    highlight_only   -> Same pipeline but no Fact Checker stage (highlights only)
    gpt_only         -> Plain GPT (DeepSeek-chat) with no structured grounding

Metrics:
    - boundary precision/recall/F1 (vs gold_boundaries.csv)
    - claim fact accuracy (% of generated claims that match gold_claims.csv)
    - hallucination rate (% unsupported)
    - end-to-end latency per system
    - per-segment LLM token cost

Run from repo root:
    python -m thesis_scripts.run_ablation
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


def _load_env() -> None:
    env_path = Path(".env")
    if not env_path.exists():
        print("[ERROR] .env not found; run from repo root.")
        sys.exit(1)
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k, v)


def main() -> None:
    _load_env()

    from evaluation.run_experiment import run_experiment

    replay_path = "data/samples/nba_replay_sample.json"
    gold_boundaries = "evaluation/datasets/gold_boundaries.csv"
    gold_claims = "evaluation/datasets/gold_claims.csv"

    output_dir = Path("evaluation/results/thesis_ablation_v16")
    output_dir.mkdir(parents=True, exist_ok=True)

    print("[info] Running 3-system ablation on", replay_path)
    print("[info] Systems:    main, highlight_only, gpt_only")
    print("[info] Runs:       3 (for latency stats)")
    print("[info] Output:    ", output_dir)
    print()

    t0 = time.time()
    result = run_experiment(
        replay_path=replay_path,
        court_report_path=None,
        gold_boundaries_path=gold_boundaries,
        gold_claims_path=gold_claims,
        systems=["main", "highlight_only", "gpt_only"],
        runs=3,
        output_dir=str(output_dir),
        debug=True,
    )
    elapsed = time.time() - t0
    print(f"\n[done] Ablation finished in {elapsed:.1f}s")
    print(f"       Summary table:\n{result.get('summary_table', '<missing>')}")
    print(f"\n       Raw JSON outputs in: {output_dir}/")
    print(f"       Use evaluation/results/thesis_ablation_v16/summary_table.md for thesis.")


if __name__ == "__main__":
    main()
