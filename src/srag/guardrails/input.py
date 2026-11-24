"""Guardrail de entrada: valida os parâmetros do pedido de relatório."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, field_validator

from srag.config import UFS


class ReportRequest(BaseModel):
    uf: str | None = None
    reference_date: date | None = None

    @field_validator("uf")
    @classmethod
    def _valid_uf(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().upper()
        if value not in UFS:
            raise ValueError(f"UF inválida: {value!r}. Use a sigla de um estado brasileiro.")
        return value


def resolve_reference_date(
    request: ReportRequest, data_min: date | None, data_max: date | None
) -> date:
    """Usa a data pedida (se dentro da base) ou a data mais recente disponível."""
    if data_min is None or data_max is None:
        raise ValueError("A base não tem casos para o recorte pedido.")
    if request.reference_date is None:
        return data_max
    if not data_min <= request.reference_date <= data_max:
        raise ValueError(
            f"Data de referência {request.reference_date} fora do intervalo da base "
            f"({data_min} a {data_max})."
        )
    return request.reference_date
