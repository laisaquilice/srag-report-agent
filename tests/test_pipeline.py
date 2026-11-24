"""Teste de ponta a ponta do grafo, sem chamadas externas."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from srag.agent.graph import AgentDeps, _Nodes, build_graph
from srag.config import Settings
from srag.data.repository import SragRepository
from srag.governance.audit import AuditLogger
from srag.guardrails.input import ReportRequest
from srag.pipeline import MissingCredentialsError, generate_report
from srag.tools.metrics import compute_metrics
from srag.tools.news import NewsSearchTool
from tests.conftest import REF
from tests.test_news import FakeBackend


class ScriptedToolLLM(GenericFakeChatModel):
    """Modelo falso que devolve respostas roteirizadas, inclusive chamadas de ferramenta."""

    def bind_tools(self, tools, **kwargs):
        return self


@pytest.fixture
def settings(db_path, tmp_path):
    return Settings(
        openai_api_key=None,
        openai_model="gpt-test",
        tavily_api_key=None,
        db_path=db_path,
        reports_dir=tmp_path / "reports",
        logs_dir=tmp_path / "logs",
    )


def test_offline_report_end_to_end(settings):
    state, audit = generate_report(ReportRequest(), settings, offline=True)

    assert state["analysis_origin"] == "deterministic"
    assert all(Path(p).exists() for p in state["report_paths"].values())
    html = Path(state["report_paths"]["html"]).read_text(encoding="utf-8")
    assert "+20.0%" in html and "25.0%" in html and "data:image/png;base64" in html

    events = [json.loads(line) for line in audit.path.read_text(encoding="utf-8").splitlines()]
    steps = {e["step"] for e in events}
    assert {"validate_input", "compute_metrics", "build_charts", "check_output"} <= steps
    assert any(e["event"] == "decision" for e in events)


def test_missing_credentials_fail_fast(settings):
    with pytest.raises(MissingCredentialsError):
        generate_report(ReportRequest(), settings, offline=False)


def test_news_without_llm_uses_default_queries_and_logs(settings):
    backend = FakeBackend(
        [{"title": "SRAG em alta", "url": "https://g1.globo.com/x", "content": "Alta de 15%."}]
    )
    audit = AuditLogger(settings.logs_dir)
    with SragRepository(settings.db_path) as repo:
        deps = AgentDeps(
            settings=settings,
            repo=repo,
            audit=audit,
            output_dir=settings.reports_dir / "t",
            news_tool=NewsSearchTool(backend, settings.news_domains),
        )
        state = build_graph(deps).invoke({"request": ReportRequest(uf="SP")})
    assert [a.url for a in state["news"]] == ["https://g1.globo.com/x"]
    assert len(backend.calls) == 2


def test_rejected_llm_text_retries_then_falls_back(settings, tmp_path):
    settings = replace(settings, max_analysis_attempts=2)
    llm = GenericFakeChatModel(messages=iter([AIMessage("x")]))
    with SragRepository(settings.db_path) as repo:
        nodes = _Nodes(AgentDeps(settings, repo, AuditLogger(tmp_path), tmp_path, llm=llm))
        assert (
            nodes.route_after_check({"guardrail_issues": ["x"], "attempts": 1}) == "write_analysis"
        )
        assert (
            nodes.route_after_check({"guardrail_issues": ["x"], "attempts": 2})
            == "fallback_analysis"
        )
        assert nodes.route_after_check({"guardrail_issues": [], "attempts": 1}) == "render_report"


def test_agentic_search_runs_tool_calls_through_guardrails(settings, repo, tmp_path):
    backend = FakeBackend([{"title": "T", "url": "https://www.gov.br/saude/n", "content": "SRAG"}])
    llm = ScriptedToolLLM(
        messages=iter(
            [
                AIMessage(
                    "",
                    tool_calls=[
                        {
                            "name": "buscar_noticias_srag",
                            "args": {"consulta": "SRAG Brasil"},
                            "id": "1",
                        },
                        {
                            "name": "buscar_noticias_srag",
                            "args": {"consulta": "futebol hoje"},
                            "id": "2",
                        },
                    ],
                ),
                AIMessage("PRONTO"),
            ]
        )
    )
    audit = AuditLogger(tmp_path)
    nodes = _Nodes(
        AgentDeps(
            settings,
            repo,
            audit,
            tmp_path,
            llm=llm,
            news_tool=NewsSearchTool(backend, settings.news_domains),
        )
    )
    state = {"request": ReportRequest(), "metrics": compute_metrics(repo, REF)}

    news = nodes.research_news(state)["news"]

    assert [a.url for a in news] == ["https://www.gov.br/saude/n"]
    assert [q for q, _ in backend.calls] == ["SRAG Brasil"]  # consulta fora de escopo barrada
    assert any(d["decision"] == "consulta rejeitada" for d in audit.decisions)
