"""Template adapter to extend for additional quant models."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TemplateAdapterInput:
    source_path: Path


class TemplateAdapter:
    """Minimal skeleton for future model-specific adapters."""

    def __init__(self, adapter_input: TemplateAdapterInput, model_id: str) -> None:
        self.adapter_input = adapter_input
        self.model_id = model_id

    def build_service_payloads(self) -> dict[str, dict[str, Any]]:
        raise NotImplementedError("Implement model-specific CSV parsing before using this adapter.")
