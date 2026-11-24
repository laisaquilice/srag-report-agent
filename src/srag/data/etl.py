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
    """Aceita `dd/mm/aaaa` (arquivos antigos) e ISO `aaaa-mm-ddT00:00:00.000Z` (arquivos novos)."""
    return f"TRY_CAST(TRY_STRPTIME(LEFT(TRIM({col}), 10), {_DATE_FORMATS}) AS DATE)"


def _code(col: str, valid: str) -> str:
    """Converte para inteiro mantendo só códigos válidos (9 = ignorado -> NULL)."""
    return f"CASE WHEN TRY_CAST({col} AS INTEGER) IN ({valid}) THEN TRY_CAST({col} AS INTEGER) END"


_AGE_YEARS = (
    "CASE WHEN TRY_CAST(TP_IDADE AS INTEGER) = 3 THEN TRY_CAST(NU_IDADE_N AS INTEGER) "
    "WHEN TRY_CAST(TP_IDADE AS INTEGER) IN (1, 2) THEN 0 END"
)

_TRANSFORM_SQL_TEMPLATE = f"""
CREATE OR REPLACE TABLE srag AS
WITH raw AS (
    -- DISTINCT sobre a linha bruta completa: só remove registros duplicados de fato,
    -- nunca pacientes diferentes que coincidem nas colunas selecionadas.
    SELECT {", ".join(RAW_COLUMNS)}
    FROM (SELECT DISTINCT * FROM ({{source}}))
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


def detect_encoding(path: Path, sample_bytes: int = 4_000_000) -> str:
    """Os arquivos antigos do DATASUS são latin-1; os mais recentes, UTF-8."""
    with Path(path).open("rb") as fh:
        sample = fh.read(sample_bytes)
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError as exc:
        if exc.start < len(sample) - 3:  # erro real, não um caractere cortado no fim da amostra
            return "latin-1"
    return "utf-8"


def _source_sql(n_files: int) -> str:
    """Um read_csv por arquivo (cada um com sua codificação), unidos pelo nome das colunas."""
    return " UNION ALL BY NAME ".join(
        f"SELECT * FROM read_csv($f{i}, delim=';', header=true, all_varchar=true, "
        f"encoding=$e{i}, ignore_errors=true)"
        for i in range(n_files)
    )


def run_etl(csv_files: Sequence[Path], db_path: Path, encoding: str | None = None) -> EtlSummary:
    """Lê os CSVs do DATASUS, aplica limpeza e grava a tabela `srag` em `db_path`.

    `encoding=None` detecta a codificação de cada arquivo automaticamente.
    """
    if not csv_files:
        raise ValueError("Nenhum arquivo CSV informado para o ETL.")
    missing = [str(f) for f in csv_files if not Path(f).exists()]
    if missing:
        raise FileNotFoundError(f"Arquivos não encontrados: {missing}")

    db_path.parent.mkdir(parents=True, exist_ok=True)
    params: dict[str, str] = {}
    for i, f in enumerate(csv_files):
        params[f"f{i}"] = str(Path(f).resolve())
        params[f"e{i}"] = encoding or detect_encoding(Path(f))
        logger.info("Lendo %s (%s)", Path(f).name, params[f"e{i}"])
    source = _source_sql(len(csv_files))

    with duckdb.connect(str(db_path)) as con:
        raw_rows = con.execute(f"SELECT COUNT(*) FROM ({source})", params).fetchone()[0]
        con.execute(_TRANSFORM_SQL_TEMPLATE.format(source=source), params)
        clean_rows, min_date, max_date = con.execute(
            "SELECT COUNT(*), MIN(dt_sintomas)::VARCHAR, MAX(dt_sintomas)::VARCHAR FROM srag"
        ).fetchone()

    summary = EtlSummary(raw_rows, clean_rows, min_date, max_date)
    logger.info("ETL concluído: %s", summary)
    return summary
