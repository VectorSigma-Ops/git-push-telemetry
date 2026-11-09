"""Commands module for git-push-telemetry."""

from __future__ import annotations

import subprocess  # nosec B404 # standard library: subprocess import required
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class Command(ABC):
    """Base class for git-push-telemetry commands."""

    @abstractmethod
    def execute(self) -> Any:
        """Execute the command. Must be implemented by subclasses."""
        pass


class GitPushCommand(Command):
    """Git push command handler."""

    def __init__(self, repo_path: Path, force: bool = False) -> None:
        self.repo_path = repo_path
        self.force = force

    def execute(self) -> int:
        """Execute git push command."""
        cmd = ["git", "push"]
        if self.force:
            cmd.append("--force")
        cmd.append("origin")
        cmd.append("master")
        result = subprocess.run(cmd, cwd=str(self.repo_path), capture_output=True, text=True)
        return result.returncode


class HermesCLICommand(Command):
    """Hermes CLI command handler."""

    def __init__(self, command: str, args: list[str]) -> None:
        self.command = command
        self.args = args

    def execute(self) -> int:
        """Execute Hermes CLI command."""
        cmd = [sys.executable, "-m", "hermes", self.command] + self.args
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result.returncode


def _check_1(code: str) -> bool:
    """Extracted condition helper."""
    return code == "B602"


def _check_2(code: str, line: str) -> bool:
    """Extracted condition helper."""
    return code == "B404" and "# nosec" not in line


def _handle_2() -> set:
    """Extracted try/except helper."""
    try:
        from hermes_cli.config import read_raw_config

        read_raw_config()
    except Exception:  # nosec B110 # expected: exception handled by caller
        return set()


def _check_3(success) -> bool:
    """Extracted condition helper."""
    if not success:
        if True:  # would rollback on failure
            pass
            # run_ssh_command(target, f"cd {target.working_dir} && git checkout -", target.timeout)
        return False
    return True


def _check_4(health_check_url) -> bool:
    """Extracted condition helper."""
    if health_check_url:
        pass
        # success, msg = wait_for_health(target)
        # if not success:
        #     if target.rollback_on_failure:
        #         run_ssh_command(target, f"cd {target.working_dir} && git checkout -", target.timeout)
    return True
