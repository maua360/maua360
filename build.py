#!/usr/bin/env python3
"""Gera o site estático do Mauá 360 em public/.

Só usa a biblioteca padrão do Python, para rodar no Cloudflare Pages sem instalar nada.

    python3 build.py            # gera public/
    python3 build.py --serve    # gera e abre em http://localhost:8000

Conteúdo:
  content/posts/*.json     matérias (o agente cria esses arquivos)
  content/paginas/*.html   páginas institucionais (primeira linha: <!-- titulo: Sobre -->)
  static/                  CSS, logo e imagens, copiados como estão
"""
from __future__ import annotations

import html
import json
import re
import shutil
import sys
import unicodedata
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "public"
SITE = json.loads((ROOT / "site.json").read_text(encoding="utf-8"))
BRT = timezone(timedelta(hours=-3))
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
         "agosto", "setembro", "outubro", "novembro", "dezembro"]
ESC = html.escape
# Contato para pautas: WhatsApp se houver número em site.json, senão e-mail da redação.
PAUTA_URL = (f"https://wa.me/{SITE['whatsapp']}" if SITE.get("whatsapp")
             else f"mailto:{SITE['email_redacao']}")
PAUTA_CANAL = "WhatsApp" if SITE.get("whatsapp") else "e-mail"


# ----------------------------------------------------------------- utilidades
def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:80] or "materia"


def parse_date(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=BRT)


def data_extenso(dt: datetime) -> str:
    dt = dt.astimezone(BRT)
    return f"{dt.day} de {MESES[dt.month - 1]} de {dt.year}, {dt:%Hh%M}"


def plain(html_text: str, limit: int = 160) -> str:
    text = re.sub(r"<[^>]+>", " ", html_text)
    text = re.sub(r"\s+", " ", html.unescape(text)).strip()
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + "…"


def write(path: str, content: str) -> None:
    dest = OUT / path.lstrip("/")
    if path.endswith("/") or not dest.suffix:
        dest = dest / "index.html"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(content, encoding="utf-8")


EDITORIAS = {e["nome"]: e for e in SITE["editorias"]}


def editoria_slug(nome: str) -> str:
    return EDITORIAS.get(nome, {"slug": slugify(nome)})["slug"]


# ------------------------------------------------------------------- conteúdo
def load_posts() -> list[dict]:
    posts = []
    for f in sorted((ROOT / "content" / "posts").glob("*.json")):
        p = json.loads(f.read_text(encoding="utf-8"))
        if p.get("status", "publicado") != "publicado":
            continue
        p["dt"] = parse_date(p["data"])
        p.setdefault("slug", slugify(p["titulo"]))
        p.setdefault("tags", [])
        p.setdefault("autor", "Redação")
        p["url"] = f"/{p['dt']:%Y/%m}/{p['slug']}/"
        p["cat_slug"] = editoria_slug(p.get("categoria", "Notícias"))
        posts.append(p)
    posts.sort(key=lambda p: p["dt"], reverse=True)
    return posts


def load_pages() -> list[dict]:
    pages = []
    for f in sorted((ROOT / "content" / "paginas").glob("*.html")):
        raw = f.read_text(encoding="utf-8")
        m = re.match(r"\s*<!--\s*titulo:\s*(.+?)\s*-->\s*", raw)
        title = m.group(1) if m else f.stem.replace("-", " ").title()
        body = raw[m.end():] if m else raw
        pages.append({"titulo": title, "slug": f.stem, "conteudo_html": body,
                      "url": f"/{f.stem}/"})
    return pages


