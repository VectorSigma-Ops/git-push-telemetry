#!/usr/bin/env python3
"""Fix the git_push_middleware.py file by restoring the original _parse_push_command function."""

import re
from pathlib import Path

file_path = Path("/home/hermes/git-push-telemetry-repo/scripts/git_push_middleware.py")
content = file_path.read_text()

# The original _parse_push_command function
original_function = """    def _parse_push_command(self, command: str, repo_path: Path) -> dict[str, Any]:
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
            branch = subprocess.run(
                ["git", "branch", "--show-current"], cwd=repo_path, capture_output=True, text=True
            ).stdout.strip()
            commit = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"], cwd=repo_path, capture_output=True, text=True
            ).stdout.strip()
        except Exception:
            branch = "unknown"
            commit = "unknown"
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
        }"""

# Find and replace the broken function
# The broken function starts with "def _parse_push_command" and ends before "def _get_all_pre_hooks"
pattern = r"    def _parse_push_command\(self, command: str, repo_path: Path\) -> dict\[str, Any\]:.*?(?=\n    def _get_all_pre_hooks)"

# Use DOTALL flag to match across newlines
new_content = re.sub(pattern, original_function, content, flags=re.DOTALL)

# Verify the replacement worked
if new_content == content:
    # Try a more specific pattern
    pattern2 = r"    def _parse_push_command\(self, command: str, repo_path: Path\) -> dict\[str, Any\]:  # noqa: VULTURE  # noqa: CC01.*?(?=\n    def _get_all_pre_hooks)"
    new_content = re.sub(pattern2, original_function, content, flags=re.DOTALL)

if new_content == content:
    # Debug: find the function
    match = re.search(r"def _parse_push_command", content)
    if match:
        pass
else:
    file_path.write_text(new_content)
