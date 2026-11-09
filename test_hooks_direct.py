import sys

sys.path.insert(0, "/home/hermes/.hermes/plugins/git_push_telemetry")

from pathlib import Path

from git_push_telemetry.eval_hooks import evaluate_hooks  # type: ignore

hook_mapping = {"sast-quality-gates": {"pre_push": ["pre_push_security"], "post_push": []}}

repo_path = Path("/home/hermes/.hermes/hermes-agent")

try:
    results = evaluate_hooks(
        hook_mapping, repo_path, is_tag_push=False, timeout=300, fail_fast=True
    )
    for hooks in results.values():
        for h in hooks:
            if h.stdout:
                pass
            if h.stderr:
                pass
except Exception:
    import traceback

    traceback.print_exc()
