# Hook Evaluation Reference

Details on how hooks are evaluated, their execution order, and common failure modes.

## Hook Execution Model

### Phase-Based Evaluation
Hooks are evaluated in two phases:
- **pre_push**: Before the actual git push executes
- **post_push**: After git push completes successfully

### Evaluation Order
1. All pre_push hooks across all skills execute in parallel
2. If any pre_push hook fails and `fail_on_hook_failure: true`, push is blocked
3. Actual git push executes (via `next_call`)
4. All post_push hooks execute in parallel
5. Repository state snapshot captured
6. Report generated

## Hook Configuration

### Hook Mapping Structure
```yaml
hook_mapping:
  <skill-name>:
    pre_push:
      - hook-name-1
      - hook-name-2
    post_push:
      - hook-name-3
```

### Current Default Mapping
| Skill | Pre-Push Hooks | Post-Push Hooks |
|-------|----------------|-----------------|
| sast-quality-gates | pre_push_security, pre_push_full_gate | post_gate_fail |
| project-standards-skill-project-standards | validate-branch, validate-commit, validate-all-fix-auto | validate_lockfile |
| requirements-manager-skill | ensure_dependencies | validate_lockfile |

## Hook Resolution

Each hook is resolved to an executable command via `resolve_hook_command()` in `eval_hooks.py`:

### sast-quality-gates
| Hook | Command |
|------|---------|
| pre_push_security | `python -m audit_gate.cli gate . --tools bandit,semgrep,pip_audit --format text` |
| pre_push_full_gate | `python -m audit_gate.cli gate . --format text` (tag pushes only) |
| post_gate_fail | `python -m audit_gate.cli gate . --format text` |

### project-standards-skill-project-standards
| Hook | Command |
|------|---------|
| validate-branch | `hermes standards validate-branch` |
| validate-commit | `hermes standards validate-commit` |
| validate-all-fix-auto | `hermes standards validate --fix-auto --format text` |
| validate_lockfile | `hermes standards validate --only observability --format json` |

### requirements-manager-skill
| Hook | Command |
|------|---------|
| ensure_dependencies | `hermes requirements check --target-path .` |
| validate_lockfile | `hermes requirements lock --target-path . --check` |

## Hook Result Status

| Status | Exit Code | Meaning |
|--------|-----------|---------|
| PASS | 0 | Hook succeeded |
| FAIL | 1 | Hook failed (errors found) |
| SKIP | 2 | Conditionally skipped (e.g., tag-only hook on branch push) |
| ERROR | -1 | Execution error (module not found, timeout, etc.) |

## Failure Modes

### Common Failures
| Skill | Hook | Failure | Root Cause |
|-------|------|---------|------------|
| sast-quality-gates | pre_push_security | ModuleNotFoundError: audit_gate | Module not installed in env |
| project-standards | validate-branch | Exit 2 | `hermes standards` command not available |
| project-standards | validate-commit | Exit 2 | `hermes standards` command not available |
| project-standards | validate-all-fix-auto | Exit 2 | `hermes standards` command not available |
| requirements-manager | ensure_dependencies | Exit 2 | `hermes requirements` command not available |

### Conditional Skips
- `pre_push_full_gate`: Only runs on tag pushes (`is_tag_push: true`)
- Other hooks: Run on all pushes

## Timeout Configuration

- Default timeout: 300 seconds (5 minutes) per hook phase
- Configurable via `hooks_timeout_seconds` in plugin.yaml
- Fail-fast behavior: First failure stops further hooks in same phase (if `fail_on_hook_failure: true`)

## Environment Requirements

For hooks to PASS (not SKIP/FAIL):
- `audit_gate` module installed in Python environment
- `hermes` CLI with `standards` and `requirements` subcommands available
- Skills installed in standard locations:
  - `/home/hermes/.hermes/skills/software-development/`
  - `/home/hermes/.hermes/skills/infrastructure/`
  - `/home/hermes/.hermes/skills/autonomous-ai-agents/`

## Testing Hook Resolution
```bash
# Test individual hook resolution
PYTHONPATH=/home/hermes/.local/git-push-telemetry python3 -c "
from eval_hooks import resolve_hook_command
from pathlib import Path
cmd = resolve_hook_command('sast-quality-gates', 'pre_push_security', Path('.'), False)
print(cmd)
"
```
