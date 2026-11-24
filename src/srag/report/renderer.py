"""Renderização do relatório final em HTML (autocontido) e PDF."""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from jinja2 import Environment, PackageLoader, select_autoescape
from xhtml2pdf import pisa

from srag.guardrails.pii import mask_pii

if TYPE_CHECKING:
    from srag.agent.state import ReportState

DISCLAIMER = (
    "Prova de conceito gerada automaticamente a partir de dados públicos do Open DATASUS e de "
    "notícias. Não substitui a avaliação de equipes de vigilância epidemiológica nem orienta "
    "condutas clínicas individuais."
)

_env = Environment(
    loader=PackageLoader("srag", "report/templates"),
    autoescape=select_autoescape(["html", "j2"]),
)


def _data_uri(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()


def _context(state: ReportState, run_id: str, model: str | None, decisions: list) -> dict[str, Any]:
    analysis = state["analysis"]
    return {
        "scope": state["metrics"].uf or "Brasil",
        "metrics": state["metrics"],
        "analysis": analysis,
        "comments": {c.metric_key: mask_pii(c.comment) for c in analysis.metric_comments},
        "news": state["news"],
        "used_sources": set(analysis.sources),
        "origin": state["analysis_origin"],
        "issues": state.get("guardrail_issues") or [],
        "decisions": decisions,
        "run_id": run_id,
        "model": model or "nenhum (modo determinístico)",
        "generated_at": datetime.now(UTC).strftime("%d/%m/%Y %H:%M UTC"),
        "disclaimer": DISCLAIMER,
    }


def render_report(
    state: ReportState, output_dir: Path, run_id: str, model: str | None, decisions: list
) -> dict[str, str]:
    template = _env.get_template("report.html.j2")
    context = _context(state, run_id, model, decisions)
    charts = state["charts"]

    images = {
        "daily_img": _data_uri(charts.daily.image_path),
        "monthly_img": _data_uri(charts.monthly.image_path),
    }

    html_path = output_dir / "relatorio.html"
    html_path.write_text(template.render(**context, **images, for_pdf=False), encoding="utf-8")

    pdf_path = output_dir / "relatorio.pdf"
    pdf_html = template.render(**context, **images, for_pdf=True)
    with pdf_path.open("wb") as fh:
        result = pisa.CreatePDF(pdf_html, dest=fh, encoding="utf-8")
    if result.err:
        raise RuntimeError(f"Falha ao gerar PDF ({result.err} erros).")

    return {"html": str(html_path), "pdf": str(pdf_path)}
