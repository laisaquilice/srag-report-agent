"""Monta as dependências, executa o grafo e grava o manifesto da execução."""

from __future__ import annotations

import json
from pathlib import Path

from srag.agent.graph import AgentDeps, build_graph
from srag.agent.state import ReportState
from srag.config import Settings
from srag.data.repository import SragRepository
from srag.governance.audit import AuditLogger, file_sha256
from srag.guardrails.input import ReportRequest
from srag.tools.news import NewsSearchTool


class MissingCredentialsError(RuntimeError):
    pass


def _make_llm(settings: Settings):
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        temperature=0,
        timeout=60,
        max_retries=2,
    )


def _make_news_tool(settings: Settings) -> NewsSearchTool:
    from tavily import TavilyClient

    return NewsSearchTool(
        backend=TavilyClient(api_key=settings.tavily_api_key),
        domains=settings.news_domains,
        days=settings.news_days,
        max_results=settings.max_news_results,
    )


def generate_report(
    request: ReportRequest, settings: Settings, offline: bool = False
) -> tuple[ReportState, AuditLogger]:
    if not offline:
        missing = [
            name
            for name, value in (
                ("OPENAI_API_KEY", settings.openai_api_key),
                ("TAVILY_API_KEY", settings.tavily_api_key),
            )
            if not value
        ]
        if missing:
            raise MissingCredentialsError(
                f"Variáveis ausentes: {', '.join(missing)}. Preencha o .env ou use --offline."
            )

    audit = AuditLogger(settings.logs_dir)
    output_dir = settings.reports_dir / audit.run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    audit.log(
        "run",
        "start",
        request=request,
        offline=offline,
        model=None if offline else settings.openai_model,
        data_sha256=file_sha256(settings.db_path),
    )

    with SragRepository(settings.db_path) as repo:
        deps = AgentDeps(
            settings=settings,
            repo=repo,
            audit=audit,
            output_dir=output_dir,
            llm=None if offline else _make_llm(settings),
            news_tool=None if offline else _make_news_tool(settings),
        )
        state: ReportState = build_graph(deps).invoke({"request": request})

    _write_manifest(output_dir / "manifest.json", state, audit, settings, offline)
    audit.log("run", "end", report_paths=state["report_paths"])
    return state, audit


def _write_manifest(
    path: Path, state: ReportState, audit: AuditLogger, settings: Settings, offline: bool
) -> None:
    manifest = {
        "run_id": audit.run_id,
        "request": state["request"].model_dump(mode="json"),
        "reference_date": state["reference_date"].isoformat(),
        "model": None if offline else settings.openai_model,
        "analysis_origin": state["analysis_origin"],
        "analysis_attempts": state["attempts"],
        "guardrail_issues": state.get("guardrail_issues", []),
        "metrics": state["metrics"].model_dump(mode="json"),
        "news_urls": [a.url for a in state["news"]],
        "decisions": audit.decisions,
        "data_sha256": file_sha256(settings.db_path),
        "audit_log": str(audit.path),
        "outputs": state["report_paths"],
    }
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
