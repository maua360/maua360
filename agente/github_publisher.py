"""Publicação no site estático (Cloudflare Pages) via GitHub.

Cada matéria vira um arquivo content/posts/<data>-<slug>.json num branch próprio e um
Pull Request. O Cloudflare Pages gera um link de prévia para cada PR; aprovar = clicar em
"Merge" (pelo site ou pelo app do GitHub). Fechar o PR sem merge = descartar.
"""
from __future__ import annotations

import base64
import json
import logging
import re
import unicodedata
from datetime import datetime, timedelta, timezone

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from wp_publisher import WPError

log = logging.getLogger(__name__)
BRT = timezone(timedelta(hours=-3))
API = "https://api.github.com"


class GitHubError(WPError):
    """Herda de WPError para o main.py tratar os dois publicadores do mesmo jeito."""


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:80] or "materia"


class GitHubPublisher:
    def __init__(self, repo: str, token: str, base_branch: str = "main",
                 timeout: int = 20, user_agent: str = ""):
        if not (repo and token):
            raise GitHubError("GITHUB_REPO e GITHUB_TOKEN precisam estar no .env")
        self.repo = repo
        self.base = base_branch
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": user_agent or "maua360-agente",
        })
        retry = Retry(total=3, backoff_factor=2, status_forcelist=(429, 500, 502, 503, 504),
                      allowed_methods=frozenset({"GET", "POST", "PUT"}))
        self.session.mount("https://", HTTPAdapter(max_retries=retry))

    def _req(self, method: str, path: str, **kw) -> dict:
        resp = self.session.request(method, f"{API}/repos/{self.repo}{path}", timeout=self.timeout, **kw)
        if resp.status_code in (401, 403):
            raise GitHubError(f"Sem permissão no GitHub ({resp.status_code}): {resp.text[:300]}")
        if not resp.ok:
            raise GitHubError(f"{method} {path} -> {resp.status_code}: {resp.text[:300]}")
        return resp.json() if resp.content else {}

    def check_auth(self) -> str:
        info = self._req("GET", "")
        perms = info.get("permissions")
        if perms is not None and not perms.get("push"):
            raise GitHubError("O token não tem permissão de escrita no repositório")
        return info["full_name"]

    def create_draft(self, titulo: str, subtitulo: str, conteudo_html: str, categoria: str,
                     tags: list[str], source_name: str, source_url: str,
                     review_note: str | None = None, busca_foto: str = "") -> dict:
        now = datetime.now(BRT).replace(microsecond=0)
        slug = slugify(titulo)
        # Branch sem horário: a mesma pauta nunca gera dois PRs, mesmo se o
        # histórico local (SQLite) se perder entre execuções do GitHub Actions.
        branch = f"rascunho/{slug[:60]}"
        path = f"content/posts/{now:%Y-%m-%d}-{slug}.json"
        post = {
            "titulo": titulo,
            "subtitulo": subtitulo,
            "categoria": categoria,
            "tags": tags,
            "data": now.isoformat(),
            "slug": slug,
            "autor": "Redação",
            "status": "publicado",
            "fonte_nome": source_name,
            "fonte_url": source_url,
            "conteudo_html": conteudo_html,
        }
        if busca_foto:
            post["busca_foto"] = busca_foto  # usado pelo redes/publicar.py para achar a foto

        base_sha = self._req("GET", f"/git/ref/heads/{self.base}")["object"]["sha"]
        resp = self.session.post(f"{API}/repos/{self.repo}/git/refs", timeout=self.timeout,
                                 json={"ref": f"refs/heads/{branch}", "sha": base_sha})
        if resp.status_code == 422 and "already exists" in resp.text:
            log.info("Rascunho já existe (branch %s), pulando: %s", branch, titulo)
            return {"id": None, "link": None, "duplicada": True}
        if not resp.ok:
            raise GitHubError(f"Criar branch -> {resp.status_code}: {resp.text[:300]}")
        content = json.dumps(post, ensure_ascii=False, indent=2) + "\n"
        self._req("PUT", f"/contents/{path}", json={
            "message": f"Rascunho: {titulo}",
            "content": base64.b64encode(content.encode("utf-8")).decode(),
            "branch": branch,
        })

        body = [f"**{categoria}** · {subtitulo}", "",
                f"Fonte: [{source_name}]({source_url})", ""]
        if review_note:
            body += [f"> ⚠️ **REVISAR:** {review_note}", ""]
        body += ["Para publicar: confira a prévia do Cloudflare Pages abaixo e clique em **Merge**.",
                 "Para corrigir: edite o arquivo .json na aba *Files changed* (lápis) antes do merge.",
                 "Para descartar: **Close pull request**."]
        pr = self._req("POST", "/pulls", json={
            "title": ("⚠️ " if review_note else "") + titulo,
            "head": branch, "base": self.base, "body": "\n".join(body),
        })
        log.info("Rascunho criado: PR #%s %s", pr["number"], pr["html_url"])
        return {"id": pr["number"], "link": pr["html_url"]}
