"""PDF Tactical Reader — extracts structured tactical intelligence from
basketball scouting reports / coaching documents using a vision LLM.

Pipeline:
    1. Render each PDF page to a PNG (pypdfium2, 200 DPI by default).
    2. Send each page to a vision LLM (Claude / GPT-4o / DeepSeek-VL —
       any provider that accepts the OpenAI-compatible chat-completions
       `image_url` payload).
    3. Aggregate page-level extractions into a single court_report-shaped
       JSON that the Content Agent can consume directly.

Output schema (subset of analysis/nba_postgame_rules.CourtReport):

    {
      "title": "string",
      "matchup": "OKC vs LAL",
      "summary": "string",
      "player_stats": [
        {"player": "L. James", "team": "LAL", "stats": {...}}
      ],
      "tactical_themes": [
        {"name": "1-5 PnR", "english": "1-5 Pick and Roll",
         "description": "...", "page": 3}
      ],
      "coach_quotes": [
        {"speaker": "Redick", "quote": "...", "page": 5}
      ],
      "matchup_advantages": [
        {"team": "OKC", "area": "Rim protection", "rationale": "..."}
      ],
      "source_pdf": "scout_report.pdf",
      "extracted_at": "2026-05-29T..."
    }

CLI:
    python -m reader.pdf_tactical_reader \\
        --pdf data/pdfs/scout_report.pdf \\
        --output data/generated/court_reports/<game_id>_court_report.json \\
        --pages 1-12              # optional page range
        --model deepseek-chat     # or claude-3-5-sonnet-20241022, gpt-4o, etc.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


# ---------- Prompt: extract tactical JSON from one page ----------
PAGE_EXTRACTION_SYSTEM_PROMPT = """你是一位有 NBA 战术分析背景的体育数据工程师，专门把球探报告和教练手册转换为结构化数据。
你看到的图像是一份篮球战术报告 PDF 的一页（可能是战术图、数据表、文字段落、或它们的组合）。

**严格要求：**
- 只提取你在图中真实看到的信息，不要编造内容
- 数字必须精确读取（不允许 "估计" 或 "大约"）
- 战术名称要用中英对照（如 "一五挡拆 (1-5 PnR)"、"反跑 (Backdoor Cut)"）
- 球员姓名保持英文（如 "L. James"、"S. Gilgeous-Alexander"）
- 如果某个字段在这一页找不到对应内容，输出空数组 `[]` 或空字符串 `""`，不要硬编

按以下 JSON 格式严格输出，不要附加任何解释或 markdown 包装：

