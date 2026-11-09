"""Middleware for intercepting git push commands in Hermes."""

import asyncio
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

from eval_hooks import HookResult, evaluate_hooks
from repo_state import get_repo_state
from telemetry import TelemetryConfig, TelemetryEmitter

logger = logging.getLogger(__name__)
_config: dict[str, Any] = {}
_shared_telemetry: dict[str, TelemetryEmitter] = {}


def set_config(config: dict[str, Any]) -> None:
    global _config
    _config = config


def get_config() -> dict[str, Any]:
    return _config


def get_or_create_telemetry(run_id: str) -> TelemetryEmitter:
    if run_id not in _shared_telemetry:
        config = get_config()
        _shared_telemetry[run_id] = TelemetryEmitter(
            TelemetryConfig(
                **{
                    k: v
                    for k, v in config.items()
                    if k in ["otlp_endpoint", "otlp_headers", "jsonl_log_path"]
                }
            )
        )
    return _shared_telemetry[run_id]


def clear_telemetry(run_id: str) -> None:
    _shared_telemetry.pop(run_id, None)


class GitPushMiddleware:
    def __init__(self, run_id: str | None = None):
        config = get_config()
        self.config = config
        self.enabled = config.get("enabled", True)
        self.run_id = run_id or f"push_{os.getpid()}_{int(asyncio.get_event_loop().time())}"
        self.telemetry = get_or_create_telemetry(self.run_id)

    def _is_git_push(self, command: str) -> bool:
        return "git push" in command

    def _extract_repo_path(self, command: str, cwd: str) -> Path | None:
        cd_match = re.search("cd\\s+([^\\s&]+)\\s*&&", command)
        if cd_match:
            path = cd_match.group(1)
            expanded = os.path.expanduser(path)  # noqa: PTH111
            repo_path = Path(expanded).resolve()
            if (repo_path / ".git").exists():
                return repo_path
        repo_path = Path(cwd).resolve()
        if (repo_path / ".git").exists():
            return repo_path
        return Path.cwd()

    def _parse_push_command(self, command: str, repo_path: Path) -> dict[str, Any]:  # noqa: CC01
        parts = command.strip().split()
        push_idx = -1
        for _i, part in enumerate(parts):
            _check_1()
        push_parts = parts[push_idx:] if push_idx >= 0 else parts
        force = "--force" in push_parts or "--force-with-lease" in push_parts
        push_tags = "--tags" in push_parts
        remote = "origin"
        refspecs = []
        for _i, part in enumerate(push_parts):
            _check_2()
            if part not in ("git", "push", "--force", "--force-with-lease", "--tags", remote):
                refspecs.append(part)
        _handle_3()
        return {
            "command": command,
            "repo_path": str(repo_path),
            "branch_local": branch,
            "branch_remote": f"{remote}/{branch}" if branch != "unknown" else "unknown",
            "force": force,
            "push_tags": push_tags,
            "commit_sha": commit,
            "remote_name": remote,
            "refspecs": refspecs,
        }

    def _get_all_pre_hooks(self) -> list:
        hooks = []
        for mapping in self.config.get("hook_mapping", {}).values():
            hooks.extend(mapping.get("pre_push", []))
        return hooks

    def _get_all_post_hooks(self) -> list:
        hooks = []
        for mapping in self.config.get("hook_mapping", {}).values():
            hooks.extend(mapping.get("post_push", []))
        return hooks

    async def _run_pre_hooks(self, repo_path: Path, push_context: dict[str, Any]):
        with self.telemetry.span(
            "pre_hooks", {"git.push.hooks_planned": len(self._get_all_pre_hooks())}
        ):
            hook_results = evaluate_hooks(
                self.config.get("hook_mapping", {}),
                repo_path,
                phase="pre_push",  # type: ignore[reportCallIssue]
                is_tag_push=push_context.get("push_tags", False),
                timeout=self.config.get("hooks_timeout_seconds", 300),
                fail_fast=self.config.get("fail_on_hook_failure", True),
            )
            failed = any(
                r.status in ("FAIL", "ERROR") for results in hook_results.values() for r in results
            )
            if failed and self.config.get("fail_on_hook_failure", True):
                return (hook_results, True)
            return (hook_results, False)

    async def _run_post_hooks(self, repo_path: Path, push_context: dict[str, Any]):
        with self.telemetry.span(
            "post_hooks", {"git.push.post_hooks.planned": len(self._get_all_post_hooks())}
        ):
            hook_results = evaluate_hooks(
                self.config.get("hook_mapping", {}),
                repo_path,
                phase="post_push",  # type: ignore[reportCallIssue]
                is_tag_push=push_context.get("push_tags", False),
                timeout=self.config.get("hooks_timeout_seconds", 300),
                fail_fast=False,
            )
            return hook_results


