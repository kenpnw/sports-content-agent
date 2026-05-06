from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from config import DATA_DIR, KNOWLEDGE_DB_PATH
from storage.file_store import ensure_dir


TEXT_RAG_ROOT = DATA_DIR / "knowledge"
TEXT_RAG_DOCS_DIR = TEXT_RAG_ROOT / "documents"


def _iso_now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _chunk_text(text: str, target_chars: int, overlap_chars: int, max_chunks: int) -> list[str]:
    cleaned = text.strip()
    if not cleaned:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(cleaned) and len(chunks) < max_chunks:
        end = min(len(cleaned), start + target_chars)
        chunks.append(cleaned[start:end].strip())
        if end >= len(cleaned):
            break
        start = max(0, end - overlap_chars)
    return [chunk for chunk in chunks if chunk]


def _read_text_file(path: Path) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gbk"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="ignore")


def _parse_document(path: Path) -> dict[str, Any]:
    raw = _read_text_file(path)
    lines = raw.splitlines()
    metadata: dict[str, Any] = {}
    body_start = 0
    for index, line in enumerate(lines[:12]):
        if ":" not in line:
            break
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if key in {"sport", "league", "source_type", "published_at", "teams", "uri", "title"}:
            metadata[key] = value
            body_start = index + 1
        else:
            break
    title = metadata.get("title") or next((line.strip("# ").strip() for line in lines if line.strip()), path.stem)
    body = "\n".join(lines[body_start:]).strip() if body_start else raw.strip()
    metadata.setdefault("sport", "NBA")
    metadata.setdefault("league", "NBA")
    metadata.setdefault("source_type", "internal_archive")
    metadata.setdefault("published_at", "")
    metadata.setdefault("teams", "")
    metadata.setdefault("uri", str(path))
    metadata.setdefault("title", title)
    return {"title": title, "body": body, "metadata": metadata}


class TextRagStore:
    def __init__(self, db_path: str = KNOWLEDGE_DB_PATH) -> None:
        self.db_path = Path(db_path)

    def initialize(self) -> None:
        ensure_dir(self.db_path.parent)
        ensure_dir(TEXT_RAG_DOCS_DIR)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS text_documents (
                    doc_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    sport TEXT NOT NULL,
                    league TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    published_at TEXT NOT NULL,
                    uri TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS text_documents_fts
                USING fts5(
                    doc_id UNINDEXED,
                    title,
                    body,
                    tokenize = 'unicode61'
                );
                """
            )

    def bootstrap_from_directory(
        self,
        docs_dir: Path = TEXT_RAG_DOCS_DIR,
        chunk_target: int = 900,
        overlap: int = 120,
        max_chunks_per_doc: int = 12,
    ) -> int:
        ensure_dir(docs_dir)
        ingested = 0
        for path in list(docs_dir.rglob("*.md")) + list(docs_dir.rglob("*.txt")):
            parsed = _parse_document(path)
            chunks = _chunk_text(parsed["body"], chunk_target, overlap, max_chunks_per_doc)
            if not chunks:
                continue
            for index, chunk in enumerate(chunks, start=1):
                doc_id = f"{path.stem}::chunk::{index}"
                title = parsed["title"] if len(chunks) == 1 else f"{parsed['title']} [chunk {index}]"
                metadata = dict(parsed["metadata"])
                metadata["chunk_index"] = index
                metadata["doc_path"] = str(path)
                self.ingest_document(
                    doc_id=doc_id,
                    title=title,
                    body=chunk,
                    sport=str(metadata.get("sport", "NBA")),
                    league=str(metadata.get("league", "NBA")),
                    source_type=str(metadata.get("source_type", "internal_archive")),
                    published_at=str(metadata.get("published_at", "")),
                    uri=str(metadata.get("uri", path)),
                    metadata=metadata,
                )
                ingested += 1
        return ingested

    def ingest_document(
        self,
        doc_id: str,
        title: str,
        body: str,
        sport: str,
        league: str,
        source_type: str,
        published_at: str,
        uri: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        meta_json = json.dumps(metadata or {}, ensure_ascii=False)
        with self._connect() as conn:
            conn.execute("DELETE FROM text_documents WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM text_documents_fts WHERE doc_id = ?", (doc_id,))
            conn.execute(
                """
                INSERT INTO text_documents (
                    doc_id, title, body, sport, league, source_type, published_at, uri, metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (doc_id, title, body, sport, league, source_type, published_at, uri, meta_json, _iso_now()),
            )
            conn.execute(
                """
                INSERT INTO text_documents_fts (doc_id, title, body)
                VALUES (?, ?, ?)
                """,
                (doc_id, title, body),
            )

    def search(
        self,
        query: str,
        sport: str = "NBA",
        limit: int = 4,
        source_types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        if not query.strip():
            return []
        tokens = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", query)
        if not tokens:
            return []
        fts_query = " OR ".join(f'"{token}"' for token in tokens[:8])
        filter_sql = "d.sport = ?"
        parameters: list[Any] = [sport]
        if source_types:
            filter_sql += " AND d.source_type IN ({})".format(",".join("?" for _ in source_types))
            parameters.extend(source_types)
        parameters.append(fts_query)
        parameters.append(limit)
        sql = f"""
            SELECT d.doc_id, d.title, d.body, d.source_type, d.published_at, d.uri, d.metadata_json,
                   bm25(text_documents_fts) AS score
            FROM text_documents_fts
            JOIN text_documents d ON d.doc_id = text_documents_fts.doc_id
            WHERE {filter_sql}
              AND text_documents_fts MATCH ?
            ORDER BY score
            LIMIT ?
        """
        with self._connect() as conn:
            rows = conn.execute(sql, parameters).fetchall()

        results = []
        for row in rows:
            body = str(row["body"])
            excerpt = body[:240] + ("..." if len(body) > 240 else "")
            results.append(
                {
                    "doc_id": row["doc_id"],
                    "title": row["title"],
                    "excerpt": excerpt,
                    "source_type": row["source_type"],
                    "published_at": row["published_at"],
                    "uri": row["uri"],
                    "score": round(float(row["score"]), 4),
                    "metadata": json.loads(row["metadata_json"] or "{}"),
                }
            )
        return results

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
