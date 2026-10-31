# Hook Evaluation Reference

Details on how hooks are evaluated, their execution order, and common failure modes.

## Hook Execution Model

### Phase-Based Evaluation
Hooks are evaluated in two phases:
- **pre_push**: Before the actual git push executes (via `pre_tool_call` hook)
- **post_push**: After git push completes successfully (via `post_tool_call` hook)

### Evaluation Order
1. All pre_push hooks across all skills execute in parallel
2. If any pre_push hook fails and `fail_on_hook_failure: true`, push is blocked (fail-closed)
3. Actual git push executes (Hermes terminal tool)
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

### Current Default Mapping (14 skills, 29 hooks)
| Skill | Pre-Push Hooks | Post-Push Hooks |
|-------|----------------|-----------------|
| sast-quality-gates | pre_push_security, pre_push_full_gate | post_gate_fail |
| project-standards-skill-project-standards | validate-branch, validate-commit, validate-all-fix-auto | validate_lockfile |
| requirements-manager-skill | ensure_dependencies | validate_lockfile |
| capability-optimizer | daily_analysis, code_review | daily_improvement |
| rate-limiter-skill-rate-limiter | check_limits | auto_improve |
| paid-model-guard | check_models | audit_catalog |
| debian-server-maintenance | audit | cleanup |
| quota-monitor | check_quotas | alert |
| mem0-router | sync_memory | validate_embeddings |
| memory-system-validation | validate | (none) |
| hermes-model-setup | validate_config | check_providers |
| observability | check_health | emit_metrics |
| blockchain | check_hyperliquid | (none) |
| security | web_pentest | (none) |

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
| validate-branch | `python -m scripts.cli branch --target-path <repo>` (run from skill dir) |
| validate-commit | `python -m scripts.cli commit --target-path <repo>` (run from skill dir) |
| validate-all-fix-auto | `python -m scripts.cli validate --fix-auto --format text --target-path <repo>` (run from skill dir) |
| validate_lockfile | `python -m scripts.cli validate-lockfile --format json --target-path <repo>` (run from skill dir) |

### requirements-manager-skill
| Hook | Command |
|------|---------|
| ensure_dependencies | `hermes requirements check --target-path .` |
| validate_lockfile | `hermes requirements lock --target-path . --check` |

### capability-optimizer
| Hook | Command |
|------|---------|
| daily_analysis | `python daily_analysis.py` |
| daily_improvement | `python daily_improvement.py` |
| optimizer | `python optimizer.py` |
| code_review | `python code_review.py` |

### rate-limiter-skill-rate-limiter
| Hook | Command |
|------|---------|
| check_limits | `python rate_limiter.py check` |
| auto_improve | `python auto_improvement.py` |

### paid-model-guard
| Hook | Command |
|------|---------|
| check_models | `python paid_guard.py check` |
| audit_catalog | `python pmg_catalog.py audit` |

### debian-server-maintenance
| Hook | Command |
|------|---------|
| audit | `python scripts/audit.py` (if exists) |
| tune | `python scripts/tune.py` (if exists) |
| cleanup | `python scripts/cleanup.py` (if exists) |

### quota-monitor
| Hook | Command |
|------|---------|
| check_quotas | `python quota_model.py check` |
| alert | `python middleware.py alert` |

### mem0-router
| Hook | Command |
|------|---------|
| sync_memory | `python router.py sync` |
| validate_embeddings | `python siyuan_client.py validate` |

### memory-system-validation
| Hook | Command |
|------|---------|
| validate | `python -m pytest tests/ -v` |

### hermes-model-setup
| Hook | Command |
|------|---------|
| validate_config | `hermes model validate` |
| check_providers | `hermes model check-providers` |

### observability
| Hook | Command |
|------|---------|
| check_health | `python observability.py health` |
| emit_metrics | `python observability.py emit` |

### blockchain
| Hook | Command |
|------|---------|
| check_hyperliquid | `python hyperliquid/cli.py check` (if exists) |

### security
| Hook | Command |
|------|---------|
| web_pentest | `python web-pentest/cli.py scan` (if exists) |

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
| validate-branch | `python -m scripts.cli branch --target-path <repo>` (run from skill dir) |
| validate-commit | `python -m scripts.cli commit --target-path <repo>` (run from skill dir) |
| validate-all-fix-auto | `python -m scripts.cli validate --fix-auto --format text --target-path <repo>` (run from skill dir) |
| validate_lockfile | `python -m scripts.cli validate-lockfile --format json --target-path <repo>` (run from skill dir) |

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
| project-standards | validate-branch | ModuleNotFoundError | PYTHONPATH not set to skill dir |
| project-standards | validate-commit | ModuleNotFoundError | PYTHONPATH not set to skill dir |
| project-standards | validate-all-fix-auto | ModuleNotFoundError | PYTHONPATH not set to skill dir |
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
- `hermes` CLI with `requirements` subcommand available
- Skills installed in standard locations:
  - `/home/hermes/.hermes/skills/software-development/`
  - `/home/hermes/.hermes/skills/infrastructure/`
  - `/home/hermes/.hermes/skills/autonomous-ai-agents/`

**For project-standards-skill-project-standards hooks specifically:**
- Run hook from skill directory (`/home/hermes/.hermes/skills/infrastructure/project-standards-skill-project-standards/`)
- Set `PYTHONPATH` to include skill directory
- Use `python -m scripts.cli <command> --target-path <repo>` pattern

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
