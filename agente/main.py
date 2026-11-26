"""Orquestrador: coleta -> deduplica -> filtra -> reescreve (Claude) -> rascunho no WordPress.

Uso:
    python main.py              # uma execução (ideal para cron)
    python main.py --loop       # roda a cada LOOP_INTERVAL_MINUTES
    python main.py --dry-run    # não chama o WordPress; salva o resultado em output/
    python main.py --check      # testa credenciais e fontes, sem gastar tokens
"""
from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import time
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler

from ai_writer import AIWriter, AIWriterError, unverified_numbers
from config import BASE_DIR, settings
from database import Database, normalize_title
from relevance import is_maua, is_politics, is_relevant
from scraper import MIN_TEXT_CHARS, Scraper
from github_publisher import GitHubPublisher
from wp_publisher import WordPressPublisher, WPError

log = logging.getLogger("agente")
_stop = False


def setup_logging() -> None:
    settings.log_file.parent.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    file_handler = RotatingFileHandler(settings.log_file, maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    file_handler.setFormatter(fmt)
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(settings.log_level)
    root.handlers[:] = [file_handler, console]
    for noisy in ("urllib3", "httpx", "anthropic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def make_publisher():
    if settings.publisher == "wordpress":
        return WordPressPublisher(
            settings.wp_url, settings.wp_user, settings.wp_app_password,
            settings.wp_create_missing_terms, settings.request_timeout, settings.user_agent)
    return GitHubPublisher(settings.github_repo, settings.github_token, settings.github_base_branch,
                           settings.request_timeout, settings.user_agent)


def run_once(dry_run: bool = False) -> dict[str, int]:
    counts = {"coletadas": 0, "duplicadas": 0, "antigas": 0, "irrelevantes": 0,
              "curtas": 0, "rascunhos": 0, "erros": 0}
    db = Database(settings.db_path)
    scraper = Scraper(settings.user_agent, settings.request_timeout)
    writer = AIWriter(settings.anthropic_api_key, settings.claude_model,
                      settings.claude_effort, settings.claude_fallback)
    publisher = None if dry_run else make_publisher()

    articles = scraper.collect(settings.load_sources())
    counts["coletadas"] = len(articles)
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=settings.max_age_hours)
              if settings.max_age_hours else None)
    processed = 0
    abc_used = 0
    politica_used = 0

    # 1ª passada (sem gastar tokens): filtra e separa pautas de Mauá das do resto do ABC.
    candidates = []
    seen_titles: set[str] = set()   # várias buscas do Google trazem a mesma matéria
    for art in articles:
        if _stop:
            break
        if db.is_known(art.url, art.title):
            counts["duplicadas"] += 1
            continue
        key = normalize_title(art.title)
        if key in seen_titles:
            counts["duplicadas"] += 1
            continue
        seen_titles.add(key)
        if cutoff and art.published and art.published < cutoff:
            counts["antigas"] += 1
            continue

        # 1º filtro só com título+resumo (barato, sem baixar a página). Links do Google Notícias não ganham segunda chance: abrir cada um custa duas chamadas ao Google.
        ok, score, hits = is_relevant(art.title, art.summary, settings.min_relevance_score, art.trust_region)
        national = art.extra.get("source_cfg", {}).get("nacional", False)
        # Páginas raspadas (type=html) não ganham segunda chance: o "texto" delas pode
        # incluir a barra lateral com manchetes de Mauá e deixar passar qualquer matéria.
        is_html = art.extra.get("source_cfg", {}).get("type") == "html"
        if not ok and not art.trust_region and not national and not is_html and "news.google." not in art.url:
            # Dá uma segunda chance com o texto completo, que pode citar Mauá só no corpo.
            scraper.enrich(art)
            ok, score, hits = is_relevant(art.title, art.text, settings.min_relevance_score, art.trust_region)
        # Política nacional/estadual vale de qualquer fonte (inclusive o governo de SP
        # republicado por sites de Mauá), mas entra depois das pautas locais.
        if not ok and is_politics(art.title, art.summary, art.url):
            candidates.append((2, 0, art, ["politica"]))
            continue
        if not ok:
            counts["irrelevantes"] += 1
            db.record(art.url, art.title, art.source, "descartada", score)
            log.debug("Descartada (%s): %s", score, art.title)
            continue
        candidates.append((0 if is_maua(hits, art.trust_region) else 1, score, art, hits))

    # Ordem: Mauá (0), resto do ABC (1), política nacional/SP (2); maior nota antes.
    # ABC e política só completam as vagas, até MAX_ABC_PER_RUN e MAX_POLITICA_PER_RUN.
    candidates.sort(key=lambda c: (c[0], -c[1]))
    # Vaga fixa: as primeiras MIN_POLITICA_PER_RUN matérias de política vão para a frente,
    # para entrarem mesmo quando a fila de Mauá está cheia.
    reserved = [c for c in candidates if c[0] == 2][:settings.min_politica_per_run]
    candidates = reserved + [c for c in candidates if c not in reserved]
    log.info("Candidatas: %d de Mauá, %d do Grande ABC, %d de política Brasil/SP",
             *(sum(1 for c in candidates if c[0] == t) for t in (0, 1, 2)))

    for tier, score, art, hits in candidates:
        if _stop or processed >= settings.max_articles_per_run:
            break
        # Pautas que não cabem nesta rodada não são registradas: podem entrar numa próxima.
        if tier == 1:
            if abc_used >= settings.max_abc_per_run:
                continue
            abc_used += 1
        elif tier == 2:
            if politica_used >= settings.max_politica_per_run:
                continue
            politica_used += 1

        scraper.enrich(art)
        if len(art.text) < MIN_TEXT_CHARS:
            counts["curtas"] += 1
            db.record(art.url, art.title, art.source, "descartada", score, error="texto insuficiente")
            log.info("Texto insuficiente para reescrever: %s", art.title)
            continue

        processed += 1
        log.info("Relevante (score=%s, %s): %s", score, ", ".join(hits[:5]), art.title)
        try:
            news = writer.rewrite(art.title, art.text, art.source, art.url)
            if tier == 2:
                news.categoria = "Política"
            suspicious = unverified_numbers(news.conteudo_html, art.text)
            note = f"números não encontrados na fonte: {', '.join(suspicious)}" if suspicious else None
            if note:
                log.warning("Checar antes de publicar (%s): %s", art.title, note)

            if dry_run:
                out_dir = BASE_DIR / "output"
                out_dir.mkdir(exist_ok=True)
                out = out_dir / f"{datetime.now():%Y%m%d-%H%M%S}-{processed}.json"
                out.write_text(json.dumps({**news.model_dump(), "fonte": art.url, "revisar": note},
                                          ensure_ascii=False, indent=2), encoding="utf-8")
                log.info("[dry-run] salvo em %s", out)
                post_id = None
            else:
                post = publisher.create_draft(news.titulo, news.subtitulo, news.conteudo_html,
                                              news.categoria, news.tags, art.source, art.url, note,
                                              busca_foto=getattr(news, "busca_foto", ""))
                post_id = post["id"]
                if post.get("duplicada"):
                    db.record(art.url, art.title, art.source, "descartada", score, error="pauta já enviada")
                    continue
            db.record(art.url, art.title, art.source, "rascunho", score, wp_post_id=post_id)
            counts["rascunhos"] += 1
        except (AIWriterError, WPError) as exc:
            counts["erros"] += 1
            db.record(art.url, art.title, art.source, "erro", score, error=str(exc))
            log.error("Falha em '%s': %s", art.title, exc)
        except Exception as exc:  # noqa: BLE001
            counts["erros"] += 1
            db.record(art.url, art.title, art.source, "erro", score, error=repr(exc))
            log.exception("Erro inesperado em '%s'", art.title)

    log.info("Resumo da execução: %s", counts)
    return counts


