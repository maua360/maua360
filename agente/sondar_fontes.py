"""Testa as fontes de notícias: procura feed RSS e, se não houver, mostra os links da página.

Uso: python sondar_fontes.py  (roda pelo GitHub Actions: workflow "Testar fontes").
"""
from __future__ import annotations

import collections
import re
import sys
from urllib.parse import urljoin, urlsplit

import feedparser
import requests
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36 Maua360Bot/1.0"
SITES = sys.argv[1:] or [
    "https://www.maua.sp.gov.br/Noticias", "https://www.camaramaua.sp.gov.br/Noticias",
    "https://www.cptm.sp.gov.br/cptm/noticias", "https://sobreabc.com.br/",
    "https://www.reporterdiario.com.br/", "https://aguardiadanoticia.com/", "https://abcdoabc.com.br/",
    "https://www.vivaabc.com.br/", "https://www.falamaua.com.br/", "https://jnconline.com.br/",
    "https://www.portalopiniaopublica.com.br/", "https://abcdjornal.com.br/", "https://folhademaua.com.br/",
    "https://grupoabcnews.com.br/", "https://portalmauaeregiao.com.br/", "https://www.dgabc.com.br/",
    "https://www.uol.com.br/", "https://www.metropoles.com/",
]
s = requests.Session()
s.headers.update({"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9"})


def get(url):
    try:
        return s.get(url, timeout=20, allow_redirects=True)
    except Exception as exc:  # noqa: BLE001
        return exc


def feed_ok(url):
    r = get(url)
    if isinstance(r, Exception) or not r.ok:
        return None
    f = feedparser.parse(r.content)
    if not f.entries:
        return None
    e = f.entries[0]
    body = (e.get("content") or [{}])[0].get("value", "") or e.get("summary", "")
    return len(f.entries), e.get("title", "")[:70], len(BeautifulSoup(body, "lxml").get_text()), r.url


for site in SITES:
    print("=" * 100, "\n", site, flush=True)
    r = get(site)
    if isinstance(r, Exception):
        print("  PÁGINA: erro", type(r).__name__, str(r)[:150])
        html, final = "", site
    else:
        print("  PÁGINA:", r.status_code, r.url, len(r.text), "bytes")
        html, final = r.text, r.url
    soup = BeautifulSoup(html, "lxml")
    root = "{0.scheme}://{0.netloc}".format(urlsplit(final))
    cands = [urljoin(final, l["href"]) for l in soup.select("link[rel=alternate][href]")
             if "rss" in (l.get("type") or "") or "atom" in (l.get("type") or "")]
    cands += [root + p for p in ("/feed/", "/rss", "/rss.xml", "/feed/rss/", "/index.xml", "/noticias/feed/")]
    found = False
    for c in dict.fromkeys(cands):
        ok = feed_ok(c)
        if ok:
            print(f"  FEED OK: {c} -> {ok[0]} itens | 1º: {ok[1]!r} | texto no feed: {ok[2]} chars | final {ok[3]}")
            found = True
            break
    if not found:
        print("  FEED: nenhum")
        links = collections.Counter()
        samples = {}
        for a in soup.find_all("a", href=True):
            href = urljoin(final, a["href"])
            if urlsplit(href).netloc != urlsplit(final).netloc:
                continue
            t = a.get_text(" ", strip=True)
            if len(t) < 25:
                continue
            path = urlsplit(href).path
            pat = re.sub(r"\d+", "N", "/".join(path.split("/")[:3]))
            links[pat] += 1
            samples.setdefault(pat, (t[:60], href))
        for pat, n in links.most_common(6):
            print(f"  LINKS {n:3d}  {pat:40s} ex: {samples[pat][0]!r} {samples[pat][1]}")
