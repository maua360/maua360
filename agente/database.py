"""Persistência em SQLite para evitar processar/publicar a mesma notícia duas vezes."""
from __future__ import annotations

import hashlib
import logging
import re
import sqlite3
import unicodedata
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    url_hash     TEXT NOT NULL UNIQUE,
    title_hash   TEXT NOT NULL,
    url          TEXT NOT NULL,
    title        TEXT NOT NULL,
    source       TEXT NOT NULL,
    status       TEXT NOT NULL,          -- descartada | rascunho | erro
    score        INTEGER DEFAULT 0,
    wp_post_id   INTEGER,
    error        TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_articles_title_hash ON articles(title_hash);
"""

_TRACKING_PARAMS = re.compile(r"^(utm_|fbclid|gclid|mc_|ref$)")


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query) if not _TRACKING_PARAMS.match(k)]
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), urlencode(query), "")
    )


def normalize_title(title: str) -> str:
    """Minúsculas, sem acento e sem pontuação: pega a mesma pauta vinda de fontes diferentes."""
    t = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-z0-9 ]", " ", t.lower())
    return re.sub(r"\s+", " ", t).strip()


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self._conn() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def is_known(self, url: str, title: str) -> bool:
        """True se a URL ou um título equivalente já foi visto (exceto falhas, que podem ser refeitas)."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT status FROM articles WHERE url_hash = ? OR title_hash = ? LIMIT 1",
                (_sha(normalize_url(url)), _sha(normalize_title(title))),
            ).fetchone()
        return row is not None and row["status"] != "erro"

    def record(
        self,
        url: str,
        title: str,
        source: str,
        status: str,
        score: int = 0,
        wp_post_id: int | None = None,
        error: str | None = None,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO articles (url_hash, title_hash, url, title, source, status, score, wp_post_id, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(url_hash) DO UPDATE SET
                    status = excluded.status, score = excluded.score,
                    wp_post_id = excluded.wp_post_id, error = excluded.error,
                    updated_at = datetime('now')
                """,
                (
                    _sha(normalize_url(url)),
                    _sha(normalize_title(title)),
                    url,
                    title,
                    source,
                    status,
                    score,
                    wp_post_id,
                    (error or "")[:1000] or None,
                ),
            )

    def stats(self) -> dict[str, int]:
        with self._conn() as conn:
            rows = conn.execute("SELECT status, COUNT(*) AS n FROM articles GROUP BY status").fetchall()
        return {r["status"]: r["n"] for r in rows}
