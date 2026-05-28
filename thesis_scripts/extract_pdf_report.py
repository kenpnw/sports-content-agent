"""PDF tactical report → court_report JSON (proposal Reader module).

One-shot helper that demonstrates the proposal's Phase 2 deliverable:
extract structured tactical intelligence from a basketball scouting PDF
using vision LLM, save as court_report JSON that the existing post-game
pipeline can consume.

Usage (PowerShell, from repo root):

    python -m thesis_scripts.extract_pdf_report ^
        --pdf "data/pdfs/sas_okc_scout.pdf" ^
        --output "data/court_reports/sas_okc_scout.json"

Optional:
    --pages "1-5,7,10-12"     # only process specific pages
    --model claude-3-5-sonnet-20241022   # override vision model
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> None:
    from reader.pdf_tactical_reader import main as reader_main
    reader_main()


if __name__ == "__main__":
    main()
