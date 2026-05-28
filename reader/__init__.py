"""Reader module — extracts tactical intelligence from professional basketball
scouting reports, coaching manuals, and other PDF documents using vision LLMs.

This was a core deliverable of the original DSAI5902 dissertation proposal
("Phase 2: Enhanced Reader Development"). It complements the NBA Live API
ingestion path: when the structured PBP feed is unavailable, or when the
user wants to enrich post-game content with insights from a coaching
report, the Reader extracts player stats, tactical diagrams, and coach
commentary as structured JSON that the existing Content Agent can consume
as `court_report_context`.
"""

from reader.pdf_tactical_reader import (  # noqa: F401
    PDFTacticalReader,
    TacticalReportExtraction,
    extract_pdf_to_court_report,
)
