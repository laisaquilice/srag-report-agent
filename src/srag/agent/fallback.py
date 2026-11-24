"""Análise determinística, usada no modo offline ou quando o texto do LLM é reprovado
pelos guardrails. Garante que o relatório sempre saia com números corretos."""

from __future__ import annotations

from srag.agent.state import Analysis, MetricComment
from srag.tools.metrics import Metric, MetricsReport
from srag.tools.news import NewsArticle


def _comment(m: Metric) -> str:
    if m.value is None:
        return (
            f"{m.name}: volume de dados insuficiente para cálculo confiável "
            f"(denominador {m.denominator}). {m.caveat}"
        )
    if m.key == "case_growth":
        trend = "aumento" if m.value > 0 else "redução" if m.value < 0 else "estabilidade"
        return (
            f"Houve {trend} de {m.display_value} nos casos da última semana "
            f"({m.numerator} casos) em relação à semana anterior ({m.denominator}). {m.caveat}"
        )
    return f"{m.name}: {m.display_value} ({m.numerator} de {m.denominator} casos). {m.caveat}"


def deterministic_analysis(report: MetricsReport, articles: list[NewsArticle]) -> Analysis:
    scope = report.uf or "Brasil"
    growth = report.by_key("case_growth")
    summary = (
        f"Relatório de SRAG para {scope} com data de referência "
        f"{report.reference_date:%d/%m/%Y}. Foram registrados {report.total_cases_window} casos "
        f"nos últimos 30 dias; a variação semanal foi de {growth.display_value}."
    )
    if articles:
        titles = "; ".join(a.title for a in articles[:5])
        news = f"Notícias recentes recuperadas (sem interpretação automática): {titles}."
    else:
        news = "Nenhuma notícia foi consultada nesta execução (modo offline ou fonte indisponível)."
    return Analysis(
        executive_summary=summary,
        metric_comments=[
            MetricComment(metric_key=m.key, comment=_comment(m)) for m in report.metrics
        ],
        news_context=news,
        limitations=(
            "Texto gerado por regras determinísticas, sem interpretação do LLM. "
            "Dados de notificação sujeitos a atraso e preenchimento incompleto."
        ),
        sources=[a.url for a in articles[:5]],
    )
