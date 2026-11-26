"""Coleta de notícias via RSS (feedparser) e raspagem HTML (requests + BeautifulSoup)."""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable
from urllib.parse import urljoin

import feedparser
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)

MIN_TEXT_CHARS = 300          # abaixo disso o texto é considerado insuficiente para reescrever
MAX_TEXT_CHARS = 20_000       # limite de segurança de custo por matéria
JUNK_SELECTORS = "script, style, noscript, iframe, form, nav, footer, header, aside, figure figcaption, .share, .social, .compartilhe, .related, .relacionadas, .publicidade, .ads"


@dataclass
class Article:
    title: str
    url: str
    source: str
    summary: str = ""
    content: str = ""
    published: datetime | None = None
    trust_region: bool = False     # fonte é, por natureza, de Mauá (Prefeitura/Câmara)
    image_url: str | None = None
    extra: dict = field(default_factory=dict)

    @property
    def text(self) -> str:
        """Melhor texto disponível: corpo completo ou, na falta, o resumo."""
        return self.content if len(self.content) >= len(self.summary) else self.summary


class Scraper:
    def __init__(self, user_agent: str, timeout: int = 20):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": user_agent, "Accept-Language": "pt-BR,pt;q=0.9"}
        )
        retry = Retry(total=3, backoff_factor=1.5, status_forcelist=(429, 500, 502, 503, 504))
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.mount("http://", HTTPAdapter(max_retries=retry))

    # ------------------------------------------------------------------ util
    def _get(self, url: str) -> requests.Response:
        resp = self.session.get(url, timeout=self.timeout)
        resp.raise_for_status()
        if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
            resp.encoding = resp.apparent_encoding
        return resp

    @staticmethod
    def clean_text(html_or_text: str) -> str:
        soup = BeautifulSoup(html_or_text or "", "lxml")
        text = soup.get_text("\n", strip=True)
        return re.sub(r"\n{3,}", "\n\n", text).strip()

    # ------------------------------------------------------------- full text
    def fetch_full_text(self, url: str, selector: str | None = None) -> tuple[str, str | None]:
        """Baixa a página da matéria e devolve (texto_limpo, url_da_imagem)."""
        resp = self._get(url)
        soup = BeautifulSoup(resp.text, "lxml")

        image = None
        og = soup.find("meta", property="og:image")
        if og and og.get("content"):
            image = og["content"]

        for junk in soup.select(JUNK_SELECTORS):
            junk.decompose()

        container = None
        if selector:
            for sel in selector.split(","):
                found = soup.select_one(sel.strip())
                if found and len(found.get_text(strip=True)) > MIN_TEXT_CHARS:
                    container = found
                    break
        if container is None:
            container = self._densest_block(soup)

        paragraphs = [
            p.get_text(" ", strip=True)
            for p in container.find_all(["p", "li", "h2", "h3"])
            if len(p.get_text(strip=True)) > 30
        ] if container else []
        text = "\n\n".join(paragraphs) or (container.get_text("\n", strip=True) if container else "")
        return text[:MAX_TEXT_CHARS], image

    @staticmethod
    def _densest_block(soup: BeautifulSoup):
        """Heurística: o elemento com mais texto em <p> diretos costuma ser o corpo da matéria."""
        best, best_len = None, 0
        for node in soup.find_all(["article", "main", "section", "div"]):
            length = sum(len(p.get_text(strip=True)) for p in node.find_all("p", recursive=False))
            if length > best_len:
                best, best_len = node, length
        return best or soup.body

    # ------------------------------------------------------------------- RSS
    def collect_rss(self, source: dict) -> list[Article]:
        resp = self._get(source["url"])
        feed = feedparser.parse(resp.content)
        if feed.bozo and not feed.entries:
            raise ValueError(f"Feed inválido: {feed.bozo_exception}")

        articles = []
        for entry in feed.entries:
            link = entry.get("link")
            title = self.clean_text(entry.get("title", ""))
            if not link or not title:
                continue
            published = None
            for key in ("published_parsed", "updated_parsed"):
                if entry.get(key):
                    published = datetime.fromtimestamp(time.mktime(entry[key]), tz=timezone.utc)
                    break
            body_html = ""
            if entry.get("content"):
                body_html = entry.content[0].get("value", "")
            articles.append(
                Article(
                    title=title,
                    url=link,
                    source=source["name"],
                    summary=self.clean_text(entry.get("summary", "")),
                    content=self.clean_text(body_html),
                    published=published,
                    trust_region=source.get("trust_region", False),
                )
            )
        return articles

    # ------------------------------------------------------------------ HTML
    def collect_html(self, source: dict, limit: int = 20) -> list[Article]:
        resp = self._get(source["url"])
        soup = BeautifulSoup(resp.text, "lxml")
        base = source.get("base_url", source["url"])
        seen, articles = set(), []
        for a in soup.select(source.get("link_selector", "article a")):
            href = a.get("href")
            title = a.get_text(" ", strip=True) or a.get("title", "")
            if not href or len(title) < 15:
                continue
            url = urljoin(base, href)
            if url in seen:
                continue
            seen.add(url)
            articles.append(
                Article(
                    title=title,
                    url=url,
                    source=source["name"],
                    trust_region=source.get("trust_region", False),
                )
            )
            if len(articles) >= limit:
                break
        return articles

    # -------------------------------------------------------------- entrada
    def collect(self, sources: Iterable[dict]) -> list[Article]:
        """Coleta todas as fontes. Uma fonte com erro não interrompe as demais."""
        all_articles: list[Article] = []
        for source in sources:
            try:
                kind = source.get("type", "rss")
                items = self.collect_rss(source) if kind == "rss" else self.collect_html(source)
                for art in items:
                    art.extra["source_cfg"] = source
                log.info("Fonte %-28s -> %d itens", source["name"], len(items))
                all_articles.extend(items)
            except Exception as exc:  # noqa: BLE001 - registrar e seguir
                log.error("Falha ao coletar %s (%s): %s", source.get("name"), source.get("url"), exc)
        return all_articles

    def enrich(self, article: Article) -> Article:
        """Busca o texto completo quando o feed só traz resumo."""
        cfg = article.extra.get("source_cfg", {})
        if not cfg.get("fetch_full_text", True) or len(article.content) >= MIN_TEXT_CHARS:
            return article
        try:
            text, image = self.fetch_full_text(article.url, cfg.get("content_selector"))
            if len(text) > len(article.content):
                article.content = text
            article.image_url = article.image_url or image
        except Exception as exc:  # noqa: BLE001
            log.warning("Não foi possível baixar o texto completo de %s: %s", article.url, exc)
        return article
