"""Interface de linha de comando.

srag etl data/raw/INFLUD24.csv data/raw/INFLUD25.csv
srag report [--uf SP] [--ref-date 2025-06-30] [--offline]
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from srag.config import Settings
from srag.data.etl import run_etl
from srag.guardrails.input import ReportRequest
from srag.pipeline import MissingCredentialsError, generate_report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="srag", description="Agente de relatórios de SRAG.")
    sub = parser.add_subparsers(dest="command", required=True)

    etl = sub.add_parser("etl", help="Carrega e limpa os CSVs do Open DATASUS.")
    etl.add_argument("files", nargs="+", type=Path, help="Arquivos CSV (INFLUDxx).")
    etl.add_argument(
        "--encoding", default=None, help="Força a codificação (padrão: detecta por arquivo)."
    )

    report = sub.add_parser("report", help="Gera o relatório (HTML + PDF).")
    report.add_argument("--uf", help="Sigla do estado (padrão: Brasil).")
    report.add_argument(
        "--ref-date", type=date.fromisoformat, help="Data de referência AAAA-MM-DD."
    )
    report.add_argument(
        "--offline", action="store_true", help="Sem LLM e sem notícias (texto determinístico)."
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _parser().parse_args(argv)
    settings = Settings.from_env()

    if args.command == "etl":
        summary = run_etl(args.files, settings.db_path, args.encoding)
        print(
            f"Base gravada em {settings.db_path}: {summary.clean_rows} casos válidos "
            f"({summary.discarded_rows} descartados), de {summary.min_date} a {summary.max_date}."
        )
        return 0

    try:
        request = ReportRequest(uf=args.uf, reference_date=args.ref_date)
        state, audit = generate_report(request, settings, offline=args.offline)
    except (ValidationError, ValueError, MissingCredentialsError, FileNotFoundError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 2

    print(f"Relatório HTML: {state['report_paths']['html']}")
    print(f"Relatório PDF:  {state['report_paths']['pdf']}")
    print(f"Auditoria:      {audit.path}")
    if state["analysis_origin"] == "deterministic" and not args.offline:
        reason = (
            f"falha ao chamar o LLM ({state['llm_error']})"
            if state.get("llm_error")
            else "o texto do LLM foi reprovado pelos guardrails"
        )
        print(f"Aviso: {reason}; usada análise determinística.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
