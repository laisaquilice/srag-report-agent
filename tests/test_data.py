from datetime import date, timedelta

import duckdb
import pytest

from srag.data.etl import detect_encoding, run_etl
from srag.data.repository import Period
from tests.conftest import REF


def test_etl_drops_invalid_rows_and_duplicates(sample_csv, tmp_path):
    summary = run_etl([sample_csv], tmp_path / "x.duckdb")
    assert summary.raw_rows == 34
    assert summary.clean_rows == 30
    assert summary.max_date == "2025-03-31"


def test_etl_keeps_only_minimized_columns(db_path):
    with duckdb.connect(str(db_path), read_only=True) as con:
        columns = {row[0] for row in con.execute("DESCRIBE srag").fetchall()}
        bands = {row[0] for row in con.execute("SELECT DISTINCT faixa_etaria FROM srag").fetchall()}
    assert "dt_nasc" not in {c.lower() for c in columns}
    assert "idade_anos" not in columns
    assert bands <= {"0-4", "5-19", "20-59", "60+"}


def test_ignored_codes_become_null(repo):
    period = Period(date(2025, 3, 1), REF)
    deaths, known = repo.count_by_flag("evolucao", 2, period)
    assert (deaths, known) == (6, 24)


def test_repository_rejects_unknown_column_and_uf(repo):
    period = Period(date(2025, 3, 1), REF)
    with pytest.raises(ValueError):
        repo.count_by_flag("uf; DROP TABLE srag", 1, period)
    with pytest.raises(ValueError):
        repo.count_cases(period, uf="XX")


def test_daily_series_fills_missing_days_with_zero(repo):
    series = repo.daily_cases(Period(REF - timedelta(days=29), REF))
    assert len(series) == 30
    assert sum(v for _, v in series) == 30
    assert dict(series)[date(2025, 3, 6)] == 0


def test_monthly_series_has_twelve_months(repo):
    series = repo.monthly_cases(Period(date(2024, 4, 1), REF))
    assert len(series) == 12
    assert series[-1] == (date(2025, 3, 1), 30)


def test_etl_reads_new_utf8_iso_format_mixed_with_old_files(sample_csv, tmp_path):
    """Arquivos recentes do DATASUS: UTF-8, campos entre aspas e datas ISO com hora."""
    new_file = tmp_path / "INFLUD26.csv"
    new_file.write_text(
        '"NU_NOTIFIC";"DT_NOTIFIC";"DT_SIN_PRI";"SG_UF_NOT";"ID_MUNICIP";"EVOLUCAO";"UTI"\n'
        '"1";"2025-04-02T00:00:00.000Z";"2025-04-01T00:00:00.000Z";"SP";"SÃO PAULO";"2";"1"\n'
        '"2";"2025-04-03T00:00:00.000Z";"2025-04-02T00:00:00.000Z";"RJ";"NITERÓI";"1";"2"\n',
        encoding="utf-8",
    )
    assert detect_encoding(new_file) == "utf-8"

    summary = run_etl([sample_csv, new_file], tmp_path / "mixed.duckdb")

    assert summary.clean_rows == 32
    assert summary.max_date == "2025-04-02"
