"""Adapter exports for service snapshot generation."""

from service_platform.publishers.adapters.s2_adapter import S2Adapter, S2AdapterInput
from service_platform.publishers.adapters.template_adapter import (
    TemplateAdapter,
    TemplateAdapterInput,
)

__all__ = [
    "S2Adapter",
    "S2AdapterInput",
    "TemplateAdapter",
    "TemplateAdapterInput",
]
