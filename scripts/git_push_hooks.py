"""Hook-based interceptors for git push commands in Hermes.

Replaces the middleware approach with pre_tool_call / post_tool_call hooks
that work everywhere (TUI, CLI, API, cron).
"""

import asyncio
import json
import logging
import os
import re
import threading
import time
import traceback
from pathlib import Path
from typing import Any

from eval_hooks import HookResult, evaluate_hooks
from git_push_report import generate_report
from repo_state import get_repo_state
from telemetry import TelemetryConfig, TelemetryEmitter

logger = logging.getLogger(__name__)

# Shared state for coordinating pre/post hooks of the same git push call
_pending_pushes: dict[str, dict[str, Any]] = {}
_pending_lock = threading.Lock()

_config: dict[str, Any] = {}


def set_config(config: dict[str, Any]) -> None:
    global _config
    _config = config
    logger.debug(f"set_config called with keys: {list(config.keys())}")


def get_config() -> dict[str, Any]:
    return _config


def get_or_create_telemetry(run_id: str) -> TelemetryEmitter:
    if run_id not in _shared_telemetry:
        config = get_config()
        _shared_telemetry[run_id] = TelemetryEmitter(TelemetryConfig(**{
            k: v for k, v in config.items()
            if k in ["otlp_endpoint", "otlp_headers", "jsonl_log_path"]
        }))
    return _shared_telemetry[run_id]


_shared_telemetry: dict[str, TelemetryEmitter] = {}


def clear_telemetry(run_id: str) -> None:
    _shared_telemetry.pop(run_id, None)


def _is_git_push(command: str) -> bool:
    return "git push" in command


def _extract_repo_path(command: str, cwd: str) -> Path | None:
    cd_match = re.search(r'cd\s+([^\s&]+)\s*&&', command)
    if cd_match:
        path = cd_match.group(1)
        expanded = os.path.expanduser(path)
        repo_path = Path(expanded).resolve()
        if (repo_path / ".git").exists():
            return repo_path

    repo_path = Path(cwd).resolve()
    if (repo_path / ".git").exists():
        return repo_path

    return Path(".").resolve()


def _parse_push_command(command: str, repo_path: Path) -> dict[str, Any]:
    parts = command.strip().split()
    push_idx = -1
    for i, part in enumerate(parts):
        if part == "git" and i + 1 < len(parts) and parts[i + 1] == "push":
            push_idx = i
            break

    if push_idx >= 0:
        push_parts = parts[push_idx:]
    else:
        push_parts = parts

    force = "--force" in push_parts or "--force-with-lease" in push_parts
    push_tags = "--tags" in push_parts
    remote = "origin"
    refspecs = []
    for i, part in enumerate(push_parts):
        if part == "push" and i + 1 < len(push_parts):
            remote = push_parts[i + 1]
        if part not in ("git", "push", "--force", "--force-with-lease", "--tags", remote):
            refspecs.append(part)

    import subprocess
    try:
        branch = subprocess.run(["git", "branch", "--show-current"], cwd=repo_path, capture_output=True, text=True).stdout.strip()
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=repo_path, capture_output=True, text=True).stdout.strip()
    except:
        branch = "unknown"
        commit = "unknown"
    return {
        "command": command, "repo_path": str(repo_path),
        "branch_local": branch, "branch_remote": f"{remote}/{branch}" if branch != "unknown" else "unknown",
        "force": force, "push_tags": push_tags, "commit_sha": commit,
        "remote_name": remote, "refspecs": refspecs,
    }


def _make_push_key(task_id: str, session_id: str, tool_call_id: str) -> str:
    """Unique key for a push call, scoped by owner."""
    owner = task_id or session_id or "default"
    return f"{owner}:{tool_call_id}"


def _run_pre_hooks_async(run_id: str, repo_path: Path, push_context: dict[str, Any]) -> tuple:
    """Run pre-push hooks in async context."""
    config = get_config()
    hook_mapping = config.get("hook_mapping", {})
    # Filter to only pre_push hooks
    pre_hooks = {skill: {"pre_push": hooks.get("pre_push", [])} for skill, hooks in hook_mapping.items() if hooks.get("pre_push")}
    telemetry = get_or_create_telemetry(run_id)

    async def _async_run():
        with telemetry.span("pre_hooks", {
            "git.push.hooks_planned": sum(len(m.get("pre_push", [])) for m in hook_mapping.values()),
        }):
            hook_results = evaluate_hooks(
                pre_hooks,
                repo_path,
                is_tag_push=push_context.get("push_tags", False),
                timeout=config.get("hooks_timeout_seconds", 300),
                fail_fast=config.get("fail_on_hook_failure", True)
            )

            failed = any(
                r.status in ("FAIL", "ERROR")
                for results in hook_results.values()
                for r in results
            )
            return hook_results, failed

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_async_run())
    finally:
        loop.close()


