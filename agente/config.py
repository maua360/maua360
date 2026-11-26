"""Configuração central: lê o .env e expõe valores tipados."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "sim", "yes", "on"}


def _path(name: str, default: str) -> Path:
    p = Path(os.getenv(name, default))
    return p if p.is_absolute() else BASE_DIR / p


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    claude_model: str = os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")
    claude_effort: str = os.getenv("CLAUDE_EFFORT", "medium")
    claude_fallback: bool = _bool("CLAUDE_FALLBACK", True)

    wp_url: str = os.getenv("WP_URL", "").rstrip("/")
    wp_user: str = os.getenv("WP_USER", "")
    wp_app_password: str = os.getenv("WP_APP_PASSWORD", "")
    wp_create_missing_terms: bool = _bool("WP_CREATE_MISSING_TERMS", True)

    # "github" (site estático Mauá 360) ou "wordpress"
    publisher: str = os.getenv("PUBLISHER", "github").strip().lower()
    github_repo: str = os.getenv("GITHUB_REPO", "")
    github_token: str = os.getenv("GITHUB_TOKEN", "")
    github_base_branch: str = os.getenv("GITHUB_BASE_BRANCH", "main")

    db_path: Path = _path("DB_PATH", "data/noticias.db")
    sources_file: Path = _path("SOURCES_FILE", "sources.json")
    log_file: Path = _path("LOG_FILE", "logs/agente.log")
    log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()

    max_articles_per_run: int = int(os.getenv("MAX_ARTICLES_PER_RUN", "10"))
    # Quantas pautas só do Grande ABC (sem Mauá) podem entrar por rodada, para completar.
    max_abc_per_run: int = int(os.getenv("MAX_ABC_PER_RUN", "1"))
    max_politica_per_run: int = int(os.getenv("MAX_POLITICA_PER_RUN", "2"))
    min_relevance_score: int = int(os.getenv("MIN_RELEVANCE_SCORE", "3"))
    max_age_hours: int = int(os.getenv("MAX_AGE_HOURS", "48"))
    loop_interval_minutes: int = int(os.getenv("LOOP_INTERVAL_MINUTES", "30"))
    request_timeout: int = int(os.getenv("REQUEST_TIMEOUT", "20"))
    user_agent: str = os.getenv(
        "USER_AGENT", "PortalMauaBot/1.0 (+https://example.com/contato)"
    )

    def load_sources(self) -> list[dict]:
        with open(self.sources_file, encoding="utf-8") as fh:
            data = json.load(fh)
        return [s for s in data.get("sources", []) if s.get("enabled", True)]


settings = Settings()
