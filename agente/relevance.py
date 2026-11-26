"""Filtro de relevância local: decide, sem gastar tokens, se a matéria interessa ao portal."""
from __future__ import annotations

import re
import unicodedata

# Peso alto: termos que, sozinhos, já indicam pauta de Mauá.
MAUA_TERMS = {
    "maua": 3, "prefeitura de maua": 4, "camara de maua": 4, "camara municipal de maua": 4,
    "marcelo oliveira": 2, "sama": 2, "saneamento basico de maua": 3,
    "jardim zaira": 3, "parque sao vicente": 2, "vila assis": 2, "jardim itapark": 3,
    "parque das americas": 2, "jardim guapituba": 3, "sertaozinho": 2, "capuava": 2,
    "estacao maua": 3, "estacao guapituba": 3, "polo petroquimico": 2, "rodoanel": 1,
    "hospital nardini": 4, "hospital estadual de maua": 4, "nardini": 3,
}
# Peso médio: Grande ABC e mobilidade regional.
ABC_TERMS = {
    "grande abc": 2, "abc paulista": 2, "santo andre": 1, "sao bernardo": 1,
    "sao caetano": 1, "diadema": 1, "ribeirao pires": 2, "rio grande da serra": 2,
    "consorcio intermunicipal": 2, "consorcio abc": 2,
    "linha 10": 3, "turquesa": 1, "cptm": 1,
    "brt-abc": 2, "brt abc": 2, "emtu": 1,
}
# Palavras que puxam a matéria para fora do escopo (conteúdo patrocinado, outras "Mauá").
NEGATIVE_TERMS = {
    "publieditorial": -10, "conteudo patrocinado": -10, "horoscopo": -5,
    "instituto maua de tecnologia": -1,  # é de São Caetano; ainda pode interessar, só reduz
    "barao de maua": -2, "maua (rj)": -5, "porto maua": -3,
}


def _norm(text: str) -> str:
    t = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", t)


def _count(term: str, text: str) -> int:
    return len(re.findall(rf"\b{re.escape(term)}\b", text))


def relevance_score(title: str, body: str, trust_region: bool = False) -> tuple[int, list[str]]:
    """Retorna (pontuação, termos encontrados). Título vale em dobro."""
    t_title, t_body = _norm(title), _norm(body)
    score, hits = (3 if trust_region else 0), []

    # Termos negativos primeiro; depois são removidos do texto para que
    # "Barão de Mauá" não conte também como "Mauá".
    for term, weight in NEGATIVE_TERMS.items():
        n_title, n_body = _count(term, t_title), _count(term, t_body)
        if n_title or n_body:
            hits.append(term)
            score += weight * (min(n_title, 1) + min(n_body, 1))
            t_title = re.sub(rf"\b{re.escape(term)}\b", " ", t_title)
            t_body = re.sub(rf"\b{re.escape(term)}\b", " ", t_body)

    for table in (MAUA_TERMS, ABC_TERMS):
        for term, weight in table.items():
            n_title, n_body = _count(term, t_title), _count(term, t_body)
            if n_title or n_body:
                hits.append(term)
                # Contagens no corpo saturam em 3 para evitar que um texto longo "infle" a nota.
                score += weight * (2 * min(n_title, 1) + min(n_body, 3))
    return score, hits


def is_relevant(title: str, body: str, min_score: int, trust_region: bool = False) -> tuple[bool, int, list[str]]:
    score, hits = relevance_score(title, body, trust_region)
    has_local = trust_region or any(h in MAUA_TERMS or h in ABC_TERMS for h in hits)
    return (has_local and score >= min_score), score, hits


def is_maua(hits: list[str], trust_region: bool = False) -> bool:
    """Pauta de Mauá (prioridade) x pauta só do Grande ABC (complemento)."""
    return trust_region or any(h in MAUA_TERMS for h in hits)


# Política nacional e do Estado de SP: entra na editoria Política, como complemento.
POLITICS_TERMS = (
    "lula", "bolsonaro", "planalto", "congresso", "senado", "senador", "camara dos deputados",
    "deputado federal", "deputados", "stf", "supremo", "ministro", "ministerio", "governo federal",
    "eleicao", "eleicoes", "eleitoral", "tse", "pec", "reforma", "orcamento", "partido",
    "pt", "pl", "psdb", "mdb", "uniao brasil", "psd", "republicanos", "tarcisio", "alesp",
    "impeachment", "cpi", "pesquisa eleitoral", "presidente da republica",
    # Estado de São Paulo
    "governador", "governo de sp", "governo de sao paulo", "governo do estado",
    "assembleia legislativa", "deputado estadual", "deputados estaduais", "palacio dos bandeirantes",
    "secretario estadual", "kassab", "prefeito de sao paulo",
)


def is_politics(title: str, summary: str, url: str) -> bool:
    """Matéria de política (Brasil ou Estado de SP): endereço com /politica ou ao menos dois termos políticos."""
    if re.search(r"/politica", (url or "").lower()):
        return True
    text = _norm(f"{title} {summary}")
    return sum(1 for t in POLITICS_TERMS if _count(t, text)) >= 2
