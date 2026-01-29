"""Services package for FAIRifier."""

from .confidence_aggregator import aggregate_confidence
from .fair_data_station import FAIRDataStationClient
from .mineru_client import MinerUClient, MinerUConversionError

# Mem0 service is optional - only import if available
try:
    from .mem0_service import Mem0Service, get_mem0_service, build_mem0_config, reset_mem0_service
except ImportError:
    Mem0Service = None
    get_mem0_service = None
    build_mem0_config = None
    reset_mem0_service = None

__all__ = [
    "aggregate_confidence",
    "FAIRDataStationClient",
    "MinerUClient",
    "MinerUConversionError",
    "Mem0Service",
    "get_mem0_service",
    "build_mem0_config",
    "reset_mem0_service",
]
