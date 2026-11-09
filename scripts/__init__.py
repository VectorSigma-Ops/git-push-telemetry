"""Git Push Telemetry plugin for Hermes Agent."""

from __future__ import annotations

import logging
import os
import sys

from hermes_cli.config import load_config_readonly  # type: ignore[reportMissingImports]
from hermes_cli.plugins import PluginContext  # type: ignore[reportMissingImports]

_current_dir = os.path.dirname(os.path.abspath(__file__))  # noqa: PTH120, PTH100
if _current_dir not in sys.path:
    sys.path.insert(0, _current_dir)

from git_push_hooks import (  # noqa: E402,F401 executed at module load, intentionally lazy
    git_push_post_tool_call,
    git_push_pre_tool_call,
    set_config,
)

logger = logging.getLogger(__name__)


def register(ctx: PluginContext) -> None:
    logger.info("Registering git_push_telemetry plugin")

    settings: dict = {}
    try:
        cfg = load_config_readonly() or {}
        plugins_config = cfg.get("plugins", {})
        entries = plugins_config.get("entries", {})
        plugin_entry = entries.get("git_push_telemetry", {})
        settings = plugin_entry.get("settings", {}) or {}
    except Exception as e:
        logger.warning(f"Failed to load config: {e}")
        settings = {}

    set_config(settings)

    if settings.get("enabled", True):
        ctx.register_hook("pre_tool_call", git_push_pre_tool_call)
        ctx.register_hook("post_tool_call", git_push_post_tool_call)
        logger.info("git_push_telemetry registered via hooks")
    else:
        logger.info("git_push_telemetry loaded but disabled by settings")