def check() -> int:
    ok = True
    log.info("Modelo configurado: %s (effort=%s)", settings.claude_model, settings.claude_effort)
    if not settings.anthropic_api_key:
        log.error("ANTHROPIC_API_KEY ausente"); ok = False
    try:
        pub = make_publisher()
        log.info("Publicador '%s' OK: %s", settings.publisher, pub.check_auth())
    except Exception as exc:  # noqa: BLE001
        log.error("Publicador '%s': %s", settings.publisher, exc); ok = False
    scraper = Scraper(settings.user_agent, settings.request_timeout)
    for src in settings.load_sources():
        items = scraper.collect([src])
        if not items:
            ok = False
            log.warning("Fonte sem itens: %s -> ajuste url/seletores em sources.json", src["name"])
        else:
            log.info("  ex.: %s", items[0].title[:90])
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Agente de notícias de Mauá e Grande ABC")
    parser.add_argument("--loop", action="store_true", help="executa continuamente")
    parser.add_argument("--dry-run", action="store_true", help="não envia ao WordPress")
    parser.add_argument("--check", action="store_true", help="testa credenciais e fontes")
    args = parser.parse_args()
    setup_logging()

    if args.check:
        return check()

    def _handle(sig, _frame):
        global _stop
        _stop = True
        log.info("Sinal %s recebido, encerrando após a matéria atual...", sig)
    signal.signal(signal.SIGINT, _handle)
    signal.signal(signal.SIGTERM, _handle)

    if not args.loop:
        counts = run_once(args.dry_run)
        return 1 if counts["erros"] and not counts["rascunhos"] else 0

    while not _stop:
        try:
            run_once(args.dry_run)
        except Exception:  # noqa: BLE001 - o loop não pode morrer
            log.exception("Execução falhou; tentando de novo no próximo ciclo")
        for _ in range(settings.loop_interval_minutes * 60):
            if _stop:
                break
            time.sleep(1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