{
  "title": "本页的主题（短句，10-30 字）",
  "summary": "本页内容摘要（50-150 字）",
  "player_stats": [
    {"player": "球员姓名", "team": "TRICODE 如 OKC/LAL", "stats": {"PTS": 27, "REB": 6, "AST": 9, "+/-": 12}}
  ],
  "tactical_themes": [
    {"name": "中文战术名", "english": "English Tactic Name", "description": "30-80 字说明", "page_evidence": "图中具体证据，如 '左侧底角空切箭头'"}
  ],
  "coach_quotes": [
    {"speaker": "教练或球员名", "quote": "原文引用（保持原文语言）"}
  ],
  "matchup_advantages": [
    {"team": "OKC", "area": "对位优势的领域，如 '禁区护框'", "rationale": "30-80 字理由"}
  ],
  "key_plays": [
    {"clock": "Q3 7:42", "description": "回合简述", "outcome": "made_shot / turnover / etc"}
  ]
}
"""

PAGE_EXTRACTION_USER_PROMPT = """这是 PDF 第 {page_num} 页（共 {total_pages} 页）。请按 JSON schema 严格提取本页可见的战术情报。"""


@dataclass
class TacticalReportExtraction:
    """Aggregated extraction across all PDF pages."""
    title: str = ""
    matchup: str = ""
    summary: str = ""
    player_stats: list[dict[str, Any]] = field(default_factory=list)
    tactical_themes: list[dict[str, Any]] = field(default_factory=list)
    coach_quotes: list[dict[str, Any]] = field(default_factory=list)
    matchup_advantages: list[dict[str, Any]] = field(default_factory=list)
    key_plays: list[dict[str, Any]] = field(default_factory=list)
    source_pdf: str = ""
    page_count: int = 0
    extracted_at: str = ""
    extraction_model: str = ""
    per_page_extractions: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "matchup": self.matchup,
            "summary": self.summary,
            "player_stats": self.player_stats,
            "tactical_themes": self.tactical_themes,
            "coach_quotes": self.coach_quotes,
            "matchup_advantages": self.matchup_advantages,
            "key_plays": self.key_plays,
            "source_pdf": self.source_pdf,
            "page_count": self.page_count,
            "extracted_at": self.extracted_at,
            "extraction_model": self.extraction_model,
            "per_page_extractions": self.per_page_extractions,
        }


class PDFTacticalReader:
    """Renders PDF pages, sends to vision LLM, aggregates structured output."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = "",
        dpi: int = 200,
    ) -> None:
        self.api_key = api_key or os.environ.get("LLM_API_KEY", "")
        self.base_url = base_url or os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")
        self.model = model or os.environ.get("LLM_MODEL_VISION", "") or os.environ.get(
            "LLM_MODEL_FAST", "deepseek-chat"
        )
        self.dpi = dpi
        if not self.api_key:
            raise ValueError("LLM_API_KEY not set (in .env or constructor).")

    # ---------- Render PDF pages to PNG bytes ----------
    def render_pages(
        self, pdf_path: Path, pages: list[int] | None = None
    ) -> list[tuple[int, bytes]]:
        """Return list of (page_num_1_indexed, png_bytes)."""
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(str(pdf_path))
        total = len(pdf)
        if pages is None:
            pages = list(range(1, total + 1))
        result: list[tuple[int, bytes]] = []
        for page_num in pages:
            if page_num < 1 or page_num > total:
                continue
            page = pdf[page_num - 1]
            scale = self.dpi / 72.0
            pil_image = page.render(scale=scale).to_pil()
            buf = io.BytesIO()
            pil_image.save(buf, format="PNG", optimize=True)
            result.append((page_num, buf.getvalue()))
            page.close()
        pdf.close()
        return result

    # ---------- Call vision LLM on one page ----------
    def extract_page(
        self, page_num: int, total_pages: int, png_bytes: bytes
    ) -> dict[str, Any]:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("openai package not installed; run: pip install openai") from exc

        client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        b64 = base64.b64encode(png_bytes).decode("ascii")
        image_url = f"data:image/png;base64,{b64}"

        messages = [
            {"role": "system", "content": PAGE_EXTRACTION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": PAGE_EXTRACTION_USER_PROMPT.format(
                        page_num=page_num, total_pages=total_pages
                    )},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            },
        ]
        resp = client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.1,
            max_tokens=2000,
        )
        raw = resp.choices[0].message.content or ""
        # Extract JSON (model may wrap in ```json ... ``` or add prose)
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end == -1:
            return {
                "_parse_error": True,
                "_raw": raw[:500],
                "page": page_num,
            }
        try:
            data = json.loads(raw[start : end + 1])
        except json.JSONDecodeError as exc:
            data = {
                "_parse_error": True,
                "_error": str(exc),
                "_raw": raw[start : end + 1][:500],
                "page": page_num,
            }
        data.setdefault("page", page_num)
        return data

    # ---------- Aggregate per-page extractions ----------
    def aggregate(
        self,
        pdf_path: Path,
        per_page: list[dict[str, Any]],
    ) -> TacticalReportExtraction:
        agg = TacticalReportExtraction(
            source_pdf=str(pdf_path),
            page_count=len(per_page),
            extracted_at=datetime.now().isoformat(),
            extraction_model=self.model,
            per_page_extractions=per_page,
        )
        # First valid page's title becomes the report title
        for page in per_page:
            if page.get("_parse_error"):
                continue
            if not agg.title and page.get("title"):
                agg.title = str(page["title"])
            for field_name in (
                "player_stats",
                "tactical_themes",
                "coach_quotes",
                "matchup_advantages",
                "key_plays",
            ):
                items = page.get(field_name) or []
                if isinstance(items, list):
                    for item in items:
                        if isinstance(item, dict):
                            item.setdefault("page", page.get("page"))
                    getattr(agg, field_name).extend(items)
        # De-duplicate trivially-identical player_stats by player name
        seen_players: set[str] = set()
        unique_players: list[dict[str, Any]] = []
        for ps in agg.player_stats:
            name = str(ps.get("player", "")).strip()
            if name and name not in seen_players:
                seen_players.add(name)
                unique_players.append(ps)
        agg.player_stats = unique_players
        # Synthesize a brief summary from collected themes if missing
        if not agg.summary:
            theme_names = [t.get("name") for t in agg.tactical_themes if t.get("name")][:5]
            if theme_names:
                agg.summary = "本报告主要涵盖战术：" + "、".join(theme_names)
        return agg

    def read(
        self, pdf_path: Path, pages: list[int] | None = None
    ) -> TacticalReportExtraction:
        rendered = self.render_pages(pdf_path, pages=pages)
        if not rendered:
            raise RuntimeError(f"no pages rendered from {pdf_path} (range={pages})")
        total = len(rendered)
        per_page = []
        for i, (page_num, png) in enumerate(rendered, 1):
            print(f"  [reader] page {page_num} ({i}/{total}) ...", file=sys.stderr, flush=True)
            data = self.extract_page(page_num, total, png)
            per_page.append(data)
        return self.aggregate(pdf_path, per_page)


