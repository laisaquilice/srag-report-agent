"""Detecção e mascaramento de dados pessoais (PII) em texto livre.

Aplicado ao conteúdo das notícias antes de chegar ao LLM e ao texto final do relatório.
"""

from __future__ import annotations

import re

_PATTERNS: dict[str, re.Pattern[str]] = {
    "EMAIL": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    "CPF": re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b"),
    "CNS": re.compile(r"\b[1-9]\d{2}\s?\d{4}\s?\d{4}\s?\d{4}\b"),  # Cartão Nacional de Saúde
    "TELEFONE": re.compile(r"(?:\+?55\s?)?\(?\b\d{2}\)?\s?9?\d{4}-?\d{4}\b"),
}


def find_pii(text: str) -> dict[str, int]:
    """Conta ocorrências de cada tipo de PII encontrado."""
    found = {kind: len(p.findall(text)) for kind, p in _PATTERNS.items()}
    return {kind: n for kind, n in found.items() if n}


def mask_pii(text: str) -> str:
    for kind, pattern in _PATTERNS.items():
        text = pattern.sub(f"[{kind} REMOVIDO]", text)
    return text
