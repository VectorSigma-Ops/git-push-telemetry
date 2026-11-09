"""Report generator for git-push-telemetry: produces standardized markdown report."""

from pathlib import Path
from typing import Any

from repo_state import RepoState
from telemetry import TelemetryEmitter


def render_template(template_path: Path, data: dict[str, Any]) -> str:
    """Simple template rendering with {{key}} substitution."""
    template = template_path.read_text()
    for key, value in data.items():
        template = template.replace(f"{{{{{key}}}}}", str(value))
    return template


def get_status_icon(status: str) -> str:
    return {"PASS": "✅", "FAIL": "❌", "SKIP": "⏭", "ERROR": "💥"}.get(status, "?")


def format_duration(ms: float) -> str:
    return f"{ms / 1000:.2f}"


def truncate(text: str, max_len: int = 500) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "... [truncated]"


def _convert_hook_results(hook_results: dict[str, list]) -> dict[str, list]:
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


def generate_report(
    telemetry: TelemetryEmitter,
    hook_results_pre: dict[str, list],
    hook_results_post: dict[str, list],
    repo_path: Path,
    push_context: dict[str, Any],
    push_result: dict[str, Any] | None = None,
    repo_state: RepoState | None = None,
    config: dict[str, Any] | None = None,
):
    """Generate and emit the markdown report (synchronous)."""
    import time
    from pathlib import Path

    run_id = telemetry.get_run_id()
    elapsed_ms = telemetry.get_elapsed_ms()
    pre_converted = _convert_hook_results(hook_results_pre)
    post_converted = _convert_hook_results(hook_results_post)

    pre_hooks = []
    pre_passed = 0
    pre_failed = 0
    pre_skipped = 0
    pre_errors = 0
    for _skill, results in pre_converted.items():
        for r in results:
            status_icon = get_status_icon(r.status)
            if r.status == "PASS":
                pre_passed += 1
            elif r.status == "FAIL":
                pre_failed += 1
            elif r.status == "SKIP":
                pre_skipped += 1
            elif r.status == "ERROR":
                pre_errors += 1
            findings_str = (
                ", ".join((f"{k}: {v}" for k, v in r.findings.items())) if r.findings else "-"
            )
            pre_hooks.append(
                {
                    "skill": r.skill,
                    "hook": r.hook,
                    "status_icon": status_icon,
                    "status": r.status,
                    "duration": format_duration(r.duration_ms),
                    "exit_code": str(r.exit_code),
                    "findings": findings_str,
                    "details": truncate(r.details or r.stdout or r.stderr),
                }
            )
    pre_total = len(pre_hooks)
    pre_verdict = (
        "❌ FAIL ({pre_failed} failed, {pre_errors} errors)"
        if pre_failed > 0 or pre_errors > 0
        else "✅ PASS ({pre_passed} passed, {pre_skipped} skipped)"
    )
    post_hooks = []
    post_passed = 0
    post_failed = 0
    post_skipped = 0
    post_errors = 0
    for _skill, results in post_converted.items():
        for r in results:
            status_icon = get_status_icon(r.status)
            if r.status == "PASS":
                post_passed += 1
            elif r.status == "FAIL":
                post_failed += 1
            elif r.status == "SKIP":
                post_skipped += 1
            elif r.status == "ERROR":
                post_errors += 1
            post_hooks.append(
                {
                    "skill": r.skill,
                    "hook": r.hook,
                    "status_icon": get_status_icon(r.status),
                    "status": r.status,
                    "duration": format_duration(r.duration_ms),
                    "exit_code": str(r.exit_code),
                    "details": truncate(r.details or r.stdout or r.stderr),
                }
            )
    post_total = len(post_hooks)
    post_verdict = (
        "❌ FAIL ({post_failed} failed, {post_errors} errors)"
        if post_failed > 0 or post_errors > 0
        else "✅ PASS ({post_passed} passed, {post_skipped} skipped)"
    )

    push_result_data = push_result or {}
    push_duration = push_result_data.get("duration_ms", 0) / 1000
    push_exit_code = push_result_data.get("exit_code", 0)
    push_stdout = push_result_data.get("stdout", "")
    push_stderr = push_result_data.get("stderr", "")
    push_result_str = "SUCCESS" if push_exit_code == 0 else "FAILED"

    if repo_state:
        {
            "state_current_branch": repo_state.current_branch,
            "state_branches_local": ", ".join(repo_state.branches_local)
            if repo_state.branches_local
            else "(none)",
            "state_branches_remote": ", ".join(repo_state.branches_remote)
            if repo_state.branches_remote
            else "(none)",
            "state_last_commit": "{repo_state.last_commit_sha} {repo_state.last_commit_message}",
            "state_tags_local": ", ".join(repo_state.tags_local)
            if repo_state.tags_local
            else "(none)",
            "state_tags_remote": ", ".join(repo_state.tags_remote)
            if repo_state.tags_remote
            else "(none)",
            "state_remote_status": repo_state.remote_status,
            "state_unpushed_commits": str(repo_state.unpushed_commits),
            "state_untracked_files": str(repo_state.untracked_files),
            "state_staged_files": str(repo_state.staged_files),
            "state_modified_files": str(repo_state.modified_files),
        }
    else:
        dict.fromkeys(
            [
                "state_current_branch",
                "state_branches_local",
                "state_branches_remote",
                "state_last_commit",
                "state_tags_local",
                "state_tags_remote",
                "state_remote_status",
                "state_unpushed_commits",
                "state_untracked_files",
                "state_staged_files",
                "state_modified_files",
            ],
            "(unavailable)",
        )

    total_duration = elapsed_ms / 1000
    pre_duration = sum(r.duration_ms for results in pre_converted.values() for r in results) / 1000
    post_duration = (
        sum(r.duration_ms for results in post_converted.values() for r in results) / 1000
    )
    push_duration_s = push_duration

    # Generate markdown report
    report_data = {
        "run_id": run_id,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        "total_duration": f"{total_duration:.2f}",
        "repo_path": str(repo_path),
        "branch_local": push_context.get("branch_local", "unknown"),
        "branch_remote": push_context.get("branch_remote", "unknown"),
        "force_push": push_context.get("force", False),
        "push_tags": push_context.get("push_tags", False),
        "commit_sha": push_context.get("commit_sha", "unknown"),
        "push_command": push_context.get("command", ""),
        "push_exit_code": push_exit_code,
        "push_duration": f"{push_duration_s:.2f}",
        "push_stdout": push_stdout[:200] if push_stdout else "",
        "push_stderr": push_stderr[:200] if push_stderr else "",
        "push_result": push_result_str,
        "pre_hooks": pre_hooks,
        "pre_total": pre_total,
        "pre_verdict": pre_verdict,
        "pre_duration": f"{pre_duration:.2f}",
        "pre_exit_codes": ", ".join(str(r.exit_code) for r in sum(pre_converted.values(), [])),
        "pre_findings": str(sum(sum(r.findings.values()) for r in sum(pre_converted.values(), [])))
        if pre_converted
        else "0",
        "pre_summary": f"{pre_passed} passed, {pre_failed} failed, {pre_skipped} skipped, {pre_errors} errors",
        "pre_pct": f"{pre_passed / pre_total * 100:.1f}" if pre_total > 0 else "0.0",
        "post_hooks": post_hooks,
        "post_total": post_total,
        "post_verdict": post_verdict,
        "post_duration": f"{post_duration:.2f}",
        "push_pct": f"{push_duration_s / total_duration * 100:.1f}"
        if total_duration > 0
        else "0.0",
        "post_pct": f"{post_passed / post_total * 100:.1f}" if post_total > 0 else "0.0",
        "hooks_executed": pre_total + post_total,
        "hooks_passed": pre_passed + post_passed,
        "hooks_failed": pre_failed + post_failed,
        "hooks_skipped": pre_skipped + post_skipped,
        "final_verdict": "✅ PUSH ALLOWED"
        if push_exit_code == 0 and (pre_failed + post_failed + pre_errors + post_errors) == 0
        else "❌ PUSH BLOCKED",
    }
    report_md = _fallback_report(report_data)
    report_path = Path(f"~/.hermes/cache/scratch/git-push-report-{run_id}.md").expanduser()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report_md)
    telemetry.event(
        "report.generated",
        {"format": "markdown", "report_length": len(report_md), "run_id": run_id},
    )


