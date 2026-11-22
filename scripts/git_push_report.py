"""Report generator for git-push-telemetry: produces standardized markdown report."""

import os
import json
import sys
import traceback
from typing import Dict, Any, Optional
from pathlib import Path
from datetime import datetime

from telemetry import TelemetryEmitter
from eval_hooks import HookResult, format_hook_results
from repo_state import RepoState, format_repo_state


def render_template(template_path: Path, data: Dict[str, Any]) -> str:
    """Simple template rendering with {{key}} substitution."""
    template = template_path.read_text()
    for key, value in data.items():
        template = template.replace(f"{{{{{key}}}}}", str(value))
    return template


def get_status_icon(status: str) -> str:
    return {
        "PASS": "✅",
        "FAIL": "❌",
        "SKIP": "⏭",
        "ERROR": "💥"
    }.get(status, "?")


def format_duration(ms: float) -> str:
    return f"{ms / 1000:.2f}"


def truncate(text: str, max_len: int = 500) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "... [truncated]"


def _convert_hook_results(hook_results: Dict[str, list]) -> Dict[str, list]:
    """Convert serialized hook results back to HookResult-like objects."""
    converted = {}
    for skill, results in hook_results.items():
        converted[skill] = []
        for r in results:
            if isinstance(r, dict):
                class SimpleHookResult:
                    def __init__(self, d):
                        self.skill = d.get("skill", skill)
                        self.hook = d.get("hook", "unknown")
                        self.status = d.get("status", "UNKNOWN")
                        self.duration_ms = d.get("duration_ms", 0)
                        self.exit_code = d.get("exit_code", 0)
                        self.stdout = d.get("stdout", "")
                        self.stderr = d.get("stderr", "")
                        self.findings = d.get("findings", {})
                        self.details = d.get("details", "")
                converted[skill].append(SimpleHookResult(r))
            else:
                converted[skill].append(r)
    return converted


