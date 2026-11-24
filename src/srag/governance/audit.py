"""Trilha de auditoria: cada passo, decisão, chamada de LLM e de ferramenta vira um
evento JSONL em `logs/run_<id>.jsonl`, além de um manifesto resumido por execução."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult


def _json_default(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    return str(obj)


class AuditLogger:
    def __init__(self, logs_dir: Path, run_id: str | None = None) -> None:
        self.run_id = (
            run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
        )
        logs_dir.mkdir(parents=True, exist_ok=True)
        self.path = logs_dir / f"run_{self.run_id}.jsonl"
        self.decisions: list[dict[str, Any]] = []

    def log(self, step: str, event: str, **data: Any) -> None:
        record = {
            "ts": datetime.now(UTC).isoformat(),
            "run_id": self.run_id,
            "step": step,
            "event": event,
            **data,
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, default=_json_default) + "\n")

    def decision(self, step: str, decision: str, reason: str, **data: Any) -> None:
        """Registra uma decisão do agente com a justificativa (aparece no relatório)."""
        self.decisions.append({"step": step, "decision": decision, "reason": reason})
        self.log(step, "decision", decision=decision, reason=reason, **data)

    @contextmanager
    def step(self, name: str, **inputs: Any) -> Iterator[None]:
        start = time.perf_counter()
        self.log(name, "start", inputs=inputs)
        try:
            yield
        except Exception as exc:
            self.log(
                name, "error", error=repr(exc), latency_s=round(time.perf_counter() - start, 3)
            )
            raise
        self.log(name, "end", latency_s=round(time.perf_counter() - start, 3))


class AuditCallbackHandler(BaseCallbackHandler):
    """Registra prompts, modelo, uso de tokens e chamadas de ferramentas do LangChain."""

    def __init__(self, audit: AuditLogger) -> None:
        self._audit = audit

    def on_chat_model_start(self, serialized: dict, messages: list, **kwargs: Any) -> None:
        prompt = [[{"role": m.type, "content": m.content} for m in batch] for batch in messages]
        self._audit.log(
            "llm",
            "request",
            model=(kwargs.get("invocation_params") or {}).get("model_name")
            or (kwargs.get("metadata") or {}).get("ls_model_name"),
            prompt=prompt,
        )

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        usage = (response.llm_output or {}).get("token_usage")
        generations = [
            {"text": g.text, "tool_calls": getattr(getattr(g, "message", None), "tool_calls", None)}
            for batch in response.generations
            for g in batch
        ]
        self._audit.log("llm", "response", token_usage=usage, generations=generations)

    def on_llm_error(self, error: BaseException, **kwargs: Any) -> None:
        self._audit.log("llm", "error", error=repr(error))


def file_sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()