def _fallback_report(data: dict[str, Any]) -> str:
    lines = []
    lines.append("## 📋 Git Push Telemetry Report")
    lines.append(
        f"**Run ID:** {data['run_id']} | **Timestamp:** {data['timestamp']} | **Duration:** {data['total_duration']}s"
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("### 🎯 Push Context")
    lines.append("| Field | Value |")
    lines.append("|-------|-------|")
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
    lines.append("| Skill | Hook | Status | Duration | Exit Code | Findings | Details |")
    lines.append("|-------|------|--------|----------|-----------|----------|---------|")
    for hook in data.get("pre_hooks", []):
        lines.append(
            f"| {hook['skill']} | {hook['hook']} | {hook['status_icon']} {hook['status']} | {hook['duration']}s | {hook['exit_code']} | {hook['findings']} | {hook['details']} |"
        )
    lines.append(
        f"| **SUMMARY** | **{data.get('pre_total', '0')} hooks** | **{data.get('pre_verdict', 'UNKNOWN')}** | **{data.get('pre_duration', '0')}s** | **{data.get('pre_exit_codes', '-')}** | **{data.get('pre_findings', '-')}** | **{data.get('pre_summary', '-')}** |"
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("### 🚀 Push Execution")
    lines.append("| Field | Value |")
    lines.append("|-------|-------|")
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
    lines.append("| Skill | Hook | Status | Duration | Exit Code | Details |")
    lines.append("|-------|------|--------|----------|-----------|---------|")
    for hook in data.get("post_hooks", []):
        lines.append(
            f"| {hook['skill']} | {hook['hook']} | {hook['status_icon']} {hook['status']} | {hook['duration']}s | {hook['exit_code']} | {hook['details']} |"
        )
    lines.append(
        f"| **SUMMARY** | **{data.get('post_total', '0')} hooks** | **{data.get('post_verdict', 'UNKNOWN')}** | **{data.get('post_duration', '0')}s** | **{data.get('post_exit_codes', '-')}** | **{data.get('post_summary', '-')}** |"
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("### 🌳 Repository State Snapshot (Post-Push)")
    lines.append("| Field | Value |")
    lines.append("|-------|-------|")
    lines.append(f"| Current Branch | {data.get('state_current_branch', 'unknown')} |")
    lines.append(f"| Branches (local) | {data.get('state_branches_local', '(none)')} |")
    lines.append(f"| Branches (remote) | {data.get('state_branches_remote', '(none)')} |")
    lines.append(f"| Last Commit | {data.get('state_last_commit', 'unknown')} |")
    lines.append(f"| Tags (local) | {data.get('state_tags_local', '(none)')} |")
    lines.append(f"| Tags (remote) | {data.get('state_tags_remote', '(none)')} |")
    lines.append(f"| Remote Status | {data.get('state_remote_status', 'UNKNOWN')} |")
    lines.append(f"| Unpushed Commits | {data.get('state_unpushed_commits', '0')} |")
    lines.append(f"| Untracked Files | {data.get('state_untracked_files', '0')} |")
    lines.append(f"| Staged Files | {data.get('state_staged_files', '0')} |")
    lines.append(f"| Modified Files | {data.get('state_modified_files', '0')} |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("### 📊 Telemetry Summary")
    lines.append("| Metric | Value |")
    lines.append("|-------|-------|")
    lines.append(f"| Total Duration | {data['total_duration']}s |")
    lines.append(
        f"| Pre-Hooks Duration | {data.get('pre_duration', '0')}s ({data.get('pre_pct', '0')}%) |"
    )
    lines.append(f"| Push Duration | {data['push_duration']}s ({data.get('push_pct', '0')}%) |")
    lines.append(
        f"| Post-Hooks Duration | {data.get('post_duration', '0')}s ({data.get('post_pct', '0')}%) |"
    )
    lines.append(f"| Hooks Executed | {data['hooks_executed']} |")
    lines.append(f"| Hooks Passed | {data['hooks_passed']} |")
    lines.append(f"| Hooks Failed | {data['hooks_failed']} |")
    lines.append(f"| Hooks Skipped | {data['hooks_skipped']} |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("### 🏁 Final Verdict")
    lines.append(f"**{data['final_verdict']}**")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(
        f"*Report generated by git-push-telemetry v1.0.0 | OTLP endpoint: {data.get('otlp_endpoint', 'N/A')}*"
    )
    return "\n".join(lines)


def _handle_1(
    telemetry,
    hook_results_pre,
    hook_results_post,
    repo_path,
    push_context,
    push_result,
    repo_state,
    config,
):
    """Extracted try/except helper."""
    try:
        run_id = telemetry.get_run_id()
        elapsed_ms = telemetry.get_elapsed_ms()
        pre_converted = _convert_hook_results(hook_results_pre)
        post_converted = _convert_hook_results(hook_results_post)
        pre_hooks = []
        pre_passed = 0
        pre_failed = 0
        pre_skipped = 0
        pre_errors = 0
        for _skill, results in pre_converted.items():
            for r in results:
                status_icon = get_status_icon(r.status)
                if r.status == "PASS":
                    pre_passed += 1
                elif r.status == "FAIL":
                    pre_failed += 1
                elif r.status == "SKIP":
                    pre_skipped += 1
                elif r.status == "ERROR":
                    pre_errors += 1
                findings_str = (
                    ", ".join((f"{k}: {v}" for k, v in r.findings.items())) if r.findings else "-"
                )
                pre_hooks.append(
                    {
                        "skill": r.skill,
                        "hook": r.hook,
                        "status_icon": status_icon,
                        "status": r.status,
                        "duration": format_duration(r.duration_ms),
                        "exit_code": str(r.exit_code),
                        "findings": findings_str,
                        "details": truncate(r.details or r.stdout or r.stderr),
                    }
                )
        pre_total = len(pre_hooks)
        pre_verdict = (
            f"❌ FAIL ({pre_failed} failed, {pre_errors} errors)"
            if pre_failed > 0 or pre_errors > 0
            else f"✅ PASS ({pre_passed} passed, {pre_skipped} skipped)"
        )
        post_hooks = []
        post_passed = 0
        post_failed = 0
        post_skipped = 0
        post_errors = 0
        for _skill, results in post_converted.items():
            for r in results:
                status_icon = get_status_icon(r.status)
                if r.status == "PASS":
                    post_passed += 1
                elif r.status == "FAIL":
                    post_failed += 1
                elif r.status == "SKIP":
                    post_skipped += 1
                elif r.status == "ERROR":
                    post_errors += 1
                post_hooks.append(
                    {
                        "skill": r.skill,
                        "hook": r.hook,
                        "status_icon": get_status_icon(r.status),
                        "status": r.status,
                        "duration": format_duration(r.duration_ms),
                        "exit_code": str(r.exit_code),
                        "details": truncate(r.details or r.stdout or r.stderr),
                    }
                )
        post_total = len(post_hooks)
        post_verdict = (
            f"❌ FAIL ({post_failed} failed, {post_errors} errors)"
            if post_failed > 0 or post_errors > 0
            else f"✅ PASS ({post_passed} passed, {post_skipped} skipped)"
        )
        push_result_data = push_result or {}
        push_duration = push_result_data.get("duration_ms", 0) / 1000
        push_exit_code = push_result_data.get("exit_code", 0)
        push_stdout = push_result_data.get("stdout", "")
        push_stderr = push_result_data.get("stderr", "")
        push_result_str = "SUCCESS" if push_exit_code == 0 else "FAILED"
        if repo_state:
            state_data = {
                "state_current_branch": repo_state.current_branch,
                "state_branches_local": ", ".join(repo_state.branches_local)
                if repo_state.branches_local
                else "(none)",
                "state_branches_remote": ", ".join(repo_state.branches_remote)
                if repo_state.branches_remote
                else "(none)",
                "state_last_commit": f"{repo_state.last_commit_sha} {repo_state.last_commit_message}",
                "state_tags_local": ", ".join(repo_state.tags_local)
                if repo_state.tags_local
                else "(none)",
                "state_tags_remote": ", ".join(repo_state.tags_remote)
                if repo_state.tags_remote
                else "(none)",
                "state_remote_status": repo_state.remote_status,
                "state_unpushed_commits": str(repo_state.unpushed_commits),
                "state_untracked_files": str(repo_state.untracked_files),
                "state_staged_files": str(repo_state.staged_files),
                "state_modified_files": str(repo_state.modified_files),
            }
        else:
            state_data = dict.fromkeys(
                [
                    "state_current_branch",
                    "state_branches_local",
                    "state_branches_remote",
                    "state_last_commit",
                    "state_tags_local",
                    "state_tags_remote",
                    "state_remote_status",
                    "state_unpushed_commits",
                    "state_untracked_files",
                    "state_staged_files",
                    "state_modified_files",
                ],
                "(unavailable)",
            )
        total_duration = elapsed_ms / 1000
        pre_duration = (
            sum(r.duration_ms for results in pre_converted.values() for r in results) / 1000
        )
        post_duration = (
            sum(r.duration_ms for results in post_converted.values() for r in results) / 1000
        )
        push_duration_s = push_duration
        pre_pct = round(pre_duration / total_duration * 100, 1) if total_duration > 0 else 0
        push_pct = round(push_duration_s / total_duration * 100, 1) if total_duration > 0 else 0
        post_pct = round(post_duration / total_duration * 100, 1) if total_duration > 0 else 0
        hooks_executed = len(pre_hooks) + len(post_hooks)
        hooks_passed = pre_passed + post_passed
        hooks_failed = pre_failed + post_failed
        hooks_skipped = pre_skipped + post_skipped
        final_verdict = (
            "✅ PUSH ALLOWED" if push_exit_code == 0 and hooks_failed == 0 else "❌ PUSH BLOCKED"
        )
        report_data = {
            "run_id": run_id,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
            "total_duration": f"{total_duration:.2f}",
            "repo_path": str(repo_path),
            "branch_local": push_context.get("branch_local", "unknown"),
            "branch_remote": push_context.get("branch_remote", "unknown"),
            "force_push": push_context.get("force", False),
            "push_tags": push_context.get("push_tags", False),
            "commit_sha": push_context.get("commit_sha", "unknown"),
            "push_command": push_context.get("command", ""),
            "push_exit_code": push_exit_code,
            "push_duration": f"{push_duration_s:.2f}",
            "push_stdout": truncate(push_stdout, 200),
            "push_stderr": truncate(push_stderr, 200),
            "push_result": push_result_str,
            "pre_hooks": pre_hooks,
            "pre_total": pre_total,
            "pre_verdict": pre_verdict,
            "pre_duration": f"{pre_duration:.2f}",
            "pre_exit_codes": ", ".join(str(r.exit_code) for r in sum(pre_converted.values(), [])),
            "pre_findings": str(
                sum(sum(r.findings.values()) for r in sum(pre_converted.values(), []))
            )
            if pre_converted
            else "0",
            "pre_summary": f"{pre_passed} passed, {pre_failed} failed, {pre_skipped} skipped, {pre_errors} errors",
            "pre_pct": f"{pre_pct:.1f}",
            "post_hooks": post_hooks,
            "post_total": post_total,
            "post_verdict": post_verdict,
            "post_duration": f"{post_duration:.2f}",
            "push_pct": f"{push_pct:.1f}",
            "post_pct": f"{post_pct:.1f}",
            **state_data,
            "otlp_endpoint": config.get("otlp_endpoint", "http://localhost:4318/v1/traces")
            if config
            else "N/A",
            "hooks_executed": hooks_executed,
            "hooks_passed": hooks_passed,
            "hooks_failed": hooks_failed,
            "hooks_skipped": hooks_skipped,
            "final_verdict": final_verdict,
        }
        report_md = _fallback_report(report_data)
        report_path = Path(f"~/.hermes/cache/scratch/git-push-report-{run_id}.md").expanduser()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report_md)
        telemetry.event(
            "report.generated",
            {"format": "markdown", "report_length": len(report_md), "run_id": run_id},
        )
    except Exception:
        import logging
        import traceback

        logger = logging.getLogger(__name__)
        logger.debug(f"Report generation error: {e}")
        logger.debug(traceback.format_exc())
