"""Publicação no WordPress via REST API com Application Passwords (status draft)."""
from __future__ import annotations

import html
import logging

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)


class WPError(Exception):
    pass


class WordPressPublisher:
    def __init__(self, base_url: str, user: str, app_password: str,
                 create_missing_terms: bool = True, timeout: int = 20, user_agent: str = ""):
        if not (base_url and user and app_password):
            raise WPError("WP_URL, WP_USER e WP_APP_PASSWORD precisam estar no .env")
        self.api = f"{base_url.rstrip('/')}/wp-json/wp/v2"
        self.timeout = timeout
        self.create_missing_terms = create_missing_terms
        self.session = requests.Session()
        # Application Password aceita os espaços, mas removê-los evita erro de colagem.
        self.session.auth = (user, app_password.replace(" ", ""))
        self.session.headers.update({"Accept": "application/json"})
        if user_agent:
            self.session.headers["User-Agent"] = user_agent
        retry = Retry(total=3, backoff_factor=2, status_forcelist=(429, 500, 502, 503, 504),
                      allowed_methods=frozenset({"GET", "POST"}))
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.mount("http://", HTTPAdapter(max_retries=retry))
        self._term_cache: dict[tuple[str, str], int] = {}

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        resp = self.session.request(method, f"{self.api}{path}", timeout=self.timeout, **kwargs)
        if resp.status_code in (401, 403):
            raise WPError(f"Sem permissão no WordPress ({resp.status_code}): {resp.text[:300]}")
        if not resp.ok:
            raise WPError(f"{method} {path} -> {resp.status_code}: {resp.text[:300]}")
        return resp

    def check_auth(self) -> str:
        """Confirma as credenciais e retorna o nome do usuário autenticado."""
        me = self._request("GET", "/users/me", params={"context": "edit"}).json()
        return me.get("name", "?")

    def _term_id(self, taxonomy: str, name: str) -> int | None:
        key = (taxonomy, name.lower())
        if key in self._term_cache:
            return self._term_cache[key]
        results = self._request("GET", f"/{taxonomy}", params={"search": name, "per_page": 100}).json()
        for term in results:
            if html.unescape(term["name"]).lower() == name.lower():
                self._term_cache[key] = term["id"]
                return term["id"]
        if not self.create_missing_terms:
            log.warning("Termo '%s' não existe em %s e a criação está desativada", name, taxonomy)
            return None
        resp = self.session.post(f"{self.api}/{taxonomy}", json={"name": name}, timeout=self.timeout)
        if resp.status_code == 400 and resp.json().get("code") == "term_exists":
            term_id = resp.json()["data"]["term_id"]
        elif resp.ok:
            term_id = resp.json()["id"]
        else:
            raise WPError(f"Não foi possível criar '{name}' em {taxonomy}: {resp.text[:300]}")
        self._term_cache[key] = term_id
        log.info("Criado termo '%s' em %s (id=%s)", name, taxonomy, term_id)
        return term_id

    def create_draft(self, titulo: str, subtitulo: str, conteudo_html: str, categoria: str,
                     tags: list[str], source_name: str, source_url: str,
                     review_note: str | None = None) -> dict:
        credit = (
            f'<p class="fonte-original"><em>Com informações de '
            f'<a href="{html.escape(source_url)}" rel="nofollow noopener" target="_blank">'
            f"{html.escape(source_name)}</a>.</em></p>"
        )
        content = conteudo_html + "\n" + credit
        if review_note:
            # Comentário HTML: aparece no editor para o revisor, não no site.
            content = f"<!-- REVISAR: {html.escape(review_note)} -->\n" + content

        cat_id = self._term_id("categories", categoria)
        tag_ids = [tid for t in tags if (tid := self._term_id("tags", t))]

        payload = {
            "title": titulo,
            "excerpt": subtitulo,
            "content": content,
            "status": "draft",
            "categories": [cat_id] if cat_id else [],
            "tags": tag_ids,
        }
        post = self._request("POST", "/posts", json=payload).json()
        log.info("Rascunho criado: id=%s %s", post["id"], post.get("link"))
        return post
