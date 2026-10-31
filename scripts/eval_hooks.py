"""Hook evaluator for git-push-telemetry: runs pre/post hooks from participating skills."""

import subprocess
import os
import sys
import time
import json
from dataclasses import dataclass
from typing import Dict, List, Optional, Any
from pathlib import Path


@dataclass
class HookResult:
    skill: str
    hook: str
    status: str  # PASS, FAIL, SKIP, ERROR
    duration_ms: float
    exit_code: int
    stdout: str
    stderr: str
    findings: Dict[str, Any]
    details: str


def get_hermes_python() -> str:
    """Find Hermes Python executable (prefers the venv with all deps)."""
    import glob
    # First try the Hermes install venv
    venv_pythons = glob.glob("/home/hermes/.hermes/installs/*/environments/*/venv/bin/python")
    if venv_pythons:
        return venv_pythons[0]
    # Fallback to the tool Python
    python_paths = glob.glob("/home/hermes/.hermes/tools/python-3.14.7+*/bin/python")
    if python_paths:
        return python_paths[0]
    return "/usr/bin/python3"


def get_skill_path(skill_name: str) -> Optional[Path]:
    """Get skill directory path."""
    # Check standard locations
    base_paths = [
        Path("/home/hermes/.hermes/skills/software-development"),
        Path("/home/hermes/.hermes/skills/infrastructure"),
        Path("/home/hermes/.hermes/skills/autonomous-ai-agents"),
        Path("/home/hermes/.hermes/skills"),
    ]
    for base in base_paths:
        skill_dir = base / skill_name
        if skill_dir.exists():
            return skill_dir
    return None


