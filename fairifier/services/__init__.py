"""Services package for FAIRifier."""

from __future__ import annotations

from typing import TYPE_CHECKING

__all__ = [
    "aggregate_confidence",
    "AgentMailbox",
    "FAIRDataStationClient",
    "MinerUClient",
    "MinerUConversionError",
    "mineru_client_from_config",
    "Mem0Service",
    "get_mem0_service",
    "build_mem0_config",
    "reset_mem0_service",
]


def __getattr__(name: str):
    if name == "aggregate_confidence":
        from .confidence_aggregator import aggregate_confidence

        return aggregate_confidence
    if name == "AgentMailbox":
        from .agent_mailbox import AgentMailbox

        return AgentMailbox
    if name == "FAIRDataStationClient":
        from .fair_data_station import FAIRDataStationClient

        return FAIRDataStationClient
    if name in {"MinerUClient", "MinerUConversionError", "mineru_client_from_config"}:
        from . import mineru_client as mc

        return getattr(mc, name)
    if name in {
        "Mem0Service",
        "get_mem0_service",
        "build_mem0_config",
        "reset_mem0_service",
    }:
        from . import mem0_service as ms

        return getattr(ms, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if TYPE_CHECKING:
    from .agent_mailbox import AgentMailbox
    from .confidence_aggregator import aggregate_confidence
    from .fair_data_station import FAIRDataStationClient
    from .mineru_client import MinerUClient, MinerUConversionError, mineru_client_from_config

    try:
        from .mem0_service import (
            Mem0Service,
            build_mem0_config,
            get_mem0_service,
            reset_mem0_service,
        )
    except ImportError:
        Mem0Service = None  # type: ignore[misc, assignment]
        get_mem0_service = None  # type: ignore[misc, assignment]
        build_mem0_config = None  # type: ignore[misc, assignment]
        reset_mem0_service = None  # type: ignore[misc, assignment]