# -------------------------------------------------------------------- layout
def layout(title: str, body: str, *, description: str = "", canonical: str = "/",
           og_type: str = "website", image: str = "", extra_head: str = "",
           active: str = "") -> str:
    full_title = f"{title} | {SITE['nome']}" if title != SITE["nome"] else SITE["nome"]
    desc = description or SITE["descricao"]
    url = SITE["url"] + canonical
    img = image or SITE["url"] + "/static/og-padrao.png"
    cur = ' aria-current="page"'
    nav = "".join(
        f'<a href="/{e["slug"]}/"{cur if active == e["slug"] else ""}>'
        f'{ESC(e["nome"])}</a>' for e in SITE["editorias"])
    ano = datetime.now(BRT).year
    return f"""<!DOCTYPE html>
<html lang="{SITE['idioma']}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{ESC(full_title)}</title>
<meta name="description" content="{ESC(desc)}">
<link rel="canonical" href="{ESC(url)}">
<meta property="og:site_name" content="{ESC(SITE['nome'])}">
<meta property="og:locale" content="pt_BR">
<meta property="og:type" content="{og_type}">
<meta property="og:title" content="{ESC(title)}">
<meta property="og:description" content="{ESC(desc)}">
<meta property="og:url" content="{ESC(url)}">
<meta property="og:image" content="{ESC(img)}">
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="/static/favicon.svg" type="image/svg+xml">
<link rel="alternate" type="application/rss+xml" title="{ESC(SITE['nome'])}" href="/feed.xml">
<link rel="stylesheet" href="/static/style.css">
{extra_head}
</head>
<body>
<header class="topo">
  <div class="faixa"><div class="wrap">
    <span id="hoje"></span>
    <a href="{PAUTA_URL}" rel="noopener">Mande sua pauta pelo {PAUTA_CANAL}</a>
  </div></div>
  <div class="wrap marca">
    <a href="/" class="logo" aria-label="{ESC(SITE['nome'])}, página inicial">
      <img src="/static/logo.svg" alt="{ESC(SITE['nome'])}" width="220" height="56">
    </a>
    <p class="slogan">{ESC(SITE['slogan'])}</p>
  </div>
  <nav class="menu" aria-label="Editorias"><div class="wrap">
    <a href="/"{' aria-current="page"' if active == 'inicio' else ''}>Início</a>{nav}
    <a href="/anuncie/" class="destaque">Anuncie</a>
  </div></nav>
</header>
<main class="wrap">
{body}
</main>
<footer class="rodape"><div class="wrap">
  <div>
    <img src="/static/logo-branco.svg" alt="{ESC(SITE['nome'])}" width="180" height="46">
    <p>{ESC(SITE['descricao'])}</p>
  </div>
  <nav aria-label="Institucional">
    <a href="/sobre/">Sobre</a><a href="/expediente/">Expediente</a>
    <a href="/politica-editorial/">Política Editorial</a><a href="/privacidade/">Privacidade</a>
    <a href="/contato/">Contato</a><a href="/anuncie/">Anuncie</a>
  </nav>
  <nav aria-label="Redes sociais">
    {"".join(f'<a href="{ESC(SITE[k])}" rel="noopener">{n}</a>' for k, n in (("instagram", "Instagram"), ("facebook", "Facebook")) if SITE.get(k))}
    {f'<a href="https://wa.me/{SITE["whatsapp"]}" rel="noopener">WhatsApp</a>' if SITE.get("whatsapp") else f'<a href="mailto:{SITE["email_redacao"]}">E-mail</a>'}
    <a href="/feed.xml">RSS</a>
  </nav>
  <p class="copy">© {ano} {ESC(SITE['nome'])}. Mauá, SP.</p>
</div></footer>
<script>document.getElementById("hoje").textContent=new Date().toLocaleDateString("pt-BR",{{weekday:"long",day:"numeric",month:"long",year:"numeric"}});</script>
</body>
</html>
"""


def card(p: dict, big: bool = False) -> str:
    img = (f'<a href="{p["url"]}" class="thumb"><img src="{ESC(p["imagem"])}" alt="" loading="lazy"></a>'
           if p.get("imagem") else "")
    tag = "h2" if big else "h3"
    return f"""<article class="card{' card-grande' if big else ''}">
  {img}
  <a class="editoria" href="/{p['cat_slug']}/">{ESC(p.get('categoria', 'Notícias'))}</a>
  <{tag}><a href="{p['url']}">{ESC(p['titulo'])}</a></{tag}>
  <p>{ESC(p.get('subtitulo', ''))}</p>
  <time datetime="{p['dt'].isoformat()}">{data_extenso(p['dt'])}</time>
</article>"""


def pager(base: str, page: int, total: int) -> str:
    if total <= 1:
        return ""
    prev = (f'<a href="{base if page == 2 else f"{base}pagina/{page - 1}/"}">← Mais recentes</a>'
            if page > 1 else "<span></span>")
    nxt = f'<a href="{base}pagina/{page + 1}/">Mais antigas →</a>' if page < total else "<span></span>"
    return f'<nav class="paginas">{prev}<span>Página {page} de {total}</span>{nxt}</nav>'


