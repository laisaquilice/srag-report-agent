from srag.tools.metrics import compute_metrics
from tests.conftest import REF


def test_metrics_match_known_values(repo):
    report = compute_metrics(repo, REF)
    values = {m.key: m.value for m in report.metrics}
    assert report.total_cases_window == 30
    assert values == {
        "case_growth": 20.0,
        "mortality": 25.0,
        "icu_rate": 30.0,
        "vaccination": 60.0,
    }


def test_coverage_reports_missing_information(repo):
    report = compute_metrics(repo, REF)
    assert report.by_key("mortality").coverage == 0.8
    assert report.by_key("vaccination").coverage == 0.833


def test_small_denominators_are_suppressed(repo):
    report = compute_metrics(repo, REF, uf="SP")  # metade dos casos
    assert report.by_key("case_growth").value is not None
    report_empty = compute_metrics(repo, REF.replace(month=1))
    assert all(m.value is None for m in report_empty.metrics)
    assert report_empty.by_key("mortality").display_value == "n/d"
