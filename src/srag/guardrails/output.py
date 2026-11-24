"""Guardrail de saída: confere o texto gerado pelo LLM antes de ir para o relatório.

Regras:
1. Todo percentual citado precisa existir nas métricas calculadas ou nas notícias usadas
   (impede números inventados).
2. Toda fonte citada precisa estar entre as notícias efetivamente recuperadas.
3. O texto não pode conter dados pessoais.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from pydantic import BaseModel

from srag.agent.state import Analysis
from srag.guardrails.pii import find_pii
from srag.tools.metrics import MetricsReport
from srag.tools.news import NewsArticle

_PERCENT = re.compile(r"([+-]?\d+(?:[.,]\d+)?)\s?%")
_TOLERANCE = 0.15


class OutputCheck(BaseModel):
    passed: bool
    issues: list[str]


def _percentages(text: str) -> list[float]:
    return [abs(float(m.replace(",", "."))) for m in _PERCENT.findall(text)]


def _allowed_percentages(metrics: MetricsReport, news: Iterable[NewsArticle]) -> set[float]:
    allowed = {abs(m.value) for m in metrics.metrics if m.value is not None}
    allowed |= {round(100 * m.coverage, 1) for m in metrics.metrics if m.coverage is not None}
    for article in news:
        allowed |= set(_percentages(article.title + " " + article.content))
    return allowed


def check_analysis(
    analysis: Analysis, metrics: MetricsReport, news: list[NewsArticle]
) -> OutputCheck:
    issues: list[str] = []
    text = analysis.full_text()

    allowed = _allowed_percentages(metrics, news)
    for value in _percentages(text):
        if not any(abs(value - a) <= _TOLERANCE for a in allowed):
            issues.append(f"Percentual {value}% não corresponde a nenhuma métrica ou notícia.")

    known_urls = {a.url for a in news}
    for url in analysis.sources:
        if url not in known_urls:
            issues.append(f"Fonte não recuperada pela ferramenta de notícias: {url}")

    pii = find_pii(text)
    if pii:
        issues.append(f"Texto contém possíveis dados pessoais: {pii}")

    expected = {m.key for m in metrics.metrics}
    missing = expected - {c.metric_key for c in analysis.metric_comments}
    if missing:
        issues.append(f"Faltam comentários para as métricas: {sorted(missing)}")

    return OutputCheck(passed=not issues, issues=issues)
