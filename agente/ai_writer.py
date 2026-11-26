"""Reescrita jornalística com a API da Anthropic (Claude), com saída JSON validada."""
from __future__ import annotations

import logging
import re
from typing import Literal

import anthropic
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

Categoria = Literal["Notícias", "Política", "Esportes", "Entretenimento", "Saúde"]

ALLOWED_TAGS = {"p", "h2", "h3", "ul", "ol", "li", "strong", "em", "blockquote", "a", "br"}

SYSTEM_PROMPT = """Você é repórter de um portal de notícias hiperlocal de Mauá e do Grande ABC (SP).
Escreve em português do Brasil, com tom jornalístico profissional, claro e direto, voltado ao morador da cidade.

Sua tarefa é reescrever a matéria-fonte fornecida pelo usuário como um texto original do portal.

Regras de apuração (as mais importantes):
- Use somente fatos, números, datas, nomes, cargos e citações que estejam no texto-fonte. Não acrescente nada de memória ou suposição.
- Se uma informação não está na fonte (horário, endereço, valor, nome), não a invente nem a estime; simplesmente não a mencione.
- Citações diretas só podem aparecer se estiverem literalmente na fonte, atribuídas a quem falou.
- Não emita opinião nem juízo de valor. Em temas políticos, apresente os lados que a fonte apresenta, sem tomar partido.
- Reescreva com suas palavras: não copie frases longas da fonte.

Estrutura:
- titulo: até 90 caracteres, informativo, sem caixa alta e sem clickbait.
- subtitulo: uma frase (linha fina) que complementa o título, até 160 caracteres.
- conteudo_html: lide no primeiro parágrafo (o quê, quem, quando, onde), depois desenvolvimento em parágrafos curtos.
  Use apenas as tags <p>, <h2>, <h3>, <ul>, <ol>, <li>, <strong>, <em>, <blockquote>. Nunca use <h1>, estilos, scripts ou imagens.
  Não inclua o título no corpo nem uma linha de "fonte" (o sistema adiciona o crédito).
- categoria: exatamente uma entre Notícias (cotidiano, cidade, serviços, segurança, mobilidade, educação), Política, Esportes, Entretenimento (cultura, lazer, eventos) e Saúde.
- tags: de 3 a 6 tags curtas em minúsculas (ex.: "mauá", "linha 10", "saúde pública"). Inclua o nome da cidade principal.
"""


class NoticiaReescrita(BaseModel):
    titulo: str = Field(description="Título jornalístico, até 90 caracteres")
    subtitulo: str = Field(description="Linha fina, até 160 caracteres")
    conteudo_html: str = Field(description="Corpo em HTML limpo, sem <h1>")
    categoria: Categoria
    tags: list[str] = Field(description="3 a 6 tags curtas em minúsculas")


class AIWriterError(Exception):
    pass


class AIWriter:
    def __init__(self, api_key: str, model: str, effort: str = "medium", use_fallback: bool = True):
        if not api_key:
            raise AIWriterError("ANTHROPIC_API_KEY não definida no .env")
        # max_retries cobre 429/5xx/erros de conexão com backoff automático do SDK.
        self.client = anthropic.Anthropic(api_key=api_key, max_retries=3, timeout=120)
        self.model = model
        self.effort = effort
        # O fallback de recusa no servidor existe para Sonnet/Opus; Haiku não tem.
        self.use_fallback = use_fallback and "haiku" not in model

    def rewrite(self, title: str, source_text: str, source_name: str, url: str) -> NoticiaReescrita:
        user_msg = (
            f"Fonte: {source_name}\nURL: {url}\n\n"
            f"<titulo_original>\n{title}\n</titulo_original>\n\n"
            f"<texto_original>\n{source_text}\n</texto_original>\n\n"
            "Reescreva a matéria seguindo as regras."
        )
        kwargs = dict(
            model=self.model,
            max_tokens=8000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
            output_config={"effort": self.effort},
            output_format=NoticiaReescrita,
        )
        if self.use_fallback:
            kwargs["betas"] = ["server-side-fallback-2026-07-01"]
            kwargs["fallbacks"] = "default"

        try:
            response = self.client.beta.messages.parse(**kwargs)
        except anthropic.AuthenticationError as exc:
            raise AIWriterError(f"Chave da Anthropic inválida: {exc}") from exc
        except anthropic.BadRequestError as exc:
            raise AIWriterError(f"Requisição rejeitada pela API: {exc}") from exc
        except anthropic.RateLimitError as exc:
            raise AIWriterError(f"Limite de taxa atingido mesmo após novas tentativas: {exc}") from exc
        except anthropic.APIStatusError as exc:
            raise AIWriterError(f"Erro da API ({exc.status_code}): {exc}") from exc
        except anthropic.APIConnectionError as exc:
            raise AIWriterError(f"Falha de conexão com a API: {exc}") from exc

        if response.stop_reason == "refusal":
            raise AIWriterError(f"Claude recusou o texto: {response.stop_details}")
        if response.stop_reason == "max_tokens":
            raise AIWriterError("Resposta cortada por max_tokens")
        result = response.parsed_output
        if result is None:
            raise AIWriterError("Resposta sem JSON válido")

        log.info(
            "Claude: %s | in=%s out=%s tokens",
            response.model, response.usage.input_tokens, response.usage.output_tokens,
        )
        result.conteudo_html = sanitize_html(result.conteudo_html)
        result.tags = sorted({t.strip().lower() for t in result.tags if t.strip()})[:6]
        return result


def sanitize_html(html: str) -> str:
    """Remove <h1> e qualquer tag/atributo fora da lista permitida."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all(["script", "style", "iframe", "img", "h1"]):
        if tag.name == "h1":
            tag.name = "h2"
        else:
            tag.decompose()
    for tag in soup.find_all(True):
        if tag.name in {"html", "body"}:
            continue
        if tag.name not in ALLOWED_TAGS:
            tag.unwrap()
            continue
        href = tag.get("href") if tag.name == "a" else None
        tag.attrs = {"href": href} if href and href.startswith("http") else {}
    body = soup.body or soup
    return "".join(str(c) for c in body.contents).strip()


_NUM_RE = re.compile(r"\d[\d.,]*")


def unverified_numbers(rewritten_html: str, source_text: str) -> list[str]:
    """Checagem anti-alucinação barata: números do texto novo que não aparecem na fonte."""
    def nums(s: str) -> set[str]:
        return {n.strip(".,").replace(".", "").replace(",", "") for n in _NUM_RE.findall(s)}

    plain = BeautifulSoup(rewritten_html, "lxml").get_text(" ")
    missing = nums(plain) - nums(source_text)
    return sorted(n for n in missing if n)
