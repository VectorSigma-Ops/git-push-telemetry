import sys
sys.path.insert(0, '/home/hermes/.hermes/plugins/git_push_telemetry')

from git_push_telemetry.eval_hooks import evaluate_hooks
from pathlib import Path

hook_mapping = {
    "sast-quality-gates": {
        "pre_push": ["pre_push_security"],
        "post_push": []
    }
}

repo_path = Path("/home/hermes/.hermes/hermes-agent")

try:
    results = evaluate_hooks(hook_mapping, repo_path, is_tag_push=False, timeout=300, fail_fast=True)
    print(f"Results: {results}")
    for skill, hooks in results.items():
        for h in hooks:
            print(f"  {h.skill}.{h.hook}: {h.status} (exit={h.exit_code}, duration={h.duration_ms}ms)")
            if h.stdout:
                print(f"    stdout: {h.stdout[:200]}")
            if h.stderr:
                print(f"    stderr: {h.stderr[:200]}")
except Exception as e:
    print(f"Exception: {e}")
    import traceback
    traceback.print_exc()