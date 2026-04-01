"""PDF ingestion module for extracting scouting report content."""

import json
import os
import sys
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium
from openai import OpenAI
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from config import DEEPSEEK_API_KEY, BASE_URL, CHAT_MODEL, MAX_TOKENS, OUTPUT_DIR


SYSTEM_PROMPT = """你是专业篮球分析师。从以下篮球球探报告文字中提取所有信息。
只返回JSON对象，不要其他文字，格式如下：
{
  "players": [{"name": "", "stats": "", "notes": ""}],
  "tactics": [{"name": "", "description": "", "diagram_description": ""}],
  "quotes": [""],
  "matchup_notes": [{"team": "", "advantage": "", "disadvantage": ""}],
  "raw_text": ""
}"""


class PDFReader:
    """Loads PDFs, extracts text per page, sends to DeepSeek for structured analysis."""

    def __init__(self, pdf_path: str) -> None:
        self.pdf_path = pdf_path
        if not os.path.isfile(self.pdf_path):
            raise FileNotFoundError(f"PDF file not found: {self.pdf_path}")
        if Path(self.pdf_path).suffix.lower() != ".pdf":
            raise ValueError(f"Input file is not a PDF: {self.pdf_path}")
        if not DEEPSEEK_API_KEY:
            raise ValueError("DEEPSEEK_API_KEY is missing. Set it in your .env file.")
        self.client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=BASE_URL)

    def extract_text_pages(self) -> list[str]:
        """Extract raw text from each page using pypdfium2."""
        pages_text = []
        pdf = pdfium.PdfDocument(self.pdf_path)
        try:
            for i in range(len(pdf)):
                page = pdf[i]
                textpage = page.get_textpage()
                text = textpage.get_text_range()
                pages_text.append(text.strip())
                textpage.close()
                page.close()
        finally:
            pdf.close()
        return pages_text

    def extract_page(self, page_text: str) -> dict[str, Any]:
        """Send page text to DeepSeek and parse structured response."""
        if not page_text:
            return {"players": [], "tactics": [], "quotes": [], "matchup_notes": [], "raw_text": ""}
        try:
            response = self.client.chat.completions.create(
                model=CHAT_MODEL,
                max_tokens=MAX_TOKENS,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"请分析以下球探报告内容：\n\n{page_text}"}
                ]
            )
            raw_text = response.choices[0].message.content.strip()
        except Exception as exc:
            raise RuntimeError(f"DeepSeek API call failed: {exc}") from exc

        if raw_text.startswith("```"):
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]

        try:
            parsed = json.loads(raw_text)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

        return {"players": [], "tactics": [], "quotes": [], "matchup_notes": [], "raw_text": raw_text}

    def extract_full_report(self) -> dict[str, Any]:
        """Extract all pages and merge into one report dict."""
        pages_text = self.extract_text_pages()
        merged: dict[str, Any] = {
            "players": [],
            "tactics": [],
            "quotes": [],
            "matchup_notes": [],
            "source_file": os.path.basename(self.pdf_path),
            "page_count": len(pages_text),
        }
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
        ) as progress:
            task_id = progress.add_task("Extracting pages", total=len(pages_text))
            for page_text in pages_text:
                page_data = self.extract_page(page_text)
                merged["players"].extend(page_data.get("players", []))
                merged["tactics"].extend(page_data.get("tactics", []))
                merged["quotes"].extend(page_data.get("quotes", []))
                merged["matchup_notes"].extend(page_data.get("matchup_notes", []))
                progress.update(task_id, advance=1)
        return merged

    def save_json(self, data: dict[str, Any], output_path: str) -> None:
        output_dir = os.path.dirname(output_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python -m reader.pdf_reader <pdf_path>")
    input_pdf = sys.argv[1]
    reader = PDFReader(input_pdf)
    report = reader.extract_full_report()
    output_name = f"{Path(input_pdf).stem}.json"
    output_path = os.path.join(OUTPUT_DIR, output_name)
    reader.save_json(report, output_path)
    print(f"\n✅ 提取完成，已保存至：{output_path}")