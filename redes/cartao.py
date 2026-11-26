"""Desenha o cartão da matéria (1080x1350, JPEG) para Instagram e Facebook."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

AQUI = Path(__file__).parent
W, H = 1080, 1350
AZUL, AZUL_NOITE, LARANJA = (11, 61, 145), (7, 42, 102), (255, 107, 26)


def _fonte(peso: str, tam: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(AQUI / "fontes" / f"Inter-{peso}.otf"), tam)


def _quebrar(draw, texto, fonte, largura):
    linhas, atual = [], ""
    for palavra in texto.split():
        teste = f"{atual} {palavra}".strip()
        if draw.textlength(teste, font=fonte) <= largura:
            atual = teste
        else:
            if atual:
                linhas.append(atual)
            atual = palavra
    if atual:
        linhas.append(atual)
    return linhas


def _fundo_marca() -> Image.Image:
    """Degradê azul com o anel da marca, quando não há foto."""
    img = Image.new("RGB", (W, H), AZUL_NOITE)
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)], fill=tuple(int(AZUL[i] * (1 - t) + AZUL_NOITE[i] * t) for i in range(3)))
    anel = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    a = ImageDraw.Draw(anel)
    cx, cy, r = W - 120, 330, 420
    a.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(255, 255, 255, 30), width=70)
    a.arc([cx - r, cy - r, cx + r, cy + r], start=-90, end=180, fill=(255, 107, 26, 210), width=70)
    img.paste(anel, (0, 0), anel)
    return img


def _fundo_foto(foto: bytes) -> Image.Image:
    img = ImageOps.fit(Image.open(BytesIO(foto)).convert("RGB"), (W, H), Image.LANCZOS)
    # Escurece de baixo para cima para o título ficar legível.
    sombra = Image.new("L", (1, H))
    for y in range(H):
        t = max(0.0, (y - H * 0.25) / (H * 0.75))
        sombra.putpixel((0, y), int(40 + 200 * t))
    sombra = sombra.resize((W, H))
    preto = Image.new("RGB", (W, H), (4, 18, 46))
    return Image.composite(preto, img, sombra)


def desenhar(titulo: str, categoria: str, foto: bytes | None = None, credito: str = "",
             site: str = "maua360.com.br") -> bytes:
    img = _fundo_foto(foto) if foto else _fundo_marca()
    d = ImageDraw.Draw(img)
    m = 72

    logo = Image.open(AQUI / "logo-branco.png").convert("RGBA")
    logo = logo.resize((380, int(380 * logo.height / logo.width)), Image.LANCZOS)
    if foto:  # leve sombra atrás do logo para fotos claras
        halo = Image.new("RGBA", (logo.width + 60, logo.height + 60), (0, 0, 0, 0))
        halo.paste((0, 0, 0, 110), (30, 30), logo.split()[3])
        halo = halo.filter(ImageFilter.GaussianBlur(18))
        img.paste(halo, (m - 30, m - 30), halo)
    img.paste(logo, (m, m), logo)

    # Título: diminui a fonte até caber em 6 linhas.
    for tam in (84, 76, 68, 60, 54):
        f_tit = _fonte("ExtraBold", tam)
        linhas = _quebrar(d, titulo, f_tit, W - 2 * m)
        if len(linhas) <= 6:
            break
    linhas = linhas[:6]
    alt_linha = int(tam * 1.18)
    y = H - 150 - alt_linha * len(linhas)

    # Editoria (etiqueta laranja) logo acima do título.
    f_cat = _fonte("ExtraBold", 30)
    txt = categoria.upper()
    lw = d.textlength(txt, font=f_cat)
    d.rounded_rectangle([m, y - 84, m + lw + 44, y - 30], radius=8, fill=LARANJA)
    d.text((m + 22, y - 57), txt, font=f_cat, fill="white", anchor="lm")

    for linha in linhas:
        d.text((m, y), linha, font=f_tit, fill="white")
        y += alt_linha

    f_rod = _fonte("SemiBold", 30)
    d.line([(m, H - 112), (W - m, H - 112)], fill=(255, 255, 255, 90), width=2)
    d.text((m, H - 70), site, font=f_rod, fill=LARANJA, anchor="lm")
    if credito:
        d.text((W - m, H - 70), credito, font=_fonte("Medium", 22), fill=(220, 228, 240), anchor="rm")

    out = BytesIO()
    img.save(out, "JPEG", quality=88, optimize=True, progressive=True)
    return out.getvalue()