def _run_post_hooks_async(run_id: str, repo_path: Path, push_context: dict[str, Any]) -> dict[str, list]:
    """Run post-push hooks with timeout."""
    config = get_config()
    hook_mapping = config.get("hook_mapping", {})
    # Filter to only post_push hooks
    post_hooks = {skill: {"post_push": hooks.get("post_push", [])} for skill, hooks in hook_mapping.items() if hooks.get("post_push")}
    telemetry = get_or_create_telemetry(run_id)

    async def _async_run():
        with telemetry.span(
            "post_hooks",
            {
                "git.push.post_hooks.planned": sum(len(m.get("post_push", [])) for m in hook_mapping.values()),
            },
        ):
            hook_results = evaluate_hooks(
                post_hooks,
                repo_path,
                is_tag_push=push_context.get("push_tags", False),
                timeout=config.get("hooks_timeout_seconds", 300),
                fail_fast=False
            )
            return hook_results

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        # Add timeout wrapper for the entire post-hooks execution
        timeout_seconds = config.get("hooks_timeout_seconds", 300)
        return loop.run_until_complete(asyncio.wait_for(_async_run(), timeout=timeout_seconds))
    except asyncio.TimeoutError:
        logger.warning(f"Post-hooks timed out after {timeout_seconds}s for run_id={run_id}")
        # Return timeout error for all planned post-hooks
        config = get_config()
        hook_mapping = config.get("hook_mapping", {})
        post_hooks = {skill: {"post_push": hooks.get("post_push", [])} for skill, hooks in hook_mapping.items() if hooks.get("post_push")}
        timeout_results = {}
        for skill, hooks_dict in post_hooks.items():
            for hook in hooks_dict.get("post_push", []):
                timeout_results.setdefault(skill, []).append(
                    HookResult(
                        skill=skill,
                        hook=hook,
                        status="FAIL",
                        duration_ms=0,
                        exit_code=-1,
                        stdout="",
                        stderr=f"Post-hook timed out after {timeout_seconds}s",
                        findings={},
                        details=f"Timeout after {timeout_seconds}s"
                    )
                )
        return timeout_results
    except Exception as e:
        logger.error(f"Post-hooks error for run_id={run_id}: {e}")
        logger.error(traceback.format_exc())
        return {"error": [HookResult("error", "error", "ERROR", 0, -1, "", str(e), {}, "Post-hooks exception")]}
    finally:
        loop.close()

def _generate_report_async(run_id: str, hook_results_pre: dict, hook_results_post: dict,
                           repo_path: Path, push_context: dict, push_result: dict, repo_state: Any) -> None:
    """Generate markdown report in async context with timeout."""
    telemetry = get_or_create_telemetry(run_id)
    config = get_config()

    async def _async_run():
        with telemetry.span("generate_report"):
            await generate_report(
                telemetry, hook_results_pre, hook_results_post,
                repo_path, push_context, push_result, repo_state, config
            )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        # Add timeout wrapper for report generation
        timeout_seconds = config.get("hooks_timeout_seconds", 300)
        loop.run_until_complete(asyncio.wait_for(_async_run(), timeout=timeout_seconds))
        logger.debug(f"Report generated successfully for run_id={run_id}")
    except asyncio.TimeoutError:
        logger.error(f"Report generation timed out after {timeout_seconds}s for run_id={run_id}")
        raise
    except Exception as e:
        logger.error(f"Report generation error for run_id={run_id}: {e}")
        logger.error(traceback.format_exc())
        raise
    finally:
        loop.close()


