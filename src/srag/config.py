"""Configuração centralizada, lida de variáveis de ambiente (.env)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Domínios de notícias aceitos pela ferramenta de busca (fontes oficiais e imprensa reconhecida).
TRUSTED_NEWS_DOMAINS: tuple[str, ...] = (
    "gov.br",
    "fiocruz.br",
    "paho.org",
    "who.int",
    "g1.globo.com",
    "folha.uol.com.br",
    "estadao.com.br",
    "cnnbrasil.com.br",
    "agenciabrasil.ebc.com.br",
    "uol.com.br",
)

UFS: frozenset[str] = frozenset(
    [
        "AC",
        "AL",
        "AP",
        "AM",
        "BA",
        "CE",
        "DF",
        "ES",
        "GO",
        "MA",
        "MT",
        "MS",
        "MG",
        "PA",
        "PB",
        "PR",
        "PE",
        "PI",
        "RJ",
        "RN",
        "RS",
        "RO",
        "RR",
        "SC",
        "SP",
        "SE",
        "TO",
    ]
)

NOTIFICATION_LAG_DAYS = 14
"""Dias mais recentes ignorados por padrão: ainda estão incompletos por atraso de notificação."""

MIN_CELL_SIZE = 5
"""Contagens abaixo deste valor não geram taxas (supressão de células pequenas)."""


@dataclass(frozen=True)
class Settings:
    openai_api_key: str | None
    openai_model: str
    tavily_api_key: str | None
    db_path: Path
    reports_dir: Path
    logs_dir: Path
    news_domains: tuple[str, ...] = field(default=TRUSTED_NEWS_DOMAINS)
    max_news_searches: int = 3
    max_news_results: int = 5
    news_days: int = 30
    max_analysis_attempts: int = 2

    @classmethod
    def from_env(cls) -> Settings:
        load_dotenv()
        return cls(
            openai_api_key=os.getenv("OPENAI_API_KEY") or None,
            openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            tavily_api_key=os.getenv("TAVILY_API_KEY") or None,
            db_path=Path(os.getenv("SRAG_DB_PATH", "data/processed/srag.duckdb")),
            reports_dir=Path(os.getenv("SRAG_REPORTS_DIR", "reports")),
            logs_dir=Path(os.getenv("SRAG_LOGS_DIR", "logs")),
        )