def resolve_hook_command(skill: str, hook: str, repo_path: Path, is_tag_push: bool = False) -> Optional[List[str]]:
    """Resolve a hook to an executable command."""
    hermes_python = get_hermes_python()
    
    # Skill-specific hook mapping
    if skill == "sast-quality-gates":
        skill_path = get_skill_path(skill)
        if not skill_path:
            return None
        py_path = f"{skill_path}:${{PYTHONPATH}}"
        
        if hook == "pre_push_security":
            return [hermes_python, "-m", "audit_gate.cli", "gate", ".", "--tools", "bandit,semgrep,pip_audit", "--format", "text"]
        elif hook == "pre_push_full_gate":
            if not is_tag_push:
                return None  # Skip for branch pushes
            return [hermes_python, "-m", "audit_gate.cli", "gate", ".", "--format", "text"]
        elif hook == "post_gate_fail":
            return [hermes_python, "-m", "audit_gate.cli", "gate", ".", "--format", "text"]
    
    elif skill == "project-standards-skill-project-standards":
        skill_path = get_skill_path(skill)
        if not skill_path:
            return None
        
        if hook == "validate-branch":
            return ["hermes", "standards", "branch"]
        elif hook == "validate-commit":
            return ["hermes", "standards", "commit"]
        elif hook == "validate-all-fix-auto":
            return ["hermes", "standards", "validate", "--fix-auto", "--format", "text"]
        elif hook == "validate_lockfile":
            return ["hermes", "standards", "validate", "--only", "requirements", "--format", "json"]
    
    elif skill == "requirements-manager-skill":
        skill_path = get_skill_path(skill)
        if not skill_path:
            return None
        
        if hook == "ensure_dependencies":
            return ["hermes", "requirements", "check", "--target-path", "."]
        elif hook == "validate_lockfile":
            return ["hermes", "requirements", "lock", "--target-path", ".", "--check"]
    
    # === USER'S CUSTOM SKILLS ===
    
    elif skill == "capability-optimizer":
        skill_path = get_skill_path(skill)
        if not skill_path:
            return None
        
        if hook == "daily_analysis":
            return [hermes_python, str(skill_path / "daily_analysis.py")]
        elif hook == "daily_improvement":
            return [hermes_python, str(skill_path / "daily_improvement.py")]
        elif hook == "optimizer":
            return [hermes_python, str(skill_path / "optimizer.py")]
        elif hook == "code_review":
            return [hermes_python, str(skill_path / "code_review.py")]
    
    elif skill == "rate-limiter-skill-rate-limiter":
        skill_path = get_skill_path(skill)
        if not skill_path:
            return None
        
        if hook == "check_limits":
            return [hermes_python, str(skill_path / "rate_limiter.py"), "check"]
        elif hook == "auto_improve":
            return [hermes_python, str(skill_path / "auto_improvement.py")]
    
    elif skill == "paid-model-guard":
        skill_path = get_skill_path(skill)
        if not skill_path:
            return None
        
        if hook == "check_models":
            return [hermes_python, str(skill_path / "paid_guard.py"), "check"]
        elif hook == "audit_catalog":
            return [hermes_python, str(skill_path / "pmg_catalog.py"), "audit"]
    
    elif skill == "debian-server-maintenance":
        skill_path = get_skill_path(skill)
        if not skill_path:
            return None
        
        scripts_dir = skill_path / "scripts"
        if hook == "audit":
            return [hermes_python, str(scripts_dir / "audit.py")] if (scripts_dir / "audit.py").exists() else None
        elif hook == "tune":
            return [hermes_python, str(scripts_dir / "tune.py")] if (scripts_dir / "tune.py").exists() else None
        elif hook == "cleanup":
            return [hermes_python, str(scripts_dir / "cleanup.py")] if (scripts_dir / "cleanup.py").exists() else None
    
    elif skill == "quota-monitor":
        skill_path = get_skill_path(skill)
        if not skill_path:
            return None
        
        if hook == "check_quotas":
            return [hermes_python, str(skill_path / "quota_model.py"), "check"]
        elif hook == "alert":
            return [hermes_python, str(skill_path / "middleware.py"), "alert"]
    
    elif skill == "mem0-router":
        skill_path = get_skill_path(skill)
        if not skill_path:
            return None
        
        if hook == "sync_memory":
            return [hermes_python, str(skill_path / "router.py"), "sync"]
        elif hook == "validate_embeddings":
            return [hermes_python, str(skill_path / "siyuan_client.py"), "validate"]
    
    elif skill == "memory-system-validation":
        skill_path = get_skill_path(skill)
        if not skill_path:
            return None
        
        if hook == "validate":
            return [hermes_python, "-m", "pytest", str(skill_path / "tests"), "-v"]
    
    elif skill == "hermes-model-setup":
        skill_path = get_skill_path(skill)
        if not skill_path:
            return None
        
        if hook == "validate_config":
            return ["hermes", "model", "validate"]
        elif hook == "check_providers":
            return ["hermes", "model", "check-providers"]
    
    elif skill == "observability":
        skill_path = get_skill_path(skill)
        if not skill_path:
            return None
        
        if hook == "check_health":
            return [hermes_python, str(skill_path / "observability.py"), "health"]
        elif hook == "emit_metrics":
            return [hermes_python, str(skill_path / "observability.py"), "emit"]
    
    elif skill == "blockchain":
        skill_path = get_skill_path(skill)
        if not skill_path:
            return None
        
        if hook == "check_hyperliquid":
            return [hermes_python, str(skill_path / "hyperliquid" / "cli.py"), "check"] if (skill_path / "hyperliquid" / "cli.py").exists() else None
    
    elif skill == "security":
        skill_path = get_skill_path(skill)
        if not skill_path:
            return None
        
        if hook == "web_pentest":
            return [hermes_python, str(skill_path / "web-pentest" / "cli.py"), "scan"] if (skill_path / "web-pentest" / "cli.py").exists() else None
    
    return None