# ---------- High-level entry ----------
def extract_pdf_to_court_report(
    pdf_path: str | Path,
    output_path: str | Path | None = None,
    pages: list[int] | None = None,
    model: str | None = None,
) -> TacticalReportExtraction:
    """One-shot helper: PDF -> JSON file consumable as court_report_context."""
    reader = PDFTacticalReader(model=model or "")
    extraction = reader.read(Path(pdf_path), pages=pages)
    if output_path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(extraction.to_dict(), ensure_ascii=False, indent=2)
        tmp = out.with_suffix(out.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(out)
        print(f"[reader] wrote {out}", file=sys.stderr)
    return extraction


# ---------- Helpers ----------
def _parse_page_range(s: str) -> list[int]:
    """Parse '1-5,7,10-12' into [1,2,3,4,5,7,10,11,12]."""
    out: list[int] = []
    for part in s.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            out.extend(range(int(a), int(b) + 1))
        elif part:
            out.append(int(part))
    return out


def _load_env() -> None:
    env_path = Path(".env")
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k, v)


def main() -> None:
    ap = argparse.ArgumentParser(description="Extract tactical info from a PDF scouting report.")
    ap.add_argument("--pdf", required=True, help="Path to PDF file")
    ap.add_argument("--output", default="", help="Output JSON path (default: <pdf_stem>_court_report.json)")
    ap.add_argument("--pages", default="", help="Page range, e.g. '1-5,7' (default: all pages)")
    ap.add_argument("--model", default="", help="Vision LLM model id (default from LLM_MODEL_VISION env)")
    ap.add_argument("--dpi", type=int, default=200, help="PDF page render DPI (default 200)")
    args = ap.parse_args()

    _load_env()
    pdf_path = Path(args.pdf).expanduser().resolve()
    if not pdf_path.exists():
        print(f"[error] PDF not found: {pdf_path}", file=sys.stderr)
        sys.exit(1)

    pages = _parse_page_range(args.pages) if args.pages else None
    output = args.output or str(pdf_path.with_name(pdf_path.stem + "_court_report.json"))

    extraction = extract_pdf_to_court_report(
        pdf_path=pdf_path, output_path=output, pages=pages, model=args.model or None,
    )

    print()
    print("=" * 60)
    print("PDF Tactical Reader  -  Extraction Summary")
    print("-" * 60)
    print(f"  source PDF:        {extraction.source_pdf}")
    print(f"  pages processed:   {extraction.page_count}")
    print(f"  title:             {extraction.title}")
    print(f"  player stats:      {len(extraction.player_stats)}")
    print(f"  tactical themes:   {len(extraction.tactical_themes)}")
    print(f"  coach quotes:      {len(extraction.coach_quotes)}")
    print(f"  matchup advs:      {len(extraction.matchup_advantages)}")
    print(f"  key plays:         {len(extraction.key_plays)}")
    print(f"  parse errors:      {sum(1 for p in extraction.per_page_extractions if p.get('_parse_error'))}")
    print("=" * 60)


if __name__ == "__main__":
    main()