def git_push_pre_tool_call(
    tool_name: str = "",
    args: dict[str, Any] | None = None,
    task_id: str = "",
    session_id: str = "",
    tool_call_id: str = "",
    **_: Any
) -> None:
    """pre_tool_call hook: intercept git push, run pre-push hooks, store state for post-hook."""
    config = get_config()
    if not config.get("enabled", True):
        return

    if tool_name != "terminal":
        return

    if not isinstance(args, dict):
        return

    command = args.get("command", "")
    if not _is_git_push(command):
        return

    cwd = args.get("cwd", ".")
    repo_path = _extract_repo_path(command, cwd)
    if not repo_path or not (repo_path / ".git").exists():
        return

    # Generate unique run_id and push key
    run_id = f"push_{os.getpid()}_{int(time.time())}"
    push_key = _make_push_key(task_id, session_id, tool_call_id)

    push_context = _parse_push_command(command, repo_path)

    logger.debug(f"pre_tool_call: intercept.start, run_id={run_id}, push_key={push_key}")

    telemetry = get_or_create_telemetry(run_id)
    telemetry.event("intercept.start", push_context)

    # Run pre-hooks in background thread with timeout
    hook_results_pre = {}
    block_push = False

    def run_pre():
        nonlocal hook_results_pre, block_push
        try:
            hook_results_pre, block_push = _run_pre_hooks_async(run_id, repo_path, push_context)
        except Exception as e:
            logger.error(f"Pre-hooks error: {e}")
            logger.error(traceback.format_exc())
            hook_results_pre = {"error": [HookResult("error", "error", "ERROR", 0, -1, "", str(e), {}, "Pre-hooks exception")]}
            block_push = True

    pre_thread = threading.Thread(target=run_pre, daemon=True)
    pre_thread.start()
    pre_thread.join(timeout=config.get("hooks_timeout_seconds", 300))

    if pre_thread.is_alive():
        logger.warning("Pre-hooks timed out!")
        hook_results_pre = {"timeout": [HookResult("timeout", "timeout", "FAIL", 0, -1, "", "Pre-hooks timeout", {}, "Pre-hooks timed out")]}
        block_push = True

    # Store state for post_tool_call
    with _pending_lock:
        _pending_pushes[push_key] = {
            "run_id": run_id,
            "repo_path": repo_path,
            "push_context": push_context,
            "hook_results_pre": hook_results_pre,
            "block_push": block_push,
            "start_time": time.time(),
        }

    # If hooks failed and fail_on_hook_failure, we need to block the tool
    # pre_tool_call hooks fail CLOSED - returning a dict blocks the tool
    if block_push and config.get("fail_on_hook_failure", True):
        # Generate blocked report
        try:
            _generate_report_async(run_id, hook_results_pre, {}, repo_path, push_context,
                                  {"exit_code": -1, "stdout": "", "stderr": "Blocked by pre-push hooks"}, None)
        except Exception as e:
            logger.debug("Blocked push report error: %s", e)
            logger.debug(traceback.format_exc())

        # Return a block directive - fails closed
        return {
            "block": True,
            "message": "Pre-push hooks failed or timed out",
            "hook_results": hook_results_pre
        }

    logger.debug(f"pre_tool_call: completed, run_id={run_id}")


def git_push_post_tool_call(
    tool_name: str = "",
    args: dict[str, Any] | None = None,
    task_id: str = "",
    session_id: str = "",
    tool_call_id: str = "",
    result: Any = None,
    duration_ms: int = 0,
    **_: Any
) -> None:
    """post_tool_call hook: run post-push hooks, capture repo state, generate report."""
    config = get_config()
    if not config.get("enabled", True):
        return

    if tool_name != "terminal":
        return

    push_key = _make_push_key(task_id, session_id, tool_call_id)

    # Retrieve pending push state
    with _pending_lock:
        pending = _pending_pushes.pop(push_key, None)

    if not pending:
        return  # No matching pre_tool_call (not a git push we intercepted)

    run_id = pending["run_id"]
    repo_path = pending["repo_path"]
    push_context = pending["push_context"]
    hook_results_pre = pending["hook_results_pre"]

    logger.debug(f"post_tool_call: start, run_id={run_id}, push_key={push_key}")

    # Parse tool result
    if isinstance(result, str):
        try:
            tool_result = json.loads(result)
        except:
            tool_result = {"exit_code": 0, "stdout": result, "stderr": "", "duration_ms": duration_ms}
    elif isinstance(result, dict):
        tool_result = result
    else:
        tool_result = {"exit_code": 0, "stdout": str(result), "stderr": "", "duration_ms": duration_ms}

    push_result = {
        "exit_code": tool_result.get("exit_code", 0),
        "stdout": tool_result.get("stdout", ""),
        "stderr": tool_result.get("stderr", ""),
        "duration_ms": tool_result.get("duration_ms", duration_ms),
    }

    # Run post-hooks
    hook_results_post = _run_post_hooks_async(run_id, repo_path, push_context)
    telemetry = get_or_create_telemetry(run_id)
    telemetry.event("post_hooks.end", {"hooks_run": sum(len(v) for v in hook_results_post.values())})

    # Capture repo state
    with get_or_create_telemetry(run_id).span("state_snapshot"):
        repo_state = get_repo_state(repo_path)

    # Generate report
    logger.debug("Generating final report...")
    try:
        _generate_report_async(run_id, hook_results_pre, hook_results_post,
                              repo_path, push_context, push_result, repo_state, config)
        telemetry.event("report.generated", {"run_id": run_id})
    except Exception as e:
        logger.error("Report generation error: %s", e)
        logger.error(traceback.format_exc())
        telemetry.event("report.failed", {"run_id": run_id, "error": str(e)})

    clear_telemetry(run_id)
    logger.debug(f"post_tool_call: completed, run_id={run_id}")