async def generate_report(
    telemetry: TelemetryEmitter,
    hook_results_pre: Dict[str, list],
    hook_results_post: Dict[str, list],
    repo_path: Path,
    push_context: Dict[str, Any],
    push_result: Optional[Dict[str, Any]] = None,
    repo_state: Optional[RepoState] = None,
    config: Optional[Dict[str, Any]] = None
):
    """Generate and emit the markdown report."""
    print(f"[REPORT] generate_report called, run_id={telemetry.get_run_id()}", file=sys.stderr, flush=True)
    
    try:
        run_id = telemetry.get_run_id()
        total_duration_ms = telemetry.get_elapsed_ms()
        total_duration = f"{total_duration_ms / 1000:.2f}"
        
        hook_results_pre = _convert_hook_results(hook_results_pre)
        hook_results_post = _convert_hook_results(hook_results_post)
        
        pre_formatted = format_hook_results(hook_results_pre, "pre") if hook_results_pre else {}
        post_formatted = format_hook_results(hook_results_post, "post") if hook_results_post else {}
        state_formatted = format_repo_state(repo_state) if repo_state else {}
        
        push_exit_code = push_result.get("exit_code", 0) if push_result else 0
        push_duration_ms = push_result.get("duration_ms", 0) if push_result else 0
        push_stdout = truncate(push_result.get("stdout", "")) if push_result else ""
        push_stderr = truncate(push_result.get("stderr", "")) if push_result else ""
        
        push_result_str = "✅ SUCCESS" if push_exit_code == 0 else "❌ FAILED"
        if push_exit_code == -1:
            push_result_str = "💥 ERROR"
        
        pre_duration_s = float(pre_formatted.get("pre_duration", "0"))
        push_duration_s = push_duration_ms / 1000
        post_duration_s = float(post_formatted.get("post_duration", "0"))
        total_duration_s = telemetry.get_elapsed_ms() / 1000
        
        pre_pct = f"{(pre_duration_s / total_duration_s * 100):.1f}" if total_duration_s > 0 else "0"
        push_pct = f"{(push_duration_s / total_duration_s * 100):.1f}" if total_duration_s > 0 else "0"
        post_pct = f"{(post_duration_s / total_duration_s * 100):.1f}" if total_duration_s > 0 else "0"
        
        all_hooks = []
        for results in hook_results_pre.values():
            all_hooks.extend(results)
        for results in hook_results_post.values():
            all_hooks.extend(results)
        
        hooks_executed = len(all_hooks)
        hooks_passed = sum(1 for h in all_hooks if h.status == "PASS")
        hooks_failed = sum(1 for h in all_hooks if h.status == "FAIL")
        hooks_skipped = sum(1 for h in all_hooks if h.status == "SKIP")
        hooks_errors = sum(1 for h in all_hooks if h.status == "ERROR")
        
        if push_exit_code != 0:
            final_verdict = "❌ PUSH FAILED — Git push exited with code " + str(push_exit_code)
        elif hooks_failed > 0 or hooks_errors > 0:
            final_verdict = f"❌ PUSH BLOCKED — {hooks_failed} hook(s) failed, {hooks_errors} error(s)"
        elif hooks_passed > 0:
            final_verdict = "✅ PUSH SUCCESSFUL — All actors healthy, no failures detected"
        else:
            final_verdict = "⏭ PUSH SKIPPED — No hooks executed"
        
        report_data = {
            "run_id": telemetry.get_run_id(),
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "total_duration": f"{telemetry.get_elapsed_ms() / 1000:.2f}",
            
            "repo_path": str(repo_path),
            "branch_local": push_context.get("branch_local", "unknown"),
            "branch_remote": push_context.get("branch_remote", "unknown"),
            "force_push": "✅ Yes" if push_context.get("force", False) else "❌ No",
            "push_tags": "✅ Yes" if push_context.get("push_tags", False) else "❌ No",
            "commit_sha": push_context.get("commit_sha", "unknown"),
            "remote_name": push_context.get("remote_name", "origin"),
            
            **pre_formatted,
            **post_formatted,
            **state_formatted,
            
            "push_command": push_context.get("command", "git push"),
            "push_exit_code": str(push_exit_code),
            "push_duration": f"{push_duration_s:.2f}",
            "push_stdout": push_stdout or "(empty)",
            "push_stderr": push_stderr or "(empty)",
            "push_result": push_result_str,
            
            "pre_pct": pre_pct,
            "push_pct": push_pct,
            "post_pct": post_pct,
            
            "hooks_executed": str(hooks_executed),
            "hooks_passed": str(hooks_passed),
            "hooks_failed": str(hooks_failed),
            "hooks_skipped": str(hooks_skipped),
            "otlp_spans": "—",
            "jsonl_events": "—",
            
            "final_verdict": final_verdict,
            
            "otlp_endpoint": config.get("otlp_endpoint", "http://localhost:4318/v1/traces") if config else "http://localhost:4318/v1/traces",
        }
        
        template_path = Path(__file__).parent.parent / "templates" / "report.md.template"
        if template_path.exists():
            report = render_template(template_path, report_data)
        else:
            report = _fallback_report(report_data)
        
        print(f"[REPORT] Report generated, length={len(report)}", file=sys.stderr, flush=True)
        
        telemetry.event("report.generated", {
            "run_id": telemetry.get_run_id(),
            "report_length": len(report),
            "format": "markdown",
        })
        
        # Print to chat (stdout for Hermes)
        print(report)
        print(f"[REPORT] Report printed to stdout", file=sys.stderr, flush=True)
        
        # Also save to scratch for reference
        scratch_path = Path(os.environ.get("HERMES_SCRATCH", "/home/hermes/.hermes/cache/scratch")) / f"git-push-report-{telemetry.get_run_id()}.md"
        print(f"[REPORT] Writing to {scratch_path}", file=sys.stderr, flush=True)
        scratch_path.write_text(report)
        print(f"[REPORT] Report written to {scratch_path}", file=sys.stderr, flush=True)
        
    except Exception as e:
        print(f"[REPORT] ERROR: {e}", file=sys.stderr, flush=True)
        traceback.print_exc(file=sys.stderr)
    
    return None


