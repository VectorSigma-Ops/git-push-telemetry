"""Repository state snapshot for git-push-telemetry."""

import subprocess  # nosec B404 # standard library: subprocess import required
from dataclasses import dataclass
from pathlib import Path


@dataclass
class RepoState:
    current_branch: str
    branches_local: list[str]
    branches_remote: list[str]
    last_commit_sha: str
    last_commit_message: str
    last_commit_author: str
    tags_local: list[str]
    tags_remote: list[str]
    remote_status: str
    unpushed_commits: int
    untracked_files: int
    staged_files: int
    modified_files: int


def run_git(repo_path: Path, args: list[str]) -> tuple[int, str, str]:
    """Run git command in repo, return (exit_code, stdout, stderr)."""
    try:
        result = subprocess.run(
            ["git"] + args, cwd=repo_path, capture_output=True, text=True, timeout=30
        )
        return (result.returncode, result.stdout.strip(), result.stderr.strip())
    except subprocess.TimeoutExpired:
        return (-1, "", "timeout")
    except Exception as e:
        return (-1, "", str(e))


def get_repo_state(repo_path: Path) -> RepoState:
    """Capture complete repository state snapshot."""
    code, stdout, _ = run_git(repo_path, ["branch", "--show-current"])
    current_branch = stdout if code == 0 else "unknown"

    code, stdout, _ = run_git(repo_path, ["branch", "--format=%(refname:short)"])
    branches_local = stdout.split("\n") if code == 0 and stdout else []

    code, stdout, _ = run_git(repo_path, ["branch", "-r", "--format=%(refname:short)"])
    branches_remote = stdout.split("\n") if code == 0 and stdout else []

    code, stdout, _ = run_git(repo_path, ["log", "-1", "--format=%H|%s|%an"])
    if code == 0 and stdout:
        parts = stdout.split("|")
        last_commit_sha = parts[0] if len(parts) > 0 else "unknown"
        last_commit_message = parts[1] if len(parts) > 1 else "unknown"
        last_commit_author = parts[2] if len(parts) > 2 else "unknown"
    else:
        last_commit_sha = "unknown"
        last_commit_message = "unknown"
        last_commit_author = "unknown"

    code, stdout, _ = run_git(repo_path, ["tag", "--list"])
    tags_local = stdout.split("\n") if code == 0 and stdout else []

    code, stdout, _ = run_git(repo_path, ["ls-remote", "--tags", "origin"])
    tags_remote = []
    if code == 0 and stdout:
        for line in stdout.split("\n"):
            if line:
                parts = line.split("\t")
                if len(parts) > 1:
                    tags_remote.append(parts[1].replace("refs/tags/", ""))

    code, stdout, _ = run_git(repo_path, ["status", "--porcelain"])
    untracked = 0
    staged = 0
    modified = 0
    if code == 0 and stdout:
        for line in stdout.split("\n"):
            if line:
                if line.startswith("??"):
                    untracked += 1
                elif line[0] in ("M", "A", "D", "R", "C"):
                    staged += 1
                if line[1:2] in ("M", "D"):
                    modified += 1

    # Remote status and unpushed commits
    remote_status = "UNKNOWN"
    unpushed_commits = 0
    try:
        code, stdout, _ = run_git(repo_path, ["rev-list", "--count", "@{u}..HEAD"])
        if code == 0 and stdout:
            unpushed_commits = int(stdout.strip())
            remote_status = "AHEAD" if unpushed_commits > 0 else "UP_TO_DATE"
    except Exception:
        pass

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
        "state_branches_local": ", ".join(state.branches_local)
        if state.branches_local
        else "(none)",
        "state_branches_remote": ", ".join(state.branches_remote)
        if state.branches_remote
        else "(none)",
        "state_last_commit": f"{state.last_commit_sha} {state.last_commit_message}",
        "state_tags_local": ", ".join(state.tags_local) if state.tags_local else "(none)",
        "state_tags_remote": ", ".join(state.tags_remote) if state.tags_remote else "(none)",
        "state_remote_status": state.remote_status,
        "state_unpushed_commits": str(state.unpushed_commits),
        "state_untracked_files": str(state.untracked_files),
        "state_staged_files": str(state.staged_files),
        "state_modified_files": str(state.modified_files),
    }
