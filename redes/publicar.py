"""Quando uma matéria é publicada (merge no main): foto, cartão e posts no Facebook e Instagram.

Passos para cada matéria nova em content/posts/:
1. Se houver PEXELS_API_KEY, busca uma foto livre (Pexels) para ilustrar, com crédito.
2. Desenha o cartão 1080x1350 da matéria (static/cards/<slug>.jpg).
3. Grava no JSON da matéria a foto, a legenda e o cartão; faz commit e push.
4. Espera o Cloudflare Pages publicar e posta no Facebook (foto + link) e no Instagram.
   Sem as credenciais da Meta, para no passo 3 e só avisa no log.

Uso: python redes/publicar.py <commit_antes> <commit_depois>   (pelo workflow redes.yml)
     python redes/publicar.py --slug <slug>                     (reprocessar uma matéria)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

import cartao

RAIZ = Path(__file__).resolve().parent.parent
POSTS = RAIZ / "content" / "posts"
SITE = json.loads((RAIZ / "site.json").read_text(encoding="utf-8"))
SITE_URL = (os.getenv("SITE_URL") or SITE["url"]).rstrip("/")
GRAPH = f"https://graph.facebook.com/{os.getenv('META_GRAPH_VERSION') or 'v23.0'}"
PAGE_ID, PAGE_TOKEN = os.getenv("META_PAGE_ID"), os.getenv("META_PAGE_TOKEN")
IG_ID = os.getenv("META_IG_USER_ID")
PEXELS_KEY = os.getenv("PEXELS_API_KEY")
UA = {"User-Agent": "Maua360Bot/1.0 (+https://maua360.com.br/contato/)"}

# Buscas de foto por editoria, quando as tags não trazem nada.
BUSCA_EDITORIA = {
    "Política": "congresso política brasil", "Saúde": "hospital saúde", "Esportes": "esporte estádio",
    "Entretenimento": "show cultura", "Notícias": "cidade rua brasil",
}


def log(*a):
    print(*a, flush=True)


def sh(*cmd) -> str:
    return subprocess.run(cmd, cwd=RAIZ, check=True, capture_output=True, text=True).stdout


def novos_posts(antes: str, depois: str) -> list[Path]:
    if not antes or set(antes) == {"0"}:
        antes = f"{depois}~1"
    nomes = sh("git", "diff", "--name-only", "--diff-filter=A", antes, depois, "--", "content/posts")
    return [RAIZ / n for n in nomes.split() if n.endswith(".json")]


def url_materia(post: dict) -> str:
    dt = datetime.fromisoformat(post["data"])
    return f"{SITE_URL}/{dt:%Y/%m}/{post['slug']}/"


# ------------------------------------------------------------------- foto
def buscar_foto(post: dict) -> tuple[bytes, str] | None:
    if not PEXELS_KEY:
        return None
    buscas = [t for t in post.get("tags", []) if t.lower() not in ("mauá", "maua", "grande abc")][:2]
    buscas.append(BUSCA_EDITORIA.get(post.get("categoria"), "cidade brasil"))
    for q in buscas:
        try:
            r = requests.get("https://api.pexels.com/v1/search", timeout=20,
                             headers={"Authorization": PEXELS_KEY, **UA},
                             params={"query": q, "locale": "pt-BR", "per_page": 5, "orientation": "portrait"})
            r.raise_for_status()
            fotos = r.json().get("photos", [])
        except Exception as exc:  # noqa: BLE001
            log("Pexels falhou:", exc)
            return None
        if fotos:
            f = fotos[0]
            img = requests.get(f["src"]["large2x"], timeout=30, headers=UA).content
            log(f"Foto Pexels ({q!r}): {f['url']}")
            return img, f"Foto: {f['photographer']} / Pexels"
    return None


# ---------------------------------------------------------------- imagens
def preparar_imagens(arq: Path) -> dict:
    post = json.loads(arq.read_text(encoding="utf-8"))
    if post.get("imagem_social"):
        return post
    slug = post["slug"]
    foto = buscar_foto(post)
    credito = ""
    if foto:
        dados, credito = foto
        destino = RAIZ / "static" / "fotos" / f"{slug}.jpg"
        destino.parent.mkdir(parents=True, exist_ok=True)
        from io import BytesIO
        from PIL import Image
        im = Image.open(BytesIO(dados)).convert("RGB")
        im.thumbnail((1600, 1600))
        im.save(destino, "JPEG", quality=85, optimize=True, progressive=True)
        post["imagem"] = f"/static/fotos/{slug}.jpg"
        post["imagem_legenda"] = f"Imagem ilustrativa. {credito}"
        foto = dados
    card = RAIZ / "static" / "cards" / f"{slug}.jpg"
    card.parent.mkdir(parents=True, exist_ok=True)
    card.write_bytes(cartao.desenhar(post["titulo"], post.get("categoria", "Notícias"), foto,
                                     f"Imagem ilustrativa · {credito}" if credito else "",
                                     SITE_URL.split("//", 1)[-1]))
    post["imagem_social"] = f"/static/cards/{slug}.jpg"
    arq.write_text(json.dumps(post, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log("Cartão criado:", card.relative_to(RAIZ))
    return post


def commit_e_push(msg: str) -> bool:
    if not sh("git", "status", "--porcelain", "content", "static"):
        return False
    sh("git", "add", "content", "static")
    sh("git", "-c", "user.name=github-actions[bot]",
       "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com", "commit", "-qm", msg)
    for tentativa in range(4):
        try:
            sh("git", "pull", "-q", "--rebase", "origin", "main")
            sh("git", "push", "-q", "origin", "HEAD:main")
            return True
        except subprocess.CalledProcessError as exc:
            log("push falhou, tentando de novo:", exc.stderr[-300:])
            time.sleep(5 * (tentativa + 1))
    raise SystemExit("Não consegui enviar as imagens para o GitHub")


def esperar_no_ar(url: str, minutos: int = 10) -> bool:
    fim = time.time() + minutos * 60
    while time.time() < fim:
        try:
            if requests.get(url, timeout=20, headers=UA).status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(20)
    return False


# ------------------------------------------------------------------- Meta
def graph(metodo: str, caminho: str, **params) -> dict:
    params["access_token"] = PAGE_TOKEN
    r = requests.request(metodo, f"{GRAPH}/{caminho}", timeout=60,
                         **({"params": params} if metodo == "GET" else {"data": params}))
    dados = r.json() if r.content else {}
    if not r.ok or "error" in dados:
        raise RuntimeError(f"{caminho}: {dados.get('error', {}).get('message', r.text[:300])}")
    return dados


def legenda(post: dict, link: str, instagram: bool) -> str:
    def hashtag(t: str) -> str:
        return "#" + "".join(p[:1].upper() + p[1:] for p in t.replace("-", " ").split() if p).replace(".", "")
    tags = " ".join(hashtag(t) for t in post.get("tags", [])[:4])
    fim = "Leia a matéria completa no link da bio." if instagram else f"Leia a matéria completa: {link}"
    partes = [post["titulo"], post.get("subtitulo", ""), fim, f"#Mauá360 #Mauá #GrandeABC {tags}".strip()]
    return "\n\n".join(p for p in partes if p)[:2100]


def postar(post: dict) -> dict:
    link, img = url_materia(post), SITE_URL + post["imagem_social"]
    feitos = dict(post.get("redes") or {})
    if PAGE_ID and "facebook" not in feitos:
        r = graph("POST", f"{PAGE_ID}/photos", url=img, caption=legenda(post, link, False))
        feitos["facebook"] = r.get("post_id") or r.get("id")
        log("Facebook ok:", feitos["facebook"])
    if IG_ID and "instagram" not in feitos:
        c = graph("POST", f"{IG_ID}/media", image_url=img, caption=legenda(post, link, True))
        for _ in range(30):  # o Instagram processa a imagem antes de publicar
            st = graph("GET", c["id"], fields="status_code").get("status_code")
            if st == "FINISHED":
                break
            if st == "ERROR":
                raise RuntimeError("Instagram recusou a imagem")
            time.sleep(5)
        feitos["instagram"] = graph("POST", f"{IG_ID}/media_publish", creation_id=c["id"])["id"]
        log("Instagram ok:", feitos["instagram"])
    return feitos


def main() -> None:
    if sys.argv[1:2] == ["--slug"]:
        arquivos = sorted(POSTS.glob(f"*-{sys.argv[2]}.json"))
    else:
        arquivos = novos_posts(*sys.argv[1:3])
    arquivos = [a for a in arquivos if a.exists()]
    if not arquivos:
        log("Nenhuma matéria nova.")
        return
    posts = {a: preparar_imagens(a) for a in arquivos}
    commit_e_push("Imagens: " + "; ".join(p["titulo"][:60] for p in posts.values()))

    if not (PAGE_TOKEN and (PAGE_ID or IG_ID)):
        log("Redes sociais não configuradas (faltam os segredos META_*). Só as imagens foram criadas.")
        return
    falhas = 0
    for arq, post in posts.items():
        if not (esperar_no_ar(SITE_URL + post["imagem_social"]) and esperar_no_ar(url_materia(post), 5)):
            log("O site não publicou a tempo:", post["titulo"]); falhas += 1
            continue
        try:
            post["redes"] = postar(post)
        except Exception as exc:  # noqa: BLE001
            log("Falha ao postar", post["titulo"], "->", exc); falhas += 1
        atual = json.loads(arq.read_text(encoding="utf-8"))
        if post.get("redes"):
            atual["redes"] = post["redes"]
            arq.write_text(json.dumps(atual, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    commit_e_push("Redes: registra posts publicados")
    if falhas:
        raise SystemExit(f"{falhas} matéria(s) não foram postadas; veja o log.")


if __name__ == "__main__":
    main()
