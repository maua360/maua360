"""Quando uma matéria é publicada (merge no main): foto, cartão e posts no Facebook e Instagram.

Passos para cada matéria nova em content/posts/:
1. Usa a foto que você anexou no PR da matéria; sem ela, busca uma foto livre no
   Openverse (Wikimedia Commons, Flickr...), só CC0/domínio público/CC BY, com crédito.
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
import re
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
UA = {"User-Agent": "Maua360Bot/1.0 (+https://maua360.com.br/contato/)"}

# Buscas de foto por editoria, quando as tags não trazem nada.
BUSCA_EDITORIA = {
    "Política": "brazil congress", "Saúde": "hospital", "Esportes": "football stadium",
    "Entretenimento": "concert stage", "Notícias": "city street brazil",
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
LICENCAS = {"cc0": "domínio público", "pdm": "domínio público", "by": "CC BY"}
PROVEDOR = {"wikimedia": "Wikimedia", "flickr": "Flickr"}


def _baixar_imagem(url: str) -> bytes | None:
    """Baixa e confere se é uma imagem de verdade com pelo menos 1000 px de largura."""
    from io import BytesIO
    from PIL import Image
    try:
        r = requests.get(url, timeout=30, headers=UA)
        r.raise_for_status()
        im = Image.open(BytesIO(r.content))
        return r.content if im.width >= 1000 else None
    except Exception:  # noqa: BLE001
        return None


def buscar_foto(post: dict) -> tuple[bytes, str] | None:
    """Foto livre pelo Openverse (agrega Wikimedia Commons, Flickr etc.), sem chave de API.

    Só aceita licenças que permitem uso comercial e adaptação sem "compartilha igual":
    CC0, domínio público e CC BY. O crédito sai com autor, origem e licença.
    """
    buscas = [post["busca_foto"]] if post.get("busca_foto") else []
    buscas += [t for t in post.get("tags", []) if t.lower() not in ("mauá", "maua", "grande abc")][:2]
    buscas.append(BUSCA_EDITORIA.get(post.get("categoria"), "city street"))
    for q in buscas:
        try:
            r = requests.get("https://api.openverse.org/v1/images/", timeout=30, headers=UA,
                             params={"q": q, "license": "cc0,pdm,by", "size": "large",
                                     "mature": "false", "page_size": 10})
            r.raise_for_status()
            fotos = r.json().get("results", [])
        except Exception as exc:  # noqa: BLE001
            log("Openverse falhou:", exc)
            return None
        for f in fotos:
            if (f.get("license") or "").lower() not in LICENCAS:
                continue
            img = _baixar_imagem(f.get("url", ""))
            if not img:
                continue
            lic = LICENCAS[f["license"].lower()]
            if lic == "CC BY" and f.get("license_version"):
                lic += f" {f['license_version']}"
            autor = (f.get("creator") or "autor desconhecido").strip()[:24]
            origem = PROVEDOR.get(f.get("source") or f.get("provider"), (f.get("provider") or "").title())
            log(f"Foto livre ({q!r}): {f.get('foreign_landing_url')} [{lic}]")
            return img, f"Foto: {autor} / {origem} ({lic})"
    return None


# ------------------------------------------------------- foto enviada no PR
# Só aceita anexos hospedados pelo próprio GitHub e só de quem tem acesso ao repositório:
# o repositório é público, e qualquer pessoa pode comentar num PR.
IMG_RE = re.compile(r'!\[[^\]]*\]\((https://[^)\s]+)\)|<img[^>]+src="(https://[^"]+)"')
CREDITO_RE = re.compile(r"^\s*(?:foto|cr[eé]dito)\s*:\s*(.+)$", re.I | re.M)
HOSTS_OK = ("https://github.com/user-attachments/", "https://user-images.githubusercontent.com/",
            "https://private-user-images.githubusercontent.com/")
AUTORES_OK = {"OWNER", "MEMBER", "COLLABORATOR"}


def _gh(caminho: str) -> list | dict:
    r = requests.get(f"https://api.github.com/repos/{os.getenv('GITHUB_REPOSITORY')}{caminho}", timeout=20,
                     headers={"Authorization": f"Bearer {os.getenv('GITHUB_TOKEN', '')}",
                              "Accept": "application/vnd.github+json", **UA})
    r.raise_for_status()
    return r.json()


def foto_do_pr(post: dict) -> tuple[bytes, str] | None:
    """Foto que você anexou no PR da matéria (comentário ou descrição). A mais recente vale."""
    if not (os.getenv("GITHUB_TOKEN") and os.getenv("GITHUB_REPOSITORY")):
        return None
    dono = os.getenv("GITHUB_REPOSITORY").split("/")[0]
    try:
        prs = _gh(f"/pulls?state=all&head={dono}:rascunho/{post['slug'][:60]}")
        if not prs:
            return None
        pr = prs[0]
        comentarios = [c for c in reversed(_gh(f"/issues/{pr['number']}/comments?per_page=100"))
                       if c.get("author_association") in AUTORES_OK]
        textos = [c.get("body") or "" for c in comentarios] + [pr.get("body") or ""]
        for texto in textos:
            urls = [u for a, b in IMG_RE.findall(texto) if (u := a or b).startswith(HOSTS_OK)]
            if not urls:
                continue
            r = requests.get(urls[-1], timeout=60, headers=UA)
            r.raise_for_status()
            if not r.headers.get("content-type", "").startswith("image/"):
                log("O anexo do PR não é imagem:", urls[-1])
                continue
            m = CREDITO_RE.search(texto)
            credito = f"Foto: {m.group(1).strip()[:60]}" if m else f"Foto: {SITE['nome']}"
            log(f"Foto enviada no PR #{pr['number']} ({credito})")
            return r.content, credito
    except Exception as exc:  # noqa: BLE001
        log("Não consegui pegar a foto do PR:", exc)
    return None


# ---------------------------------------------------------------- imagens
def preparar_imagens(arq: Path) -> dict:
    post = json.loads(arq.read_text(encoding="utf-8"))
    if post.get("imagem_social"):
        return post
    slug = post["slug"]
    foto, ilustrativa = foto_do_pr(post), False
    if not foto and not post.get("sem_foto"):  # "sem_foto": true deixa o cartão só com a marca
        foto, ilustrativa = buscar_foto(post), True
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
        post["imagem_legenda"] = f"Imagem ilustrativa. {credito}" if ilustrativa else credito
        foto = dados
    card = RAIZ / "static" / "cards" / f"{slug}.jpg"
    card.parent.mkdir(parents=True, exist_ok=True)
    card.write_bytes(cartao.desenhar(post["titulo"], post.get("categoria", "Notícias"), foto,
                                     (f"Imagem ilustrativa · {credito}" if ilustrativa else credito) if credito else "",
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


def verificar() -> None:
    """Só leitura: confere se o token enxerga a página e o Instagram. Não posta nada."""
    if not PAGE_TOKEN:
        raise SystemExit("Falta o segredo META_PAGE_TOKEN")
    if PAGE_ID:
        p = graph("GET", PAGE_ID, fields="name,link")
        log(f"Página do Facebook ok: {p.get('name')} ({p.get('link', '')})")
    if IG_ID:
        i = graph("GET", IG_ID, fields="username,name")
        log(f"Instagram ok: @{i.get('username')}")
        lim = graph("GET", f"{IG_ID}/content_publishing_limit", fields="quota_usage,config").get("data", [{}])
        log("Limite de posts no Instagram:", lim[0] if lim else "?")


def main() -> None:
    if sys.argv[1:2] == ["--teste-foto"]:
        achou = buscar_foto({"busca_foto": sys.argv[2], "tags": [], "categoria": "Notícias"})
        log("Resultado:", achou[1] if achou else "nenhuma foto", f"({len(achou[0])} bytes)" if achou else "")
        return
    if sys.argv[1:2] == ["--verificar"]:
        verificar()
        return
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
