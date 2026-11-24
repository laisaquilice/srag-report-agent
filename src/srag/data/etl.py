"""ETL: CSV bruto do Open DATASUS (SRAG) -> tabela DuckDB limpa e minimizada.

Princípios aplicados:
- Minimização de dados: só as colunas necessárias para as métricas entram na base.
- Anonimização: idade exata vira faixa etária; nenhum código de unidade, município
  ou data de nascimento é mantido.
- Qualidade: datas inválidas/fora do intervalo são descartadas e códigos de
  "ignorado" (9) viram NULL para não distorcer os denominadores.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import duckdb

logger = logging.getLogger(__name__)

RAW_COLUMNS: tuple[str, ...] = (
    "DT_NOTIFIC",
    "DT_SIN_PRI",
    "SG_UF_NOT",
    "EVOLUCAO",
    "UTI",
    "VACINA_COV",
    "VACINA",
    "HOSPITAL",
    "CLASSI_FIN",
    "NU_IDADE_N",
    "TP_IDADE",
    "CS_SEXO",
)

MIN_VALID_DATE = "2019-01-01"

_DATE_FORMATS = "['%d/%m/%Y', '%Y-%m-%d']"


def _date(col: str) -> str:
    return f"TRY_CAST(TRY_STRPTIME(TRIM({col}), {_DATE_FORMATS}) AS DATE)"


def _code(col: str, valid: str) -> str:
    """Converte para inteiro mantendo só códigos válidos (9 = ignorado -> NULL)."""
    return f"CASE WHEN TRY_CAST({col} AS INTEGER) IN ({valid}) THEN TRY_CAST({col} AS INTEGER) END"


_AGE_YEARS = (
    "CASE WHEN TRY_CAST(TP_IDADE AS INTEGER) = 3 THEN TRY_CAST(NU_IDADE_N AS INTEGER) "
    "WHEN TRY_CAST(TP_IDADE AS INTEGER) IN (1, 2) THEN 0 END"
)

_TRANSFORM_SQL = f"""
CREATE OR REPLACE TABLE srag AS
WITH raw AS (
    -- DISTINCT sobre a linha bruta completa: só remove registros duplicados de fato,
    -- nunca pacientes diferentes que coincidem nas colunas selecionadas.
    SELECT {", ".join(RAW_COLUMNS)}
    FROM (
        SELECT DISTINCT *
        FROM read_csv($files, delim=';', header=true, all_varchar=true,
                      encoding=$encoding, union_by_name=true, ignore_errors=true)
    )
),
typed AS (
    SELECT
        {_date("DT_NOTIFIC")} AS dt_notificacao,
        {_date("DT_SIN_PRI")} AS dt_sintomas,
        UPPER(TRIM(SG_UF_NOT)) AS uf,
        {_code("EVOLUCAO", "1, 2, 3")} AS evolucao,
        {_code("UTI", "1, 2")} AS uti,
        {_code("VACINA_COV", "1, 2")} AS vacina_covid,
        {_code("VACINA", "1, 2")} AS vacina_gripe,
        {_code("HOSPITAL", "1, 2")} AS hospitalizado,
        {_code("CLASSI_FIN", "1, 2, 3, 4, 5")} AS classificacao_final,
        {_AGE_YEARS} AS idade_anos,
        CASE WHEN UPPER(TRIM(CS_SEXO)) IN ('M', 'F') THEN UPPER(TRIM(CS_SEXO)) END AS sexo
    FROM raw
)
SELECT
    dt_notificacao, dt_sintomas, uf, evolucao, uti, vacina_covid, vacina_gripe,
    hospitalizado, classificacao_final, sexo,
    CASE
        WHEN idade_anos IS NULL OR idade_anos > 120 THEN NULL
        WHEN idade_anos < 5 THEN '0-4'
        WHEN idade_anos < 20 THEN '5-19'
        WHEN idade_anos < 60 THEN '20-59'
        ELSE '60+'
    END AS faixa_etaria
FROM typed
WHERE dt_sintomas IS NOT NULL
  AND dt_sintomas >= DATE '{MIN_VALID_DATE}'
  AND (dt_notificacao IS NULL OR dt_sintomas <= dt_notificacao)
  AND dt_sintomas <= current_date
"""


@dataclass(frozen=True)
class EtlSummary:
    raw_rows: int
    clean_rows: int
    min_date: str | None
    max_date: str | None

    @property
    def discarded_rows(self) -> int:
        return self.raw_rows - self.clean_rows


def run_etl(csv_files: Sequence[Path], db_path: Path, encoding: str = "latin-1") -> EtlSummary:
    """Lê os CSVs do DATASUS, aplica limpeza e grava a tabela `srag` em `db_path`."""
    if not csv_files:
        raise ValueError("Nenhum arquivo CSV informado para o ETL.")
    missing = [str(f) for f in csv_files if not Path(f).exists()]
    if missing:
        raise FileNotFoundError(f"Arquivos não encontrados: {missing}")

    db_path.parent.mkdir(parents=True, exist_ok=True)
    files = [str(Path(f).resolve()) for f in csv_files]
    params = {"files": files, "encoding": encoding}

    with duckdb.connect(str(db_path)) as con:
        raw_rows = con.execute(
            "SELECT COUNT(*) FROM read_csv($files, delim=';', header=true, all_varchar=true, "
            "encoding=$encoding, union_by_name=true, ignore_errors=true)",
            params,
        ).fetchone()[0]
        con.execute(_TRANSFORM_SQL, params)
        clean_rows, min_date, max_date = con.execute(
            "SELECT COUNT(*), MIN(dt_sintomas)::VARCHAR, MAX(dt_sintomas)::VARCHAR FROM srag"
        ).fetchone()

    summary = EtlSummary(raw_rows, clean_rows, min_date, max_date)
    logger.info("ETL concluído: %s", summary)
    return summary
