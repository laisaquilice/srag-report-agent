from datetime import date

import pytest
from pydantic import ValidationError

from srag.agent.fallback import deterministic_analysis
from srag.agent.state import Analysis, MetricComment, NewsCitation
from srag.guardrails.input import ReportRequest, resolve_reference_date
from srag.guardrails.output import check_analysis
from srag.guardrails.pii import find_pii, mask_pii
from srag.tools.metrics import compute_metrics
from srag.tools.news import NewsArticle
from tests.conftest import REF

NEWS = [
    NewsArticle(
        title="Casos de SRAG sobem 15% em SP",
        url="https://g1.globo.com/a",
        content="Alta puxada por influenza.",
    )
]


def _analysis(summary: str, sources: list[str] | None = None) -> Analysis:
    keys = ["case_growth", "mortality", "icu_rate", "vaccination"]
    return Analysis(
        executive_summary=summary,
        metric_comments=[MetricComment(metric_key=k, comment="Comentário.") for k in keys],
        news_context="Contexto.",
        limitations="Limitações.",
        cited_news=[NewsCitation(url=u, contribution="Contexto.") for u in sources or []],
    )


@pytest.fixture
def metrics(repo):
    return compute_metrics(repo, REF)


def test_output_accepts_numbers_from_metrics_and_news(metrics):
    text = "Aumento de +20,0% nos casos, mortalidade de 25.0% e notícias citam alta de 15%."
    result = check_analysis(_analysis(text, ["https://g1.globo.com/a"]), metrics, NEWS)
    assert result.passed, result.issues


def test_output_rejects_invented_percentage(metrics):
    result = check_analysis(_analysis("A mortalidade chegou a 42,7%."), metrics, NEWS)
    assert not result.passed
    assert "42.7" in result.issues[0]


def test_output_rejects_unknown_source(metrics):
    result = check_analysis(_analysis("Ok.", ["https://site-falso.com/x"]), metrics, NEWS)
    assert any("Fonte" in i for i in result.issues)


def test_output_rejects_pii_and_missing_comments(metrics):
    analysis = _analysis("Paciente CPF 123.456.789-09.")
    analysis.metric_comments = analysis.metric_comments[:2]
    issues = check_analysis(analysis, metrics, NEWS).issues
    assert any("pessoais" in i for i in issues)
    assert any("Faltam" in i for i in issues)


def test_deterministic_fallback_always_passes(metrics):
    assert check_analysis(deterministic_analysis(metrics, NEWS), metrics, NEWS).passed


def test_pii_masking():
    text = "Contato: joao@email.com, (11) 98765-4321, CPF 12345678909."
    assert set(find_pii(text)) == {"EMAIL", "TELEFONE", "CPF"}
    masked = mask_pii(text)
    assert not find_pii(masked)


def test_input_rejects_invalid_uf_and_out_of_range_date():
    with pytest.raises(ValidationError):
        ReportRequest(uf="ZZ")
    assert ReportRequest(uf=" sp ").uf == "SP"
    request = ReportRequest(reference_date=date(2030, 1, 1))
    with pytest.raises(ValueError):
        resolve_reference_date(request, date(2024, 1, 1), REF)
    default = resolve_reference_date(ReportRequest(), date(2024, 1, 1), REF)
    assert default == date(2025, 3, 17)  # 14 dias antes do fim da base (atraso de notificação)


def test_output_rejects_no_news_claim_with_sources(metrics):
    analysis = _analysis("Ok.", ["https://g1.globo.com/a"])
    analysis.news_context = "Não há notícias disponíveis que expliquem o cenário."
    issues = check_analysis(analysis, metrics, NEWS).issues
    assert any("contradição" in i for i in issues)
