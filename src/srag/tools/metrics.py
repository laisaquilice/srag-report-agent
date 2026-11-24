"""Cálculo determinístico das quatro métricas do relatório.

Todos os números do relatório vêm daqui; o LLM apenas os interpreta.
"""

from __future__ import annotations

from datetime import date, timedelta

from pydantic import BaseModel

from srag.config import MIN_CELL_SIZE
from srag.data.repository import Period, SragRepository

WINDOW_DAYS = 30
GROWTH_DAYS = 7


class Metric(BaseModel):
    key: str
    name: str
    value: float | None
    numerator: int
    denominator: int
    period_start: date
    period_end: date
    definition: str
    caveat: str
    coverage: float | None = None
    """Fração dos casos do período em que a informação usada no cálculo estava preenchida."""

    @property
    def display_value(self) -> str:
        if self.value is None:
            return "n/d"
        return f"{self.value:+.1f}%" if self.key == "case_growth" else f"{self.value:.1f}%"


class MetricsReport(BaseModel):
    reference_date: date
    uf: str | None
    total_cases_window: int
    metrics: list[Metric]

    def by_key(self, key: str) -> Metric:
        return next(m for m in self.metrics if m.key == key)


def _rate(numerator: int, denominator: int) -> float | None:
    """Percentual, com supressão de denominadores pequenos (estatística e privacidade)."""
    if denominator < MIN_CELL_SIZE:
        return None
    return round(100 * numerator / denominator, 1)


def _window(reference_date: date, days: int, offset: int = 0) -> Period:
    end = reference_date - timedelta(days=offset)
    return Period(start=end - timedelta(days=days - 1), end=end)


def _case_growth(repo: SragRepository, ref: date, uf: str | None) -> Metric:
    current = _window(ref, GROWTH_DAYS)
    previous = _window(ref, GROWTH_DAYS, offset=GROWTH_DAYS)
    cur, prev = repo.count_cases(current, uf), repo.count_cases(previous, uf)
    value = None if prev < MIN_CELL_SIZE else round(100 * (cur - prev) / prev, 1)
    return Metric(
        key="case_growth",
        name="Taxa de aumento de casos",
        value=value,
        numerator=cur,
        denominator=prev,
        period_start=previous.start,
        period_end=current.end,
        definition=(
            f"Variação percentual de casos (data de início dos sintomas) nos últimos {GROWTH_DAYS} "
            f"dias ({cur}) em relação aos {GROWTH_DAYS} dias anteriores ({prev})."
        ),
        caveat=(
            "Casos recentes ainda estão sendo notificados (atraso de notificação), o que tende a "
            "subestimar a semana mais recente."
        ),
    )


def _flag_rate(
    repo: SragRepository,
    period: Period,
    uf: str | None,
    total: int,
    *,
    key: str,
    name: str,
    column: str,
    positive: int,
    definition: str,
    caveat: str,
) -> Metric:
    numerator, denominator = repo.count_by_flag(column, positive, period, uf)
    return Metric(
        key=key,
        name=name,
        value=_rate(numerator, denominator),
        numerator=numerator,
        denominator=denominator,
        period_start=period.start,
        period_end=period.end,
        definition=definition,
        caveat=caveat,
        coverage=round(denominator / total, 3) if total else None,
    )


def compute_metrics(
    repo: SragRepository, reference_date: date, uf: str | None = None
) -> MetricsReport:
    window = _window(reference_date, WINDOW_DAYS)
    total = repo.count_cases(window, uf)
    common = {"repo": repo, "period": window, "uf": uf, "total": total}

    metrics = [
        _case_growth(repo, reference_date, uf),
        _flag_rate(
            **common,
            key="mortality",
            name="Taxa de mortalidade",
            column="evolucao",
            positive=2,
            definition=(
                f"Óbitos por SRAG / casos com desfecho conhecido (cura, óbito por SRAG ou por "
                f"outras causas) nos últimos {WINDOW_DAYS} dias."
            ),
            caveat=(
                "Letalidade entre casos notificados (majoritariamente hospitalizados), não da "
                "população geral. Casos sem desfecho ainda não entram no cálculo."
            ),
        ),
        _flag_rate(
            **common,
            key="icu_rate",
            name="Taxa de ocupação de UTI",
            column="uti",
            positive=1,
            definition=(
                f"Casos internados em UTI / casos com a informação de UTI preenchida nos últimos "
                f"{WINDOW_DAYS} dias."
            ),
            caveat=(
                "Proxy: a base não traz a capacidade de leitos. Mede a proporção de casos de SRAG "
                "que precisaram de UTI, não a ocupação dos leitos existentes "
                "(exigiria dados do CNES)."
            ),
        ),
        _flag_rate(
            **common,
            key="vaccination",
            name="Taxa de vacinação (COVID-19)",
            column="vacina_covid",
            positive=1,
            definition=(
                f"Casos vacinados contra COVID-19 / casos com a informação de vacina preenchida "
                f"nos últimos {WINDOW_DAYS} dias."
            ),
            caveat=(
                "Proxy: mede a vacinação entre os casos de SRAG notificados, não a cobertura "
                "vacinal da população (exigiria dados do SI-PNI)."
            ),
        ),
    ]
    return MetricsReport(
        reference_date=reference_date, uf=uf, total_cases_window=total, metrics=metrics
    )
