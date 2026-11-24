"""Geração dos dois gráficos obrigatórios do relatório."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from srag.data.repository import Period, SragRepository  # noqa: E402

_BAR_COLOR = "#2a6f97"
_PARTIAL_COLOR = "#9dbcd4"
_MONTHS_PT = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


class ChartSeries(BaseModel):
    labels: list[date]
    values: list[int]
    image_path: Path


class Charts(BaseModel):
    daily: ChartSeries
    monthly: ChartSeries


def _style(ax: plt.Axes, title: str) -> None:
    ax.set_title(title, loc="left", fontsize=12, fontweight="bold")
    ax.set_ylabel("Casos")
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.3)


def _plot_daily(series: list[tuple[date, int]], path: Path) -> None:
    days, values = zip(*series, strict=True)
    fig, ax = plt.subplots(figsize=(9, 3.6), dpi=120)
    ax.bar(days, values, color=_BAR_COLOR, width=0.8)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m"))
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=3))
    _style(ax, "Casos diários de SRAG – últimos 30 dias (data de início dos sintomas)")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def _plot_monthly(series: list[tuple[date, int]], path: Path, reference_date: date) -> None:
    months, values = zip(*series, strict=True)
    labels = [f"{_MONTHS_PT[m.month - 1]}/{m.year % 100:02d}" for m in months]
    colors = [_BAR_COLOR] * len(values)
    partial = _add_month(months[-1]) - timedelta(days=1) > reference_date
    if partial:  # mês corrente incompleto: destacado para não parecer uma queda real
        labels[-1] += f"\n(até {reference_date:%d/%m})"
        colors[-1] = _PARTIAL_COLOR
    fig, ax = plt.subplots(figsize=(9, 3.6), dpi=120)
    ax.bar(labels, values, color=colors)
    for x, v in enumerate(values):
        ax.annotate(f"{v:,}".replace(",", "."), (x, v), ha="center", va="bottom", fontsize=8)
    title = "Casos mensais de SRAG – últimos 12 meses"
    _style(ax, title + (" (último mês parcial)" if partial else ""))
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def build_charts(
    repo: SragRepository, reference_date: date, output_dir: Path, uf: str | None = None
) -> Charts:
    output_dir.mkdir(parents=True, exist_ok=True)
    daily_period = Period(reference_date - timedelta(days=29), reference_date)
    first_month = date(reference_date.year - 1, reference_date.month, 1)
    monthly_period = Period(_add_month(first_month), reference_date)

    daily = repo.daily_cases(daily_period, uf)
    monthly = repo.monthly_cases(monthly_period, uf)

    daily_path, monthly_path = output_dir / "casos_diarios.png", output_dir / "casos_mensais.png"
    _plot_daily(daily, daily_path)
    _plot_monthly(monthly, monthly_path, reference_date)

    return Charts(
        daily=ChartSeries(
            labels=[d for d, _ in daily], values=[v for _, v in daily], image_path=daily_path
        ),
        monthly=ChartSeries(
            labels=[m for m, _ in monthly], values=[v for _, v in monthly], image_path=monthly_path
        ),
    )


def _add_month(d: date) -> date:
    return date(d.year + d.month // 12, d.month % 12 + 1, 1)