def listing(base: str, title: str, posts: list[dict], *, intro: str = "", active: str = "",
            home: bool = False) -> None:
    per = SITE["posts_por_pagina"]
    chunks = [posts[i:i + per] for i in range(0, len(posts), per)] or [[]]
    for n, chunk in enumerate(chunks, 1):
        parts = []
        if not home or n > 1:
            parts.append(f'<h1 class="titulo-secao">{ESC(title)}</h1>')
            if intro:
                parts.append(f"<p class='intro'>{intro}</p>")
        if not chunk:
            parts.append('<p class="vazio">Ainda não há matérias publicadas aqui.</p>')
        elif home and n == 1:
            parts.append(f'<section class="manchete">{card(chunk[0], big=True)}'
                         f'<div class="lista">{"".join(card(p) for p in chunk[1:4])}</div></section>')
            for e in SITE["editorias"]:
                ep = [p for p in posts if p["cat_slug"] == e["slug"]][:3]
                if ep:
                    parts.append(f'<section class="bloco"><h2 class="titulo-secao">'
                                 f'<a href="/{e["slug"]}/">{ESC(e["nome"])}</a></h2>'
                                 f'<div class="grade">{"".join(card(p) for p in ep)}</div></section>')
        else:
            parts.append(f'<div class="grade">{"".join(card(p) for p in chunk)}</div>')
        parts.append(pager(base, n, len(chunks)))
        url = base if n == 1 else f"{base}pagina/{n}/"
        write(url, layout(SITE["nome"] if home and n == 1 else title, "\n".join(parts),
                          canonical=url, active=active))


def post_page(p: dict, posts: list[dict]) -> None:
    credito = ""
    if p.get("fonte_url"):
        credito = (f'<p class="fonte-original"><em>Com informações de <a href="{ESC(p["fonte_url"])}" '
                   f'rel="nofollow noopener">{ESC(p.get("fonte_nome", "fonte original"))}</a>.</em></p>')
    tags = "".join(f'<li><a href="/tag/{slugify(t)}/">{ESC(t)}</a></li>' for t in p["tags"])
    rel = [q for q in posts if q["cat_slug"] == p["cat_slug"] and q is not p][:3]
    share_url = SITE["url"] + p["url"]
    wa = "https://wa.me/?text=" + html.escape(f"{p['titulo']} {share_url}").replace(" ", "%20")
    img = (f'<figure><img src="{ESC(p["imagem"])}" alt="{ESC(p.get("imagem_legenda", ""))}">'
           f'<figcaption>{ESC(p.get("imagem_legenda", ""))}</figcaption></figure>'
           if p.get("imagem") else "")
    ld = {
        "@context": "https://schema.org", "@type": "NewsArticle",
        "headline": p["titulo"], "description": p.get("subtitulo", ""),
        "datePublished": p["dt"].isoformat(),
        "dateModified": parse_date(p.get("atualizado", p["data"])).isoformat(),
        "author": {"@type": "Organization", "name": SITE["nome"]},
        "publisher": {"@type": "Organization", "name": SITE["nome"],
                      "logo": {"@type": "ImageObject", "url": SITE["url"] + "/static/logo.png"}},
        "mainEntityOfPage": share_url,
    }
    if p.get("imagem"):
        ld["image"] = [p["imagem"]]
    body = f"""<article class="materia">
  <a class="editoria" href="/{p['cat_slug']}/">{ESC(p.get('categoria', 'Notícias'))}</a>
  <h1>{ESC(p['titulo'])}</h1>
  <p class="linha-fina">{ESC(p.get('subtitulo', ''))}</p>
  <p class="meta">Por {ESC(p['autor'])} · <time datetime="{p['dt'].isoformat()}">{data_extenso(p['dt'])}</time></p>
  <p class="compartilhar"><a href="{wa}" rel="noopener">Compartilhar no WhatsApp</a></p>
  {img}
  <div class="texto">{p['conteudo_html']}</div>
  {credito}
  {f'<ul class="tags">{tags}</ul>' if tags else ''}
  <aside class="pauta">Viu algo no seu bairro? <a href="{PAUTA_URL}">Mande sua pauta para a redação</a>.</aside>
</article>
{f'<section class="bloco"><h2 class="titulo-secao">Leia também</h2><div class="grade">{"".join(card(q) for q in rel)}</div></section>' if rel else ''}"""
    write(p["url"], layout(p["titulo"], body, description=p.get("subtitulo") or plain(p["conteudo_html"]),
                           canonical=p["url"], og_type="article", image=p.get("imagem", ""),
                           active=p["cat_slug"],
                           extra_head=f'<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>'))


