# Evaluation Framework

This folder supports the thesis experiment for Video Scout. It compares the
full system with two independent baselines under the same replay, gold labels,
and DeepSeek client wrapper.

## Systems

`main` runs the current Video Scout pipeline:
PBP replay -> `PossessionBoundaryDetector` -> auto observations -> court-report
evidence injection -> four-step tactical report generation.

`highlight_only` selects only made-shot highlights, mainly 3PT and dunk events.
It simulates a basic AI highlight product that sees scoring moments but does
not reconstruct tactical possessions.

`gpt_only` sends raw PBP JSON directly to the LLM. It simulates prompt-only
usage without event detection, court-report injection, or evidence indexing.

## Gold Boundary CSV

Path: `evaluation/datasets/mini_gold_boundaries.csv`

Fields:

- `scenario_id`: manually assigned scenario or game id.
- `period`: NBA period number.
- `end_event_index`: the PBP `actionId` that ends the possession.
- `end_reason`: label such as `made_shot`, `turnover`, `defensive_rebound`.
- `possession_team`: offensive team for that possession.

For the final thesis experiment, expand this file to 30-50 manually checked
boundaries across several games. Keep `end_event_index` aligned with the replay
JSON `actionId`, not the row number in the file.

## Gold Claim CSV

Path: `evaluation/datasets/mini_gold_claims.csv`

Fields:

- `scenario_id`: same scenario id used by the boundary file.
- `claim_text`: a fact claim that should or should not appear in generated output.
- `label`: one of `correct`, `incorrect`, or `unverifiable`.

`incorrect` rows are intentional traps. If a report repeats them, the
hallucination rate rises. `unverifiable` rows count toward coverage, but are
excluded from the accuracy denominator.

To expand the dataset, mark 30-50 short claims from PBP and court reports:
shot descriptions, turnovers, MVP stat lines, and player tactical stat lines.
Prefer short, exact strings so the fuzzy matcher remains interpretable.

## Running The Mini Experiment

From `sports_agent/`:

```powershell
.\.venv\Scripts\python.exe -m evaluation.run_experiment `
  --replay data\samples\nba_replay_sample.json `
  --court-report data\samples\court_ai_report_sample.json `
  --gold-boundaries evaluation\datasets\mini_gold_boundaries.csv `
  --gold-claims evaluation\datasets\mini_gold_claims.csv `
  --systems main,highlight_only,gpt_only `
  --runs 1 `
  --output evaluation\results\mini_validate
```

Outputs:

- `per_system_outputs.json`: report dictionaries, summaries, fallback flags,
  predicted boundaries, and per-run latency.
- `boundary_metrics.json`: precision, recall, F1, TP, FP, FN for each system.
- `claim_metrics.json`: fact accuracy, coverage, hallucination rate, and fuzzy
  matches.
- `latency_metrics.json`: p50, p95, mean, and run count.
- `summary_table.md`: thesis-friendly comparison table.

## Adding A New Baseline

Add a new analyzer class in `evaluation/baselines.py` with:

```python
analyze(replay_path, court_report_path) -> dict
```

The returned dict should include:

- `full_analysis`
- `key_segments`
- `metadata.fallback`
- `metadata.predicted_boundaries`

Then register it in `evaluation/run_experiment.py` without calling the main
Video Scout pipeline internals.

## Reading The Results

For the mini sample, the expected pattern is:

- `main` should have the best boundary F1 because it detects turnovers and
  possession-level boundaries.
- `highlight_only` should be lower because it ignores non-scoring boundaries.
- `gpt_only` should have boundary F1 near zero because it produces no explicit
  boundaries.
- `main` should have stronger claim accuracy and coverage when court-report
  evidence is injected into key segments.

