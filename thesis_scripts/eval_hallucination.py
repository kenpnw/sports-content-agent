"""Compute hallucination rate on the OKC-LAL G1 v16 (full-LLM) report.

Hallucination rate definition:
    For each generated claim in report.key_segments[*].decision_analysis,
    evaluate whether it is supported by the underlying evidence
    (observation event_description + PBP context). Use DeepSeek as the
    judge model with a strict 3-class rubric:
        - supported     -> claim is fully grounded in evidence
        - partial       -> some facts correct, some unverifiable
        - unsupported   -> claim contradicts or invents facts

    Hallucination Rate = (unsupported) / (total)
    Partial-Hallucination Rate = (partial + unsupported) / (total)

Output:
    evaluation/results/thesis_hallucination_v16/
        hallucination_per_claim.json
        hallucination_summary.json
        hallucination_table.md

Run from repo root:
    python -m thesis_scripts.eval_hallucination
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


JUDGE_PROMPT = """你是严谨的体育数据事实核查员。给你 (1) 一段战术解说; (2) 该回合的原始 PBP 证据。\
请你判断解说是否完全被证据支持。

判定规则:
- supported: 所有具体事实(球员姓名、比分、动作、时间、地点等)都能在证据中找到对应; 主观战术评价(如"利用挡拆"、"防守换防慢")若与动作合理一致也算 supported
- partial: 主要事实正确但某些细节(数字、球员名)无法验证或略有偏差
- unsupported: 出现了证据中没有的具体事实(虚构球员、虚构比分、虚构事件)、或与证据明显矛盾

严格按以下 JSON 格式输出, 不要多余文字:
{
  "label": "supported" | "partial" | "unsupported",
  "reason": "<一句话, 30-80 字>"
}
"""


def _load_env() -> None:
    env_path = Path(".env")
    if not env_path.exists():
        print("[ERROR] .env not found.")
        sys.exit(1)
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k, v)


def _judge_one(client, model: str, claim: str, evidence: str) -> dict:
    messages = [
        {"role": "system", "content": JUDGE_PROMPT},
        {
            "role": "user",
            "content": f"【战术解说】\n{claim}\n\n【证据 PBP】\n{evidence}\n\n请判定:",
        },
    ]
    resp = client.chat.completions.create(
        model=model, messages=messages, temperature=0.0, max_tokens=200
    )
    raw = resp.choices[0].message.content.strip()
    # Extract JSON
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1:
        return {"label": "unsupported", "reason": f"judge parse error: {raw[:100]}"}
    try:
        return json.loads(raw[start : end + 1])
    except Exception:
        return {"label": "unsupported", "reason": f"json parse error: {raw[:100]}"}


def main() -> None:
    _load_env()
    try:
        from openai import OpenAI
    except ImportError:
        print("[ERROR] pip install openai")
        sys.exit(1)

    client = OpenAI(
        api_key=os.environ["LLM_API_KEY"], base_url=os.environ["LLM_BASE_URL"]
    )
    model = os.environ.get("LLM_MODEL_FAST", "deepseek-chat")

    # Prefer v16 (full LLM); fall back to v15.
    candidates = [
        "data/generated/video_scout/real_okc_lal_g1_v16_full_llm",
        "data/generated/video_scout/real_okc_lal_g1_v15_endperiodfix",
    ]
    src = None
    for c in candidates:
        if (Path(c) / "report.json").exists():
            src = Path(c)
            break
    if src is None:
        print("[ERROR] no v15/v16 report.json found")
        sys.exit(1)

    print(f"[info] judging report at: {src}")
    report = json.loads((src / "report.json").read_text(encoding="utf-8"))
    obs_list = json.loads(
        (src / "observations.normalized.json").read_text(encoding="utf-8")
    )
    obs_by_id = {o.get("observation_id", ""): o for o in obs_list}

    segments = report.get("key_segments", []) or []
    if not segments:
        print("[ERROR] no key_segments in report.json")
        sys.exit(1)

    print(f"[info] judging {len(segments)} segments with {model}")

    out_dir = Path("evaluation/results/thesis_hallucination_v16")
    out_dir.mkdir(parents=True, exist_ok=True)
    per_claim = []
    counts = {"supported": 0, "partial": 0, "unsupported": 0}

    for i, seg in enumerate(segments, 1):
        claim_text = " ".join(
            [
                seg.get("decision_analysis") or "",
                seg.get("win_loss_impact") or "",
            ]
        ).strip()
        if not claim_text:
            continue
        evidence_ids = seg.get("evidence", []) or []
        evidence_texts = []
        for eid in evidence_ids:
            if eid in obs_by_id:
                ob = obs_by_id[eid]
                evidence_texts.append(
                    f"period={ob.get('period')} clock={ob.get('clock')} event={ob.get('event_description')}"
                )
            else:
                evidence_texts.append(str(eid))
        evidence_text = "\n".join(evidence_texts) or "(no evidence found)"

        verdict = _judge_one(client, model, claim_text, evidence_text)
        label = verdict.get("label", "unsupported")
        counts[label] = counts.get(label, 0) + 1
        per_claim.append(
            {
                "index": i,
                "timecode": seg.get("timecode"),
                "claim": claim_text[:200],
                "label": label,
                "reason": verdict.get("reason", ""),
            }
        )
        if i % 5 == 0:
            print(
                f"   [{i}/{len(segments)}] "
                f"supported={counts['supported']} "
                f"partial={counts['partial']} "
                f"unsupported={counts['unsupported']}"
            )
        # Mild rate limit
        time.sleep(0.2)

    total = sum(counts.values())
    summary = {
        "source_report": str(src),
        "total_claims": total,
        "supported": counts.get("supported", 0),
        "partial": counts.get("partial", 0),
        "unsupported": counts.get("unsupported", 0),
        "hallucination_rate": (
            round(counts.get("unsupported", 0) / total, 4) if total else 0.0
        ),
        "partial_or_worse_rate": (
            round(
                (counts.get("partial", 0) + counts.get("unsupported", 0)) / total, 4
            )
            if total
            else 0.0
        ),
        "judge_model": model,
    }

    (out_dir / "hallucination_per_claim.json").write_text(
        json.dumps(per_claim, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "hallucination_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    table = (
        "| 指标 | 值 |\n"
        "|------|----|\n"
        f"| 总样本数 | {total} |\n"
        f"| 完全支持 | {counts['supported']} ({counts['supported']/total*100:.1f}%) |\n"
        f"| 部分支持 | {counts['partial']} ({counts['partial']/total*100:.1f}%) |\n"
        f"| 未支持 (幻觉) | {counts['unsupported']} ({counts['unsupported']/total*100:.1f}%) |\n"
        f"| **幻觉率** | **{summary['hallucination_rate']*100:.2f}%** |\n"
        f"| 严格幻觉率 (含部分支持) | {summary['partial_or_worse_rate']*100:.2f}% |\n"
        f"| 评审模型 | {model} |\n"
    )
    (out_dir / "hallucination_table.md").write_text(table, encoding="utf-8")

    print("\n[done] " + json.dumps(summary, ensure_ascii=False))
    print(f"\n{table}")
    print(f"\n[saved] {out_dir}/")


if __name__ == "__main__":
    main()
