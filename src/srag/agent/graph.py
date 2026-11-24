"""Orquestrador do relatório (LangGraph).

Fluxo:
    validate_input -> compute_metrics -> build_charts -> research_news
        -> write_analysis -> check_output --(ok)--> render_report
                               ^         |
                               +--(retry)+--(esgotou)--> fallback_analysis -> render_report
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph

from srag.agent.fallback import deterministic_analysis
from srag.agent.prompts import (
    ANALYST_SYSTEM,
    RESEARCH_SYSTEM,
    analyst_user_message,
    format_metrics,
)
from srag.agent.state import Analysis, ReportState
from srag.config import NOTIFICATION_LAG_DAYS, Settings
from srag.data.repository import SragRepository
from srag.governance.audit import AuditCallbackHandler, AuditLogger
from srag.guardrails.input import resolve_reference_date
from srag.guardrails.output import check_analysis
from srag.report.renderer import render_report
from srag.tools.charts import build_charts
from srag.tools.metrics import compute_metrics
from srag.tools.news import NewsArticle, NewsSearchTool, QueryRejectedError

DEFAULT_QUERIES = (
    "SRAG síndrome respiratória aguda grave casos",
    "vírus respiratórios internações",
)


@tool
def buscar_noticias_srag(consulta: str) -> str:
    """Busca notícias recentes em fontes confiáveis sobre SRAG e vírus respiratórios no Brasil."""
    raise NotImplementedError  # executada pelo nó research_news, que aplica os guardrails


@dataclass
class AgentDeps:
    settings: Settings
    repo: SragRepository
    audit: AuditLogger
    output_dir: Path
    llm: BaseChatModel | None = None
    news_tool: NewsSearchTool | None = None

    @property
    def llm_config(self) -> RunnableConfig:
        return {"callbacks": [AuditCallbackHandler(self.audit)]}


class _Nodes:
    def __init__(self, deps: AgentDeps) -> None:
        self.d = deps

    def validate_input(self, state: ReportState) -> ReportState:
        request = state["request"]
        with self.d.audit.step("validate_input", request=request):
            data_min, data_max = self.d.repo.date_bounds(request.uf)
            ref = resolve_reference_date(request, data_min, data_max)
            self.d.audit.decision(
                "validate_input",
                f"data de referência {ref}",
                "informada pelo usuário"
                if request.reference_date
                else f"última data da base ({data_max}) menos {NOTIFICATION_LAG_DAYS} dias "
                "de atraso de notificação",
            )
        return {"reference_date": ref}

    def compute_metrics(self, state: ReportState) -> ReportState:
        with self.d.audit.step("compute_metrics"):
            report = compute_metrics(self.d.repo, state["reference_date"], state["request"].uf)
            self.d.audit.log("compute_metrics", "output", metrics=report)
        return {"metrics": report}

    def build_charts(self, state: ReportState) -> ReportState:
        with self.d.audit.step("build_charts"):
            charts = build_charts(
                self.d.repo, state["reference_date"], self.d.output_dir, state["request"].uf
            )
            self.d.audit.log(
                "build_charts", "output", daily=charts.daily.values, monthly=charts.monthly.values
            )
        return {"charts": charts}

    # -- notícias ---------------------------------------------------------------

    def research_news(self, state: ReportState) -> ReportState:
        with self.d.audit.step("research_news"):
            if self.d.news_tool is None:
                self.d.audit.decision(
                    "research_news", "sem busca de notícias", "ferramenta de notícias desativada"
                )
                return {"news": []}
            collected: dict[str, NewsArticle] = {}
            update: ReportState = {}
            if self.d.llm is not None:
                try:
                    self._agentic_search(state, collected)
                except Exception as exc:  # LLM indisponível não pode derrubar o relatório
                    update["llm_error"] = repr(exc)
                    self.d.audit.decision(
                        "research_news",
                        "usar consultas padrão",
                        "falha ao chamar o LLM para escolher as buscas",
                        error=repr(exc),
                    )
            if self.d.llm is None or "llm_error" in update:
                for query in DEFAULT_QUERIES:
                    self._run_search(query, collected)
            self.d.audit.log("research_news", "output", urls=list(collected))
        return {**update, "news": list(collected.values())}

    def _agentic_search(self, state: ReportState, collected: dict[str, NewsArticle]) -> None:
        """O LLM escolhe as consultas; cada uma passa pelos guardrails da ferramenta."""
        max_searches = self.d.settings.max_news_searches
        uf = state["request"].uf
        system = RESEARCH_SYSTEM.format(
            max_searches=max_searches, uf_hint=f", com foco no estado {uf}" if uf else ""
        )
        messages = [SystemMessage(system), HumanMessage(format_metrics(state["metrics"]))]
        llm = self.d.llm.bind_tools([buscar_noticias_srag])
        searches = 0
        while searches < max_searches:
            ai = llm.invoke(messages, config=self.d.llm_config)
            messages.append(ai)
            if not ai.tool_calls:
                break
            for call in ai.tool_calls:
                query = str(call["args"].get("consulta", ""))
                if searches >= max_searches:
                    result = "Limite de buscas atingido."
                else:
                    searches += 1
                    self.d.audit.decision(
                        "research_news", f"buscar: {query}", "consulta escolhida pelo LLM"
                    )
                    result = self._run_search(query, collected)
                messages.append(ToolMessage(result, tool_call_id=call["id"]))

    def _run_search(self, query: str, collected: dict[str, NewsArticle]) -> str:
        try:
            articles, rejected = self.d.news_tool.search(query)
        except QueryRejectedError as exc:
            self.d.audit.decision("research_news", "consulta rejeitada", str(exc), query=query)
            return f"Consulta rejeitada: {exc}"
        except Exception as exc:  # falha externa não pode derrubar o relatório
            self.d.audit.decision("research_news", "busca falhou", repr(exc), query=query)
            return "A busca falhou; prossiga com o que já tem."
        for a in articles:
            if a.flagged_injection:
                self.d.audit.decision(
                    "research_news", "trecho neutralizado", "possível prompt injection", url=a.url
                )
            collected.setdefault(a.url, a)
        self.d.audit.log(
            "research_news",
            "tool_call",
            tool="buscar_noticias_srag",
            query=query,
            accepted=[a.url for a in articles],
            rejected_by_domain_or_topic=rejected,
        )
        return "\n".join(f"- {a.title} ({a.url})" for a in articles) or "Nenhum resultado."

    # -- análise e verificação -----------------------------------------------------

    def write_analysis(self, state: ReportState) -> ReportState:
        attempts = state.get("attempts", 0) + 1
        with self.d.audit.step("write_analysis", attempt=attempts):
            if self.d.llm is None:
                self.d.audit.decision("write_analysis", "análise determinística", "LLM desativado")
                analysis = deterministic_analysis(state["metrics"], state["news"])
                return {
                    "analysis": analysis,
                    "analysis_origin": "deterministic",
                    "attempts": attempts,
                }
            structured = self.d.llm.with_structured_output(Analysis)
            message = analyst_user_message(
                state["metrics"], state["news"], state.get("guardrail_issues")
            )
            try:
                analysis = structured.invoke(
                    [SystemMessage(ANALYST_SYSTEM), HumanMessage(message)],
                    config=self.d.llm_config,
                )
            except Exception as exc:  # LLM indisponível: segue com texto determinístico
                self.d.audit.decision(
                    "write_analysis",
                    "análise determinística",
                    "falha ao chamar o LLM",
                    error=repr(exc),
                )
                return {
                    "analysis": deterministic_analysis(state["metrics"], state["news"]),
                    "analysis_origin": "deterministic",
                    "attempts": attempts,
                    "llm_error": repr(exc),
                }
        return {"analysis": analysis, "analysis_origin": "llm", "attempts": attempts}

    def check_output(self, state: ReportState) -> ReportState:
        with self.d.audit.step("check_output"):
            result = check_analysis(state["analysis"], state["metrics"], state["news"])
            self.d.audit.log(
                "check_output", "guardrail", passed=result.passed, issues=result.issues
            )
            if result.passed:
                origin = "LLM" if state["analysis_origin"] == "llm" else "regras determinísticas"
                self.d.audit.decision(
                    "check_output",
                    f"texto aprovado ({origin})",
                    f"passou em todas as verificações na tentativa {state['attempts']}",
                )
        return {"guardrail_issues": result.issues}

    def route_after_check(self, state: ReportState) -> str:
        if not state["guardrail_issues"]:
            return "render_report"
        if state["attempts"] < self.d.settings.max_analysis_attempts:
            self.d.audit.decision(
                "check_output", "reescrever análise", "reprovada pelos guardrails de saída"
            )
            return "write_analysis"
        return "fallback_analysis"

    def fallback_analysis(self, state: ReportState) -> ReportState:
        self.d.audit.decision(
            "fallback_analysis",
            "usar análise determinística",
            f"texto do LLM reprovado após {state['attempts']} tentativas",
            issues=state["guardrail_issues"],
        )
        analysis = deterministic_analysis(state["metrics"], state["news"])
        return {"analysis": analysis, "analysis_origin": "deterministic"}

    def render_report(self, state: ReportState) -> ReportState:
        with self.d.audit.step("render_report"):
            paths = render_report(
                state=state,
                output_dir=self.d.output_dir,
                run_id=self.d.audit.run_id,
                model=self.d.settings.openai_model if self.d.llm else None,
                decisions=self.d.audit.decisions,
            )
            self.d.audit.log("render_report", "output", paths=paths)
        return {"report_paths": paths}


def build_graph(deps: AgentDeps):
    nodes = _Nodes(deps)
    graph = StateGraph(ReportState)
    for name in (
        "validate_input",
        "compute_metrics",
        "build_charts",
        "research_news",
        "write_analysis",
        "check_output",
        "fallback_analysis",
        "render_report",
    ):
        graph.add_node(name, getattr(nodes, name))

    graph.add_edge(START, "validate_input")
    graph.add_edge("validate_input", "compute_metrics")
    graph.add_edge("compute_metrics", "build_charts")
    graph.add_edge("build_charts", "research_news")
    graph.add_edge("research_news", "write_analysis")
    graph.add_edge("write_analysis", "check_output")
    graph.add_conditional_edges(
        "check_output",
        nodes.route_after_check,
        ["render_report", "write_analysis", "fallback_analysis"],
    )
    graph.add_edge("fallback_analysis", "render_report")
    graph.add_edge("render_report", END)
    return graph.compile()