def _fallback_report(data: Dict[str, Any]) -> str:
    lines = []
    lines.append(f"## 📋 Git Push Telemetry Report")
    lines.append(f"**Run ID:** {data['run_id']} | **Timestamp:** {data['timestamp']} | **Duration:** {data['total_duration']}s")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("### 🎯 Push Context")
    lines.append(f"| Field | Value |")
    lines.append(f"|-------|-------|")
    lines.append(f"| Repository | {data['repo_path']} |")
    lines.append(f"| Local Branch | {data['branch_local']} |")
    lines.append(f"| Remote Branch | {data['branch_remote']} |")
    lines.append(f"| Force Push | {data['force_push']} |")
    lines.append(f"| Push Tags | {data['push_tags']} |")
    lines.append(f"| Commit SHA | {data['commit_sha']} |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("### 🔍 Pre-Push Hook Evaluation")
    lines.append(f"| Skill | Hook | Status | Duration | Exit Code | Findings | Details |")
    lines.append(f"|-------|------|--------|----------|-----------|----------|---------|")
    
    for hook in data.get("pre_hooks", []):
        lines.append(f"| {hook['skill']} | {hook['hook']} | {hook['status_icon']} {hook['status']} | {hook['duration']}s | {hook['exit_code']} | {hook['findings']} | {hook['details']} |")
    
    lines.append(f"| **SUMMARY** | **{data.get('pre_total', '0')} hooks** | **{data.get('pre_verdict', 'UNKNOWN')}** | **{data.get('pre_duration', '0')}s** | **{data.get('pre_exit_codes', '-')}** | **{data.get('pre_findings', '-')}** | **{data.get('pre_summary', '-')}** |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("### 🚀 Push Execution")
    lines.append(f"| Field | Value |")
    lines.append(f"|-------|-------|")
    lines.append(f"| Command | {data['push_command']} |")
    lines.append(f"| Exit Code | {data['push_exit_code']} |")
    lines.append(f"| Duration | {data['push_duration']}s |")
    lines.append(f"| Stdout | {data['push_stdout']} |")
    lines.append(f"| Stderr | {data['push_stderr']} |")
    lines.append(f"| Result | {data['push_result']} |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("### 📦 Post-Push Hook Evaluation")
    lines.append(f"| Skill | Hook | Status | Duration | Exit Code | Details |")
    lines.append(f"|-------|------|--------|----------|-----------|---------|")
    
    for hook in data.get("post_hooks", []):
        lines.append(f"| {hook['skill']} | {hook['hook']} | {hook['status_icon']} {hook['status']} | {hook['duration']}s | {hook['exit_code']} | {hook['details']} |")
    
    lines.append(f"| **SUMMARY** | **{data.get('post_total', '0')} hooks** | **{data.get('post_verdict', 'UNKNOWN')}** | **{data.get('post_duration', '0')}s** | **{data.get('post_exit_codes', '-')}** | **{data.get('post_summary', '-')}** |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("### 🌳 Repository State Snapshot (Post-Push)")
    lines.append(f"| Field | Value |")
    lines.append(f"|-------|-------|")
    lines.append(f"| Current Branch | {data.get('state_current_branch', 'unknown')} |")
    lines.append(f"| Branches (local) | {data.get('state_branches_local', '(none)')} |")
    lines.append(f"| Branches (remote) | {data.get('state_branches_remote', '(none)')} |")
    lines.append(f"| Last Commit | {data.get('state_last_commit', 'unknown')} |")
    lines.append(f"| Tags (local) | {data.get('state_tags_local', '(none)')} |")
    lines.append(f"| Tags (remote) | {data.get('state_tags_remote', '(none)')} |")
    lines.append(f"| Remote Status | {data.get('state_remote_status', 'UNKNOWN')} |")
    lines.append(f"| Unpushed Commits | {data.get('state_unpushed_commits', '0')} |")
    lines.append(f"| Untracked Files | {data.get('state_untracked_files', '0')} |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("### 📊 Telemetry Summary")
    lines.append(f"| Metric | Value |")
    lines.append(f"|-------|-------|")
    lines.append(f"| Total Duration | {data['total_duration']}s |")
    lines.append(f"| Pre-Hooks Duration | {data.get('pre_duration', '0')}s ({data.get('pre_pct', '0')}%) |")
    lines.append(f"| Push Duration | {data['push_duration']}s ({data.get('push_pct', '0')}%) |")
    lines.append(f"| Post-Hooks Duration | {data.get('post_duration', '0')}s ({data.get('post_pct', '0')}%) |")
    lines.append(f"| Hooks Executed | {data['hooks_executed']} |")
    lines.append(f"| Hooks Passed | {data['hooks_passed']} |")
    lines.append(f"| Hooks Failed | {data['hooks_failed']} |")
    lines.append(f"| Hooks Skipped | {data['hooks_skipped']} |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"### 🏁 Final Verdict")
    lines.append(f"**{data['final_verdict']}**")
    lines.append("")
    lines.append("---")
    lines.append(f"*Report generated by git-push-telemetry v1.0.0 | OTLP endpoint: {data['otlp_endpoint']}*")
    
    return "\n".join(lines)