# ------------------------------------------------------------- arquivos XML
def feeds(posts: list[dict], pages: list[dict]) -> None:
    items = "".join(f"""
  <item>
    <title>{ESC(p['titulo'])}</title>
    <link>{SITE['url']}{p['url']}</link>
    <guid isPermaLink="true">{SITE['url']}{p['url']}</guid>
    <pubDate>{format_datetime(p['dt'])}</pubDate>
    <category>{ESC(p.get('categoria', 'Notícias'))}</category>
    <description>{ESC(p.get('subtitulo', ''))}</description>
  </item>""" for p in posts[:30])
    (OUT / "feed.xml").write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>{ESC(SITE['nome'])}</title>
  <link>{SITE['url']}/</link>
  <description>{ESC(SITE['descricao'])}</description>
  <language>pt-br</language>{items}
</channel></rss>
""", encoding="utf-8")

    urls = ["/"] + [f"/{e['slug']}/" for e in SITE["editorias"]] + [pg["url"] for pg in pages]
    entries = "".join(f"<url><loc>{SITE['url']}{u}</loc></url>" for u in urls)
    entries += "".join(f"<url><loc>{SITE['url']}{p['url']}</loc><lastmod>{p['dt'].date()}</lastmod></url>"
                       for p in posts)
    (OUT / "sitemap.xml").write_text(
        f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{entries}</urlset>\n", encoding="utf-8")

    # Sitemap do Google Notícias: só matérias das últimas 48 horas.
    recent = [p for p in posts if p["dt"] > datetime.now(BRT) - timedelta(hours=48)]
    news = "".join(f"""<url><loc>{SITE['url']}{p['url']}</loc><news:news>
<news:publication><news:name>{ESC(SITE['nome'])}</news:name><news:language>pt</news:language></news:publication>
<news:publication_date>{p['dt'].isoformat()}</news:publication_date><news:title>{ESC(p['titulo'])}</news:title>
</news:news></url>""" for p in recent)
    (OUT / "sitemap-noticias.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
        f'xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">{news}</urlset>\n', encoding="utf-8")

    (OUT / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\n\nSitemap: {SITE['url']}/sitemap.xml\n"
        f"Sitemap: {SITE['url']}/sitemap-noticias.xml\n", encoding="utf-8")


# ---------------------------------------------------------------------- main
def build() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    shutil.copytree(ROOT / "static", OUT / "static")
    for extra in ("_headers", "_redirects"):
        if (ROOT / extra).exists():
            shutil.copy(ROOT / extra, OUT / extra)

    posts = load_posts()
    pages = load_pages()

    listing("/", SITE["nome"], posts, active="inicio", home=True)
    for e in SITE["editorias"]:
        listing(f"/{e['slug']}/", e["nome"], [p for p in posts if p["cat_slug"] == e["slug"]],
                active=e["slug"])
    tags: dict[str, tuple[str, list[dict]]] = {}
    for p in posts:
        for t in p["tags"]:
            tags.setdefault(slugify(t), (t, []))[1].append(p)
    for slug, (name, tp) in tags.items():
        listing(f"/tag/{slug}/", f"Tag: {name}", tp)
    for p in posts:
        post_page(p, posts)
    for pg in pages:
        write(pg["url"], layout(pg["titulo"], f'<article class="materia pagina"><h1>{ESC(pg["titulo"])}</h1>'
                                f'<div class="texto">{pg["conteudo_html"]}</div></article>',
                                canonical=pg["url"], description=plain(pg["conteudo_html"])))
    (OUT / "404.html").write_text(layout(
        "Página não encontrada",
        '<article class="materia pagina"><h1>Página não encontrada</h1>'
        '<p>O endereço pode ter mudado. <a href="/">Volte para a página inicial</a>.</p></article>',
        canonical="/404.html"), encoding="utf-8")
    feeds(posts, pages)
    print(f"Site gerado em {OUT}: {len(posts)} matérias, {len(pages)} páginas, {len(tags)} tags.")


if __name__ == "__main__":
    build()
    if "--serve" in sys.argv:
        import functools
        import http.server
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(OUT))
        print("Abrindo em http://localhost:8000 (Ctrl+C para sair)")
        http.server.ThreadingHTTPServer(("", 8000), handler).serve_forever()
