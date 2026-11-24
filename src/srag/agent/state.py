"""Estado do grafo e esquema da saída estruturada do LLM."""

from __future__ import annotations

from datetime import date
from typing import Literal, TypedDict

from pydantic import BaseModel, Field

from srag.guardrails.input import ReportRequest
from srag.tools.charts import Charts
from srag.tools.metrics import MetricsReport
from srag.tools.news import NewsArticle

MetricKey = Literal["case_growth", "mortality", "icu_rate", "vaccination"]


class MetricComment(BaseModel):
    metric_key: MetricKey = Field(description="Chave da métrica comentada.")
    comment: str = Field(
        description="2 a 4 frases interpretando a métrica, usando apenas os números fornecidos."
    )


class Analysis(BaseModel):
    """Análise escrita pelo LLM para o relatório."""

    executive_summary: str = Field(description="Resumo executivo do cenário em até 5 frases.")
    metric_comments: list[MetricComment] = Field(
        description="Um comentário para cada uma das quatro métricas."
    )
    news_context: str = Field(
        description="Como as notícias recentes ajudam a explicar o cenário. "
        "Diga explicitamente se não houver notícias disponíveis."
    )
    limitations: str = Field(description="Limitações dos dados e da análise.")
    sources: list[str] = Field(
        default_factory=list, description="URLs das notícias usadas, exatamente como fornecidas."
    )

    def full_text(self) -> str:
        parts = [self.executive_summary, self.news_context, self.limitations]
        parts += [c.comment for c in self.metric_comments]
        return "\n".join(parts)

    def comment_for(self, key: str) -> str:
        return next((c.comment for c in self.metric_comments if c.metric_key == key), "")


class ReportState(TypedDict, total=False):
    request: ReportRequest
    reference_date: date
    metrics: MetricsReport
    charts: Charts
    news: list[NewsArticle]
    analysis: Analysis
    analysis_origin: Literal["llm", "deterministic"]
    attempts: int
    guardrail_issues: list[str]
    report_paths: dict[str, str]
