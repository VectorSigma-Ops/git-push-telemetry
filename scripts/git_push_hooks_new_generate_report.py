"""Generate markdown report in async context with timeout."""

import asyncio
import logging
import traceback
from pathlib import Path
from typing import Any

from .git_push_hooks import get_config, get_or_create_telemetry
from .git_push_report import generate_report

logger = logging.getLogger(__name__)


def _generate_report_async(  # noqa: VULTURE
    run_id: str,
    hook_results_pre: dict,
    hook_results_post: dict,
    repo_path: Path,
    push_context: dict,
    push_result: dict,
    repo_state: Any,
) -> None:
    """Generate markdown report in async context with timeout."""
    telemetry = get_or_create_telemetry(run_id)
    config = get_config()

    async def _async_run():
        with telemetry.span("generate_report"):
            await generate_report(  # type: ignore[reportGeneralTypeIssues]
                telemetry,
                hook_results_pre,
                hook_results_post,
                repo_path,
                push_context,
                push_result,
                repo_state,
                config,
            )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        # Add timeout wrapper for report generation
        timeout_seconds = config.get("hooks_timeout_seconds", 300)
        loop.run_until_complete(asyncio.wait_for(_async_run(), timeout=timeout_seconds))
        logger.debug(f"Report generated successfully for run_id={run_id}")
    except asyncio.TimeoutError:
        logger.error(f"Report generation timed out after {timeout_seconds}s for run_id={run_id}")  # type: ignore[reportPossiblyUnboundVariable]
        raise
    except Exception as e:
        logger.error(f"Report generation error for run_id={run_id}: {e}")
        logger.error(traceback.format_exc())
        raise
    finally:
        loop.close()
