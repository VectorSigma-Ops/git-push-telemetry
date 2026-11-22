"""Repository state snapshot for git-push-telemetry."""

import subprocess
import json
from dataclasses import dataclass
from typing import List, Optional
from pathlib import Path


@dataclass
class RepoState:
    current_branch: str
    branches_local: List[str]
    branches_remote: List[str]
    last_commit_sha: str
    last_commit_message: str
    last_commit_author: str
    tags_local: List[str]
    tags_remote: List[str]
    remote_status: str  # UP_TO_DATE, AHEAD, BEHIND, DIVERGED
    unpushed_commits: int
    untracked_files: int
    staged_files: int
    modified_files: int


def run_git(repo_path: Path, args: List[str]) -> tuple[int, str, str]:
    """Run git command in repo, return (exit_code, stdout, stderr)."""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=30
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except Exception as e:
        return -1, "", str(e)


def get_repo_state(repo_path: Path) -> RepoState:
    """Capture complete repository state snapshot."""
    # Current branch
    code, stdout, _ = run_git(repo_path, ["branch", "--show-current"])
    current_branch = stdout if code == 0 else "unknown"
    
    # Local branches
    code, stdout, _ = run_git(repo_path, ["branch", "--format=%(refname:short)"])
    branches_local = stdout.split("\n") if code == 0 and stdout else []
    
    # Remote branches
    code, stdout, _ = run_git(repo_path, ["branch", "-r", "--format=%(refname:short)"])
    branches_remote = stdout.split("\n") if code == 0 and stdout else []
    
    # Last commit
    code, stdout, _ = run_git(repo_path, ["log", "-1", "--format=%H|%s|%an"])
    if code == 0 and stdout:
        parts = stdout.split("|", 2)
        last_commit_sha = parts[0][:8]
        last_commit_message = parts[1] if len(parts) > 1 else ""
        last_commit_author = parts[2] if len(parts) > 2 else ""
    else:
        last_commit_sha = "unknown"
        last_commit_message = ""
        last_commit_author = ""
    
    # Tags local
    code, stdout, _ = run_git(repo_path, ["tag", "--list"])
    tags_local = stdout.split("\n") if code == 0 and stdout else []
    
    # Tags remote
    code, stdout, _ = run_git(repo_path, ["ls-remote", "--tags", "origin"])
    tags_remote = []
    if code == 0 and stdout:
        for line in stdout.split("\n"):
            if "refs/tags/" in line:
                tag = line.split("refs/tags/")[-1]
                if not tag.endswith("^{}"):
                    tags_remote.append(tag)
    
    # Remote status
    remote_status = "UNKNOWN"
    unpushed_commits = 0
    if current_branch != "unknown":
        # Check upstream
        code, stdout, _ = run_git(repo_path, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"])
        if code == 0 and stdout:
            upstream = stdout.strip()
            # Count commits ahead/behind
            code, stdout, _ = run_git(repo_path, ["rev-list", "--left-right", "--count", f"{upstream}...HEAD"])
            if code == 0 and stdout:
                behind, ahead = map(int, stdout.split())
                if ahead > 0 and behind > 0:
                    remote_status = "DIVERGED"
                elif ahead > 0:
                    remote_status = "AHEAD"
                elif behind > 0:
                    remote_status = "BEHIND"
                else:
                    remote_status = "UP_TO_DATE"
                unpushed_commits = ahead
            else:
                remote_status = "UP_TO_DATE"
        else:
            remote_status = "NO_UPSTREAM"
    
    # Working tree status
    code, stdout, _ = run_git(repo_path, ["status", "--porcelain"])
    untracked = 0
    staged = 0
    modified = 0
    if code == 0 and stdout:
        for line in stdout.split("\n"):
            if line.startswith("??"):
                untracked += 1
            elif line[0] != " ":
                staged += 1
            if line[1:2] == "M" or line[1:2] == "D":
                modified += 1
    
    return RepoState(
        current_branch=current_branch,
        branches_local=branches_local,
        branches_remote=branches_remote,
        last_commit_sha=last_commit_sha,
        last_commit_message=last_commit_message,
        last_commit_author=last_commit_author,
        tags_local=tags_local,
        tags_remote=tags_remote,
        remote_status=remote_status,
        unpushed_commits=unpushed_commits,
        untracked_files=untracked,
        staged_files=staged,
        modified_files=modified,
    )


def format_repo_state(state: RepoState) -> dict:
    """Format RepoState for report template."""
    return {
        "state_current_branch": state.current_branch,
        "state_branches_local": ", ".join(state.branches_local) if state.branches_local else "(none)",
        "state_branches_remote": ", ".join(state.branches_remote) if state.branches_remote else "(none)",
        "state_last_commit": f"{state.last_commit_sha} {state.last_commit_message}",
        "state_tags_local": ", ".join(state.tags_local) if state.tags_local else "(none)",
        "state_tags_remote": ", ".join(state.tags_remote) if state.tags_remote else "(none)",
        "state_remote_status": state.remote_status,
        "state_unpushed_commits": str(state.unpushed_commits),
        "state_untracked_files": str(state.untracked_files),
        "state_staged_files": str(state.staged_files),
        "state_modified_files": str(state.modified_files),
    }
