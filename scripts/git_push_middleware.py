"""Middleware for intercepting git push commands in Hermes."""

import os
import sys
import json
import asyncio
import logging
import re
import threading
import traceback
import time
from typing import Dict, Any, Optional
from pathlib import Path

from telemetry import TelemetryEmitter, TelemetryConfig
from eval_hooks import evaluate_hooks, HookResult
from repo_state import get_repo_state, format_repo_state
from git_push_report import generate_report

logger = logging.getLogger(__name__)

_config: Dict[str, Any] = {}
_shared_telemetry: Dict[str, TelemetryEmitter] = {}


def set_config(config: Dict[str, Any]) -> None:
    global _config
    _config = config
    print(f"[CONFIG] set_config called with keys: {list(config.keys())}", file=sys.stderr, flush=True)


def get_config() -> Dict[str, Any]:
    return _config


def get_or_create_telemetry(run_id: str) -> TelemetryEmitter:
    if run_id not in _shared_telemetry:
        config = get_config()
        _shared_telemetry[run_id] = TelemetryEmitter(TelemetryConfig(**{
            k: v for k, v in config.items()
            if k in ["otlp_endpoint", "otlp_headers", "jsonl_log_path"]
        }))
    return _shared_telemetry[run_id]


def clear_telemetry(run_id: str) -> None:
    if run_id in _shared_telemetry:
        del _shared_telemetry[run_id]


class GitPushMiddleware:
    def __init__(self, run_id: str = None):
        config = get_config()
        self.config = config
        self.enabled = config.get("enabled", True)
        self.run_id = run_id or f"push_{os.getpid()}_{int(asyncio.get_event_loop().time())}"
        self.telemetry = get_or_create_telemetry(self.run_id)
        print(f"[MIDDLEWARE] GitPushMiddleware initialized, run_id={self.run_id}, enabled={self.enabled}", file=sys.stderr, flush=True)

    def _is_git_push(self, command: str) -> bool:
        return "git push" in command

    def _extract_repo_path(self, command: str, cwd: str) -> Optional[Path]:
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

    def _parse_push_command(self, command: str, repo_path: Path) -> Dict[str, Any]:
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

    def _get_all_pre_hooks(self) -> list:
        hooks = []
        for skill, mapping in self.config.get("hook_mapping", {}).items():
            hooks.extend(mapping.get("pre_push", []))
        return hooks

    def _get_all_post_hooks(self) -> list:
        hooks = []
        for skill, mapping in self.config.get("hook_mapping", {}).items():
            hooks.extend(mapping.get("post_push", []))
        return hooks

    async def _run_pre_hooks(self, repo_path: Path, push_context: Dict[str, Any]):
        with self.telemetry.span("pre_hooks", {
            "git.push.hooks_planned": len(self._get_all_pre_hooks()),
        }) as span:
            hook_results = evaluate_hooks(
                self.config.get("hook_mapping", {}),
                repo_path,
                phase="pre_push",
                is_tag_push=push_context.get("push_tags", False),
                timeout=self.config.get("hooks_timeout_seconds", 300),
                fail_fast=self.config.get("fail_on_hook_failure", True)
            )

            failed = any(
                r.status in ("FAIL", "ERROR")
                for results in hook_results.values()
                for r in results
            )

            if failed and self.config.get("fail_on_hook_failure", True):
                return hook_results, True
            
            return hook_results, False

    async def _run_post_hooks(self, repo_path: Path, push_context: Dict[str, Any]):
        with self.telemetry.span("post_hooks", {
            "git.push.post_hooks.planned": len(self._get_all_post_hooks()),
        }) as span:
            hook_results = evaluate_hooks(
                self.config.get("hook_mapping", {}),
                repo_path,
                phase="post_push",
                is_tag_push=push_context.get("push_tags", False),
                timeout=self.config.get("hooks_timeout_seconds", 300),
                fail_fast=False
            )
            return hook_results


