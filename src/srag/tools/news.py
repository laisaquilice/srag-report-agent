"""Ferramenta de busca de notícias sobre SRAG (Tavily) com sanitização do conteúdo.

O texto das notícias é tratado como dado não confiável: passa por filtro de domínio,
corte de tamanho, mascaramento de PII e detecção de tentativas de prompt injection.
"""

from __future__ import annotations

import re
from typing import Protocol
from urllib.parse import urlparse

from pydantic import BaseModel

from srag.guardrails.pii import mask_pii

MAX_CONTENT_CHARS = 1200
MAX_QUERY_CHARS = 200

_INJECTION = re.compile(
    r"(ignore|desconsidere|esque[çc]a)\s+(all\s+|todas?\s+(as\s+)?)?"
    r"(previous|prior|above|anteriores|instru[çc][õo]es)|system\s*prompt|you\s+are\s+now|"
    r"voc[êe]\s+agora\s+[ée]|<\s*/?\s*(system|assistant)\s*>",
    re.IGNORECASE,
)

_HEALTH_TERMS = re.compile(
    r"srag|s[íi]ndrome respirat|respirat|gripe|influenza|covid|v[íi]rus|vsr|interna[çc]|"
    r"uti|vacina|surto|epidemi|sa[úu]de|hospital",
    re.IGNORECASE,
)


class NewsArticle(BaseModel):
    title: str
    url: str
    published: str | None = None
    content: str
    flagged_injection: bool = False


class SearchBackend(Protocol):
    def search(self, query: str, **kwargs: object) -> dict: ...


class QueryRejectedError(ValueError):
    """A consulta pedida pelo agente está fora do escopo permitido."""


def is_trusted(url: str, domains: tuple[str, ...]) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in domains)


def validate_query(query: str) -> str:
    query = " ".join(query.split())
    if not query or len(query) > MAX_QUERY_CHARS:
        raise QueryRejectedError("Consulta vazia ou longa demais.")
    if not _HEALTH_TERMS.search(query):
        raise QueryRejectedError("Consulta fora do escopo de saúde/SRAG.")
    return query


def sanitize_content(text: str) -> tuple[str, bool]:
    """Corta, mascara PII e neutraliza trechos com cara de instrução ao modelo."""
    text = " ".join(text.split())[:MAX_CONTENT_CHARS]
    flagged = bool(_INJECTION.search(text))
    if flagged:
        text = _INJECTION.sub("[TRECHO REMOVIDO]", text)
    return mask_pii(text), flagged


class NewsSearchTool:
    def __init__(
        self,
        backend: SearchBackend,
        domains: tuple[str, ...],
        days: int = 30,
        max_results: int = 5,
    ) -> None:
        self._backend = backend
        self._domains = domains
        self._days = days
        self._max_results = max_results

    def search(self, query: str) -> tuple[list[NewsArticle], int]:
        """Retorna (artigos aceitos, número de resultados descartados por domínio)."""
        query = validate_query(query)
        response = self._backend.search(
            query,
            topic="news",
            days=self._days,
            max_results=self._max_results,
            include_domains=list(self._domains),
        )
        articles, rejected = [], 0
        for item in response.get("results", []):
            url = item.get("url", "")
            if not is_trusted(url, self._domains):
                rejected += 1
                continue
            content, flagged = sanitize_content(item.get("content", ""))
            articles.append(
                NewsArticle(
                    title=mask_pii(item.get("title", "")[:200]),
                    url=url,
                    published=item.get("published_date"),
                    content=content,
                    flagged_injection=flagged,
                )
            )
        return articles, rejected