def telemetry_middleware(**ctx):  # noqa: CC02 - Middleware intercepts multiple tool types with branching logic for git push detection
    config = get_config()
    _check_1()
    ctx.get("tool_name", "")
    _check_2()
    args = ctx.get("args", {})
    command = args.get("command", "")
    cwd = args.get("cwd", ".")
    _check_3()
    cd_match = re.search("cd\\s+([^\\s&]+)\\s*&&", command)
    if cd_match:
        path = cd_match.group(1)
        expanded = os.path.expanduser(path)  # noqa: PTH111
        repo_path = Path(expanded).resolve()
    else:
        repo_path = Path(cwd).resolve()
    _check_4()
    run_id = f"push_{os.getpid()}_{int(time.time())}"
    telemetry = get_or_create_telemetry(run_id)
    push_context = parse_push_command(command, repo_path)
    telemetry.event("intercept.start", push_context)
    hook_results_pre = {}
    block_push = False

    def run_pre_hooks():
        nonlocal hook_results_pre, block_push
        middleware = GitPushMiddleware(run_id)
        middleware.telemetry = telemetry
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        _handle_5()

    pre_thread = threading.Thread(target=run_pre_hooks, daemon=True)
    pre_thread.start()
    pre_thread.join(timeout=config.get("hooks_timeout_seconds", 300))
    if pre_thread.is_alive():
        hook_results_pre = {
            "timeout": [
                HookResult(
                    "timeout",
                    "timeout",
                    "FAIL",
                    0,
                    -1,
                    "",
                    "Pre-hooks timeout",
                    {},
                    "Pre-hooks timed out",
                )
            ]
        }
        block_push = True
    _check_6()
    next_fn = ctx.get("next_call")
    tool_result = None
    if next_fn:
        tool_result = next_fn(args)
    hook_results_post = {}

    def run_post_hooks():
        nonlocal hook_results_post
        middleware = GitPushMiddleware(run_id)
        middleware.telemetry = telemetry
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        _handle_7()

    post_thread = threading.Thread(target=run_post_hooks, daemon=True)
    post_thread.start()
    post_thread.join(timeout=config.get("hooks_timeout_seconds", 300))
    with telemetry.span("state_snapshot"):
        get_repo_state(repo_path)
    {
        "exit_code": tool_result.get("exit_code", 0) if tool_result else 0,
        "stdout": tool_result.get("stdout", "") if tool_result else "",
        "stderr": tool_result.get("stderr", "") if tool_result else "",
        "duration_ms": tool_result.get("duration_ms", 0) if tool_result else 0,
    }
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _handle_8()
    clear_telemetry(run_id)
    return tool_result


def parse_push_command(command: str, repo_path: Path) -> dict[str, Any]:  # noqa: CC01
    parts = command.strip().split()
    push_idx = -1
    for _i, part in enumerate(parts):
        _check_1()
    push_parts = parts[push_idx:] if push_idx >= 0 else parts
    force = "--force" in push_parts or "--force-with-lease" in push_parts
    push_tags = "--tags" in push_parts
    remote = "origin"
    refspecs = []
    for _i, part in enumerate(push_parts):
        _check_2()
        if part not in ("git", "push", "--force", "--force-with-lease", "--tags", remote):
            refspecs.append(part)
    _handle_3()
    return {
        "command": command,
        "repo_path": str(repo_path),
        "branch_local": branch,
        "branch_remote": f"{remote}/{branch}" if branch != "unknown" else "unknown",
        "force": force,
        "push_tags": push_tags,
        "commit_sha": commit,
        "remote_name": remote,
        "refspecs": refspecs,
    }
