"""Acesso somente leitura à base SRAG por consultas pré-definidas e parametrizadas.

O LLM nunca escreve SQL: ele só recebe os resultados agregados destas funções.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import duckdb

from srag.config import UFS


@dataclass(frozen=True)
class Period:
    start: date
    end: date


class SragRepository:
    """Consultas agregadas sobre a tabela `srag` (conexão read-only)."""

    def __init__(self, db_path: Path) -> None:
        if not db_path.exists():
            raise FileNotFoundError(
                f"Base não encontrada em {db_path}. Rode `srag etl` antes de gerar relatórios."
            )
        self._con = duckdb.connect(str(db_path), read_only=True)

    def close(self) -> None:
        self._con.close()

    def __enter__(self) -> SragRepository:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @staticmethod
    def _uf_filter(uf: str | None, alias: str = "") -> tuple[str, list[str]]:
        if uf is None:
            return "", []
        if uf not in UFS:
            raise ValueError(f"UF inválida: {uf!r}")
        return f" AND {alias}uf = ?", [uf]

    def date_bounds(self, uf: str | None = None) -> tuple[date | None, date | None]:
        clause, params = self._uf_filter(uf)
        return self._con.execute(
            f"SELECT MIN(dt_sintomas), MAX(dt_sintomas) FROM srag WHERE 1=1{clause}", params
        ).fetchone()

    def count_cases(self, period: Period, uf: str | None = None) -> int:
        clause, params = self._uf_filter(uf)
        return self._con.execute(
            f"SELECT COUNT(*) FROM srag WHERE dt_sintomas BETWEEN ? AND ?{clause}",
            [period.start, period.end, *params],
        ).fetchone()[0]

    def count_by_flag(
        self, column: str, positive: int, period: Period, uf: str | None = None
    ) -> tuple[int, int]:
        """Retorna (casos com `column = positive`, casos com `column` informado)."""
        if column not in {"evolucao", "uti", "vacina_covid", "vacina_gripe"}:
            raise ValueError(f"Coluna não permitida: {column!r}")
        clause, params = self._uf_filter(uf)
        return self._con.execute(
            f"SELECT COUNT(*) FILTER (WHERE {column} = ?), COUNT({column}) "
            f"FROM srag WHERE dt_sintomas BETWEEN ? AND ?{clause}",
            [positive, period.start, period.end, *params],
        ).fetchone()

    def daily_cases(self, period: Period, uf: str | None = None) -> list[tuple[date, int]]:
        clause, params = self._uf_filter(uf, alias="s.")
        return self._con.execute(
            f"""
            SELECT d::DATE AS dia, COUNT(s.dt_sintomas) AS casos
            FROM generate_series(?::DATE, ?::DATE, INTERVAL 1 DAY) AS t(d)
            LEFT JOIN srag s ON s.dt_sintomas = d::DATE{clause}
            GROUP BY dia ORDER BY dia
            """,
            [period.start, period.end, *params],
        ).fetchall()

    def monthly_cases(self, period: Period, uf: str | None = None) -> list[tuple[date, int]]:
        clause, params = self._uf_filter(uf, alias="s.")
        return self._con.execute(
            f"""
            SELECT m::DATE AS mes, COUNT(s.dt_sintomas) AS casos
            FROM generate_series(date_trunc('month', ?::DATE), date_trunc('month', ?::DATE),
                                 INTERVAL 1 MONTH) AS t(m)
            LEFT JOIN srag s
              ON date_trunc('month', s.dt_sintomas) = m
             AND s.dt_sintomas <= ?::DATE{clause}
            GROUP BY mes ORDER BY mes
            """,
            [period.start, period.end, period.end, *params],
        ).fetchall()