def telemetry_middleware(**ctx):
    config = get_config()
    print(f"[MIDDLEWARE] tool_execution invoked", file=sys.stderr, flush=True)
    
    if not config.get("enabled", True):
        next_fn = ctx.get("next_call")
        if next_fn:
            return next_fn(ctx.get("args", {}))
        return None
    
    tool_name = ctx.get("tool_name", "")
    if tool_name != "terminal":
        next_fn = ctx.get("next_call")
        if next_fn:
            return next_fn(ctx.get("args", {}))
        return None
    
    args = ctx.get("args", {})
    command = args.get("command", "")
    cwd = args.get("cwd", ".")
    
    if "git push" not in command:
        next_fn = ctx.get("next_call")
        if next_fn:
            return next_fn(ctx.get("args", {}))
        return None
    
    cd_match = re.search(r'cd\s+([^\s&]+)\s*&&', command)
    if cd_match:
        path = cd_match.group(1)
        expanded = os.path.expanduser(path)
        repo_path = Path(expanded).resolve()
    else:
        repo_path = Path(cwd).resolve()
    
    if not (repo_path / ".git").exists():
        next_fn = ctx.get("next_call")
        if next_fn:
            return next_fn(ctx.get("args", {}))
        return None
    
    run_id = f"push_{os.getpid()}_{int(time.time())}"
    telemetry = get_or_create_telemetry(run_id)
    
    push_context = parse_push_command(command, repo_path)
    
    telemetry.event("intercept.start", push_context)
    print(f"[MIDDLEWARE] intercept.start, run_id={run_id}", file=sys.stderr, flush=True)
    
    hook_results_pre = {}
    block_push = False
    
    def run_pre_hooks():
        nonlocal hook_results_pre, block_push
        middleware = GitPushMiddleware(run_id)
        middleware.telemetry = telemetry
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            hook_results_pre, block_push = loop.run_until_complete(
                middleware._run_pre_hooks(repo_path, push_context)
            )
        except Exception as e:
            print(f"[MIDDLEWARE] Pre-hooks error: {e}", file=sys.stderr, flush=True)
            traceback.print_exc(file=sys.stderr)
        finally:
            loop.close()
    
    pre_thread = threading.Thread(target=run_pre_hooks, daemon=True)
    pre_thread.start()
    pre_thread.join(timeout=config.get("hooks_timeout_seconds", 300))
    
    if pre_thread.is_alive():
        print(f"[MIDDLEWARE] Pre-hooks timed out!", file=sys.stderr, flush=True)
        hook_results_pre = {"timeout": [HookResult("timeout", "timeout", "FAIL", 0, -1, "", "Pre-hooks timeout", {}, "Pre-hooks timed out")]}
        block_push = True
    
    if block_push and config.get("fail_on_hook_failure", True):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            middleware = GitPushMiddleware(run_id)
            middleware.telemetry = telemetry
            loop.run_until_complete(generate_report(
                hook_results_pre, {}, repo_path, push_context, 
                {"exit_code": -1, "stdout": "", "stderr": "Blocked by pre-push hooks"}, None
            ))
        except Exception as e:
            print(f"[MIDDLEWARE] Blocked push report error: {e}", file=sys.stderr, flush=True)
            traceback.print_exc(file=sys.stderr)
        finally:
            loop.close()
        clear_telemetry(run_id)
        return {"action": "block", "message": "Pre-push hooks failed or timed out"}
    
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
        try:
            hook_results_post = loop.run_until_complete(
                middleware._run_post_hooks(repo_path, push_context)
            )
        except Exception as e:
            print(f"[MIDDLEWARE] Post-hooks error: {e}", file=sys.stderr, flush=True)
            traceback.print_exc(file=sys.stderr)
        finally:
            loop.close()
    
    post_thread = threading.Thread(target=run_post_hooks, daemon=True)
    post_thread.start()
    post_thread.join(timeout=config.get("hooks_timeout_seconds", 300))
    
    with telemetry.span("state_snapshot"):
        repo_state = get_repo_state(repo_path)
    
    push_result = {
        "exit_code": tool_result.get("exit_code", 0) if tool_result else 0,
        "stdout": tool_result.get("stdout", "") if tool_result else "",
        "stderr": tool_result.get("stderr", "") if tool_result else "",
        "duration_ms": tool_result.get("duration_ms", 0) if tool_result else 0,
    }
    
    print(f"[MIDDLEWARE] Generating final report...", file=sys.stderr, flush=True)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(generate_report(
            hook_results_pre, hook_results_post, repo_path, push_context, push_result, repo_state
        ))
    except Exception as e:
        print(f"[MIDDLEWARE] Report generation error: {e}", file=sys.stderr, flush=True)
        traceback.print_exc(file=sys.stderr)
    finally:
        loop.close()
    
    clear_telemetry(run_id)
    
    return tool_result


def parse_push_command(command: str, repo_path: Path) -> Dict[str, Any]:
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
