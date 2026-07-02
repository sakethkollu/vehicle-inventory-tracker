"""Shared application configuration and logging."""

from vehicle_inventory.core.config import Settings, get_settings
from vehicle_inventory.core.logging import configure_logging, get_logger

__all__ = ["Settings", "configure_logging", "get_logger", "get_settings"]
