"""Run a three-system evaluation experiment for the Video Scout Agent."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

from evaluation.baselines import GPTOnlyAnalyzer, HighlightOnlyAnalyzer
from evaluation.metrics import (
    boundary_recall_precision_f1,
    claim_fact_accuracy,
    claim_match_diagnostics,
    latency_stats,
    read_gold_boundaries,
)
from storage.file_store import ensure_dir, read_json, timestamp_slug, write_json, write_text
from video_scout.demo_runner import run_video_scout_demo


DEFAULT_OUTPUT_ROOT = Path("evaluation") / "results"
SYSTEM_ORDER = ("main", "highlight_only", "gpt_only")


def run_experiment(
    *,
    replay_path: str,
    court_report_path: str | None,
    gold_boundaries_path: str,
    gold_claims_path: str,
    systems: list[str],
    runs: int,
    output_dir: str | Path | None = None,
    debug: bool = False,
) -> dict[str, Any]:
    """Run selected systems and write all evaluation artifacts."""
    _ensure_eval_llm_defaults()
    output_base = Path(output_dir) if output_dir else DEFAULT_OUTPUT_ROOT / timestamp_slug()
    ensure_dir(output_base)

    gold_boundaries = read_gold_boundaries(gold_boundaries_path)
    per_system_outputs: dict[str, Any] = {}
    boundary_metrics: dict[str, Any] = {}
    claim_metrics: dict[str, Any] = {}
    latency_metrics: dict[str, Any] = {}
    match_diagnostics: dict[str, Any] = {}

    for system in systems:
        if system not in SYSTEM_ORDER:
            raise ValueError(f"Unknown system `{system}`. Expected one of: {', '.join(SYSTEM_ORDER)}")
        runs_payload = []
        latencies: list[float] = []
        for run_index in range(1, runs + 1):
            result = _run_one_system(
                system=system,
                replay_path=replay_path,
                court_report_path=court_report_path,
                output_base=output_base,
                run_index=run_index,
            )
            runs_payload.append(result)
            latencies.append(float(result.get("elapsed_seconds", 0.0) or 0.0))

        first_report = runs_payload[0]["report"] if runs_payload else {}
        predicted_boundaries = runs_payload[0].get("predicted_boundaries", []) if runs_payload else []
        per_system_outputs[system] = {
            "runs": runs_payload,
            "fallback": any(bool(item.get("fallback", False)) for item in runs_payload),
        }
        predicted_for_boundary_metric = None if system == "gpt_only" else predicted_boundaries
        boundary_metrics[system] = boundary_recall_precision_f1(predicted_for_boundary_metric, gold_boundaries)
        claim_metrics[system] = claim_fact_accuracy(first_report, gold_claims_path)
        latency_metrics[system] = latency_stats(latencies)
        if debug:
            match_diagnostics[system] = claim_match_diagnostics(first_report, gold_claims_path)

    summary = _summary_table(boundary_metrics, claim_metrics, latency_metrics, per_system_outputs)
    write_json(output_base / "per_system_outputs.json", per_system_outputs)
    write_json(output_base / "boundary_metrics.json", boundary_metrics)
    write_json(output_base / "claim_metrics.json", claim_metrics)
    write_json(output_base / "latency_metrics.json", latency_metrics)
    write_text(output_base / "summary_table.md", summary)
    diagnostics_path = ""
    if debug:
        diagnostics_path = str((output_base / "match_diagnostics.json").resolve())
        write_json(output_base / "match_diagnostics.json", match_diagnostics)

    return {
        "output_dir": str(output_base.resolve()),
        "systems": systems,
        "runs": runs,
        "debug": debug,
        "match_diagnostics_path": diagnostics_path,
        "summary_table": summary,
        "boundary_metrics": boundary_metrics,
        "claim_metrics": claim_metrics,
        "latency_metrics": latency_metrics,
    }


def _run_one_system(
    *,
    system: str,
    replay_path: str,
    court_report_path: str | None,
    output_base: Path,
    run_index: int,
) -> dict[str, Any]:
    start = time.monotonic()
    if system == "main":
        run_dir = output_base / "main_artifacts" / f"run_{run_index:02d}"
        summary = run_video_scout_demo(
            replay_path=replay_path,
            court_report_path=court_report_path,
            output_dir=str(run_dir),
            use_llm=True,
            target_chars=2000,
            auto_observations=True,
        )
        elapsed = time.monotonic() - start
        report_path = Path(summary["output_dir"]) / "report.json"
        observations_path = Path(summary["output_dir"]) / "observations.normalized.json"
        report = read_json(report_path)
        observations = read_json(observations_path)
        predicted = _predicted_boundaries_from_observations(observations)
        fallback = not bool(summary.get("llm_used_successfully", False))
        return {
            "system": system,
            "run_index": run_index,
            "elapsed_seconds": round(elapsed, 4),
            "fallback": fallback,
            "summary": summary,
            "report": report,
            "predicted_boundaries": predicted,
        }

    if system == "highlight_only":
        report = HighlightOnlyAnalyzer().analyze(replay_path, court_report_path)
    elif system == "gpt_only":
        report = GPTOnlyAnalyzer().analyze(replay_path, court_report_path)
    else:
        raise ValueError(f"Unknown system `{system}`")

    elapsed = time.monotonic() - start
    metadata = report.get("metadata", {}) if isinstance(report, dict) else {}
    return {
        "system": system,
        "run_index": run_index,
        "elapsed_seconds": round(elapsed, 4),
        "fallback": bool(metadata.get("fallback", False)),
        "summary": {
            "llm_used_successfully": not bool(metadata.get("fallback", False)),
            "elapsed_seconds": round(elapsed, 4),
        },
        "report": report,
        "predicted_boundaries": metadata.get("predicted_boundaries", []),
    }


def _predicted_boundaries_from_observations(observations_payload: Any) -> list[dict[str, Any]]:
    if isinstance(observations_payload, dict):
        observations = observations_payload.get("observations", [])
    else:
        observations = observations_payload
    predicted: list[dict[str, Any]] = []
    if not isinstance(observations, list):
        return predicted
    for item in observations:
        if not isinstance(item, dict):
            continue
        event_ids = [
            str(value).split("event:", 1)[1]
            for value in item.get("evidence", [])
            if str(value).startswith("event:")
        ]
        if not event_ids:
            continue
        predicted.append(
            {
                "period": int(item.get("period", 0) or 0),
                "end_event_index": event_ids[-1],
                "end_reason": _infer_end_reason(item.get("tactic_tags", [])),
                "possession_team": str(item.get("possession_team", "")),
            }
        )
    return predicted


def _infer_end_reason(tags: Any) -> str:
    tag_set = {str(tag) for tag in tags if str(tag)}
    for reason in ("game_end", "period_end", "turnover", "defensive_rebound", "made_shot"):
        if reason in tag_set:
            return reason
    return sorted(tag_set)[-1] if tag_set else ""


def _summary_table(
    boundary_metrics: dict[str, Any],
    claim_metrics: dict[str, Any],
    latency_metrics: dict[str, Any],
    per_system_outputs: dict[str, Any],
) -> str:
    lines = [
        "| System | Boundary Precision | Boundary Recall | Boundary F1 | Claim Accuracy | Claim Coverage | Hallucination Rate | Latency p50(s) | Latency p95(s) | Fallback |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for system in SYSTEM_ORDER:
        if system not in boundary_metrics:
            continue
        boundary = boundary_metrics[system]
        claim = claim_metrics[system]
        latency = latency_metrics[system]
        fallback = "yes" if per_system_outputs.get(system, {}).get("fallback") else "no"
        lines.append(
            f"| {system} | {_format_optional(boundary['precision'])} | "
            f"{_format_optional(boundary['recall'])} | {_format_optional(boundary['f1'])} | "
            f"{claim['accuracy']:.4f} | {claim['coverage']:.4f} | {claim['hallucination_rate']:.4f} | "
            f"{latency['p50']:.2f} | {latency['p95']:.2f} | {fallback} |"
        )
    return "\n".join(lines) + "\n"


def _format_optional(value: Any) -> str:
    if value is None:
        return "—"
    return f"{float(value):.4f}"


def _ensure_eval_llm_defaults() -> None:
    os.environ.setdefault("LLM_MODEL_FAST", "deepseek-chat")
    try:
        timeout = float(os.getenv("LLM_TIMEOUT_SECONDS", "0") or 0)
    except ValueError:
        timeout = 0.0
    if timeout < 60:
        os.environ["LLM_TIMEOUT_SECONDS"] = "60"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Video Scout evaluation experiment.")
    parser.add_argument("--replay", required=True, help="Replay JSON path.")
    parser.add_argument("--court-report", default="", help="Optional smart-court report JSON path.")
    parser.add_argument("--gold-boundaries", required=True, help="Gold boundary CSV path.")
    parser.add_argument("--gold-claims", required=True, help="Gold claim CSV path.")
    parser.add_argument("--systems", default="main,highlight_only,gpt_only", help="Comma-separated systems.")
    parser.add_argument("--runs", type=int, default=1, help="Runs per system for latency stats.")
    parser.add_argument("--debug", action="store_true", help="Write match_diagnostics.json for claim matching.")
    parser.add_argument("--output", default="", help="Output folder.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    systems = [item.strip() for item in args.systems.split(",") if item.strip()]
    result = run_experiment(
        replay_path=args.replay,
        court_report_path=args.court_report or None,
        gold_boundaries_path=args.gold_boundaries,
        gold_claims_path=args.gold_claims,
        systems=systems,
        runs=max(1, args.runs),
        output_dir=args.output or None,
        debug=args.debug,
    )
    print(json.dumps({key: value for key, value in result.items() if key != "summary_table"}, ensure_ascii=False, indent=2))
    print("\nsummary_table.md")
    print("----------------")
    print(result["summary_table"])


if __name__ == "__main__":
    main()
