"""Base pequena e controlada, com resultados de métricas conhecidos de antemão.

Data de referência: 31/03/2025.
- Últimos 7 dias (25-31/03): 12 casos; 7 dias anteriores (18-24/03): 10 casos -> +20,0%.
- Mais 8 casos em 05/03 -> 30 casos na janela de 30 dias.
- EVOLUCAO: 6 óbitos, 18 curas, 6 ignorados -> mortalidade 6/24 = 25,0%.
- UTI: 9 sim, 21 não -> 30,0%.
- VACINA_COV: 15 sim, 10 não, 5 vazio -> 60,0%.
Ruídos: data inválida, data de 1900, sintomas após notificação, linha duplicada.
"""

from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path

import pytest

from srag.data.etl import run_etl
from srag.data.repository import SragRepository

REF = date(2025, 3, 31)
HEADER = [
    "DT_NOTIFIC",
    "DT_SIN_PRI",
    "SG_UF_NOT",
    "DT_NASC",
    "NU_IDADE_N",
    "TP_IDADE",
    "CS_SEXO",
    "HOSPITAL",
    "UTI",
    "VACINA",
    "VACINA_COV",
    "CLASSI_FIN",
    "EVOLUCAO",
]


def _onset_dates() -> list[date]:
    last_week = [REF - timedelta(days=i % 7) for i in range(12)]
    prev_week = [REF - timedelta(days=7 + i % 7) for i in range(10)]
    older = [date(2025, 3, 5)] * 8
    return last_week + prev_week + older


def _rows() -> list[dict[str, str]]:
    evolucao = ["2"] * 6 + ["1"] * 18 + ["9"] * 6
    uti = ["1"] * 9 + ["2"] * 21
    vacina = ["1"] * 15 + ["2"] * 10 + [""] * 5
    rows = []
    for i, onset in enumerate(_onset_dates()):
        rows.append(
            {
                "DT_NOTIFIC": (onset + timedelta(days=1)).strftime("%d/%m/%Y"),
                "DT_SIN_PRI": onset.strftime("%d/%m/%Y"),
                "SG_UF_NOT": "SP" if i % 2 else "RJ",
                "DT_NASC": f"{1 + i % 28:02d}/01/{1950 + i}",
                "NU_IDADE_N": str(70 - i),
                "TP_IDADE": "3",
                "CS_SEXO": "F" if i % 2 else "M",
                "HOSPITAL": "1",
                "UTI": uti[i],
                "VACINA": "9",
                "VACINA_COV": vacina[i],
                "CLASSI_FIN": "4",
                "EVOLUCAO": evolucao[i],
            }
        )
    noise = dict(rows[0])
    rows += [
        {**noise, "DT_SIN_PRI": "31/02/2025"},
        {**noise, "DT_SIN_PRI": "01/01/1900"},
        {**noise, "DT_SIN_PRI": "10/03/2025", "DT_NOTIFIC": "01/03/2025"},
        dict(rows[0]),  # duplicata exata
    ]
    return rows


@pytest.fixture(scope="session")
def sample_csv(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("raw") / "INFLUD_TESTE.csv"
    with path.open("w", newline="", encoding="latin-1") as fh:
        writer = csv.DictWriter(fh, fieldnames=HEADER, delimiter=";")
        writer.writeheader()
        writer.writerows(_rows())
    return path


@pytest.fixture(scope="session")
def db_path(sample_csv: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("db") / "srag.duckdb"
    run_etl([sample_csv], path)
    return path


@pytest.fixture
def repo(db_path: Path):
    with SragRepository(db_path) as r:
        yield r