def run_hook(skill: str, hook: str, repo_path: Path, is_tag_push: bool = False, timeout: int = 300) -> HookResult:
    """Execute a single hook and return result."""
    cmd = resolve_hook_command(skill, hook, repo_path, is_tag_push)
    if cmd is None:
        return HookResult(
            skill=skill,
            hook=hook,
            status="SKIP",
            duration_ms=0,
            exit_code=2,
            stdout="",
            stderr="",
            findings={},
            details="Conditional skip (not tag push / not applicable)"
        )
    
    # Build environment
    env = os.environ.copy()
    skill_path = get_skill_path(skill)
    if skill_path:
        env["PYTHONPATH"] = f"{skill_path}:{env.get('PYTHONPATH', '')}"
    
    start = time.time()
    try:
        result = subprocess.run(
            cmd,
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env
        )
        duration_ms = round((time.time() - start) * 1000, 2)
        
        # Determine status
        if result.returncode == 0:
            status = "PASS"
        elif result.returncode == 2:
            status = "SKIP"
        else:
            status = "FAIL"
        
        # Parse findings from stdout if structured
        findings = {}
        if "audit_gate" in " ".join(cmd):
            # Try to extract findings counts
            pass
        
        details = result.stdout[:200] if result.stdout else result.stderr[:200]
        
        return HookResult(
            skill=skill,
            hook=hook,
            status=status,
            duration_ms=duration_ms,
            exit_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            findings=findings,
            details=details
        )
    
    except subprocess.TimeoutExpired:
        duration_ms = round((time.time() - start) * 1000, 2)
        return HookResult(
            skill=skill,
            hook=hook,
            status="FAIL",
            duration_ms=duration_ms,
            exit_code=-1,
            stdout="",
            stderr=f"Timeout after {timeout}s",
            findings={},
            details=f"Hook timed out after {timeout}s"
        )
    except Exception as e:
        duration_ms = round((time.time() - start) * 1000, 2)
        return HookResult(
            skill=skill,
            hook=hook,
            status="ERROR",
            duration_ms=duration_ms,
            exit_code=-1,
            stdout="",
            stderr=str(e),
            findings={},
            details=f"Hook execution error: {e}"
        )


def evaluate_hooks(skill_hooks: Dict[str, Dict[str, List[str]]], repo_path: Path, is_tag_push: bool = False, timeout: int = 300, fail_fast: bool = True) -> Dict[str, List[HookResult]]:
    """Evaluate all hooks for pre-push or post-push phase."""
    results = {}
    
    for skill, hooks in skill_hooks.items():
        results[skill] = []
        for hook in hooks.get("pre_push", []) + hooks.get("post_push", []):
            # Determine if this is pre or post push hook
            phase = "pre_push" if hook in hooks.get("pre_push", []) else "post_push"
            result = run_hook(skill, hook, repo_path, is_tag_push, timeout)
            results[skill].append(result)
            
            if fail_fast and result.status in ("FAIL", "ERROR"):
                break
    
    return results


def format_hook_results(results: Dict[str, List[HookResult]], phase: str) -> dict:
    """Format hook results for report template."""
    all_results = []
    for skill_results in results.values():
        all_results.extend(skill_results)
    
    passed = sum(1 for r in all_results if r.status == "PASS")
    failed = sum(1 for r in all_results if r.status == "FAIL")
    skipped = sum(1 for r in all_results if r.status == "SKIP")
    errors = sum(1 for r in all_results if r.status == "ERROR")
    total_duration = sum(r.duration_ms for r in all_results) / 1000
    
    if failed > 0 or errors > 0:
        verdict = f"❌ FAIL ({failed} failed, {errors} errors)"
    elif passed > 0:
        verdict = f"✅ PASS ({passed} passed, {skipped} skipped)"
    else:
        verdict = "⏭ SKIPPED"
    
    exit_codes = ", ".join(str(r.exit_code) for r in all_results)
    
    formatted_hooks = []
    for skill_results in results.values():
        for r in skill_results:
            status_icon = {
                "PASS": "✅",
                "FAIL": "❌",
                "SKIP": "⏭",
                "ERROR": "💥"
            }.get(r.status, "?")
            
            findings_str = ""
            if r.findings:
                findings_str = ", ".join(f"{k}: {v}" for k, v in r.findings.items())
            
            formatted_hooks.append({
                "skill": r.skill,
                "hook": r.hook,
                "status_icon": status_icon,
                "status": r.status,
                "duration": f"{r.duration_ms / 1000:.2f}",
                "exit_code": str(r.exit_code),
                "findings": findings_str or "-",
                "details": r.details
            })
    
    return {
        f"{phase}_hooks": formatted_hooks,
        f"{phase}_total": str(len(all_results)),
        f"{phase}_verdict": verdict,
        f"{phase}_duration": f"{total_duration:.2f}",
        f"{phase}_exit_codes": exit_codes,
        f"{phase}_findings": findings_str if 'findings_str' in locals() else "-",
        f"{phase}_summary": f"{passed} passed, {failed} failed, {skipped} skipped, {errors} errors",
    }
