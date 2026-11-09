"""Remediation engine - runs fix-verify loop until gate passes."""

import json
import subprocess  # nosec B404 # standard library: subprocess import required
import sys
from dataclasses import dataclass
from pathlib import Path

from .fixers import BaseFixer, get_fixer_for_tool


@dataclass
class FixLoopConfig:
    """Configuration for the remediation loop."""

    max_iterations: int = 256
    max_fixes_per_iteration: int = 10
    confidence_threshold: float = 0.7
    timeout_seconds: int = 600
    tools_with_fixers: tuple = ("ruff", "bandit", "pyright", "vulture", "radon", "pip_audit")


class RemediationEngine:
    """Runs fix-verify loop for SAST gate failures."""

    def __init__(self, config: FixLoopConfig | None = None, gate_config_path: str | None = None):
        self.config = config or FixLoopConfig()
        self.gate_config_path = gate_config_path
        self.fixers: dict[str, BaseFixer] = {}
        self._init_fixers()

    def _init_fixers(self):
        """Initialize fixers for supported tools."""
        for tool in self.config.tools_with_fixers:
            fixer = get_fixer_for_tool(tool, self.config.confidence_threshold)
            if fixer:
                self.fixers[tool] = fixer

    def run_gate(self, repo_path: Path, tools: list[str] | None = None) -> tuple[bool, list[dict]]:
        """Run audit_gate and return (passed, findings)."""
        tool_list = ",".join(tools) if tools else "bandit,pyright,radon,vulture,pip_audit"
        cmd = [
            sys.executable,
            "-m",
            "audit_gate.cli",
            "gate",
            str(repo_path),
            "--format",
            "json",
            "--tools",
            tool_list,
        ]
        if self.gate_config_path:
            cmd.extend(["--config", self.gate_config_path])
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=self.config.timeout_seconds
            )  # nosec B603 # trusted input: internal command execution
            data = json.loads(result.stdout)
            return (data.get("passed", False), self._flatten_findings(data.get("results", [])))
        except Exception:
            return (False, [])

    def apply_fixes(self, findings: list[dict], repo_path: Path) -> int:
        """Apply fixes for findings using registered fixers.

        Returns number of fixes applied.
        """
        repo_path = Path(repo_path)
        fixes_applied = 0
        by_tool: dict[str, list[dict]] = {}
        for f in findings:
            tool = f.get("tool", "").lower()
            if tool in self.fixers:
                by_tool.setdefault(tool, []).append(f)
        for tool, tool_findings in by_tool.items():
            fixer = self.fixers[tool]
            for finding in tool_findings[: self.config.max_fixes_per_iteration]:
                if fixer.can_fix(finding) and fixer.fix(finding, repo_path):
                    fixes_applied += 1
        return fixes_applied

    def _flatten_findings(self, results: list[dict]) -> list[dict]:
        """Flatten tool results into a list of findings with tool info."""
        findings = []
        for r in results:
            tool = r.get("tool", "")
            for f in r.get("findings", []):
                f["tool"] = tool
                findings.append(f)
        return findings

    def run_remediation(self, repo_path: Path | str, tools: list[str] | None = None) -> bool:
        """Run the fix-verify loop until gate passes or max iterations reached.

        Strategy:
        1. Comprehensive fix pass - apply all fixers to all findings
        2. Verify gate
        3. If fails, targeted fix passes for remaining findings
        4. Repeat until gate passes or max iterations

        Returns True if gate passes, False if max iterations reached.
        """
        repo_path = Path(repo_path)
        passed, findings = self.run_gate(repo_path, tools)
        if passed:
            return True
        for _iteration in range(self.config.max_iterations):
            self.apply_fixes(findings, repo_path)
            passed, findings = self.run_gate(repo_path, tools)
            if passed:
                return True
        passed, _ = self.run_gate(repo_path, tools)
        return passed


def run_remediation_cli(
    repo_path: str,
    max_iterations: int = 256,
    confidence: float = 0.7,
    gate_config: str | None = None,
) -> int:
    """CLI entry point for remediation engine."""
    config = FixLoopConfig(max_iterations=max_iterations, confidence_threshold=confidence)
    engine = RemediationEngine(config, gate_config_path=gate_config)
    success = engine.run_remediation(repo_path)
    return 0 if success else 1
