# git-push-telemetry

Skill + plugin for Hermes Agent that intercepts `git push` commands, runs configurable pre/post-push hooks from multiple skills, emits JSONL telemetry, and generates Markdown reports.

## Features

- **Pre-push hooks**: Run security gates, standards validation, dependency checks, capability analysis, rate limiting, model guards, quota monitoring, health checks
- **Post-push hooks**: Failure handling, lockfile validation, improvements, catalog audits, alerts, metrics emission
- **Telemetry**: JSONL logging to `~/.hermes/logs/git-push-telemetry.jsonl` (OTLP disabled by default to avoid TracerProvider conflicts)
- **Reports**: Markdown reports in `~/.hermes/cache/scratch/git-push-report-<run_id>.md`
- **Execution**: Uses Hermes install venv for hook execution (has all dependencies: audit_gate, etc.)

## Installation

### Method 1: Hermes Skill Install (recommended)

```bash
# Install the skill (downloads skill documentation)
hermes skill install git-push-telemetry

# Install the plugin (downloads implementation scripts)
hermes plugin install git_push_telemetry
```

### Method 2: Manual Installation

```bash
# 1. Clone to Hermes plugins directory
git clone https://github.com/VectorSigma-Ops/git-push-telemetry.git ~/.hermes/plugins/git_push_telemetry

# 2. Enable plugin in config.yaml
# Add to ~/.hermes/config.yaml:
plugins:
  enabled: true
  entries:
    git_push_telemetry:
      path: ~/.hermes/plugins/git_push_telemetry
      enabled: true

# 3. Reload plugins
hermes plugins reload
```

## Configuration

The plugin works out-of-the-box with defaults. Override in `~/.hermes/config.yaml`:

```yaml
plugins:
  entries:
    git_push_telemetry:
      config:
        enabled: true
        jsonl_log_path: "~/.hermes/logs/git-push-telemetry.jsonl"
        hooks_timeout_seconds: 300
        fail_on_hook_failure: true
        # Full hook_mapping with 8 skills included by default
```

## Hooks Included (8 skills, 18 hooks)

| Skill | Pre-push | Post-push |
|-------|----------|-----------|
| `sast-quality-gates` | `pre_push_security`, `pre_push_full_gate` | `post_gate_fail` |
| `project-standards-skill-project-standards` | `validate-branch`, `validate-commit`, `validate-all-fix-auto` | `validate_lockfile` |
| `requirements-manager-skill` | `ensure_dependencies` | `validate_lockfile` |
| `capability-optimizer` | `daily_analysis`, `code_review` | `daily_improvement` |
| `rate-limiter-skill-rate-limiter` | `check_limits` | `auto_improve` |
| `paid-model-guard` | `check_models` | `audit_catalog` |
| `quota-monitor` | `check_quotas` | `alert` |
| `observability` | `check_health` | `emit_metrics` |

## Requirements

For all hooks to work, the following must be available in the Hermes execution environment:
- `audit_gate` CLI (for SAST gates)
- `hermes standards` CLI (for project-standards)
- `hermes requirements` CLI (for requirements-manager)
- Other custom skills' CLI commands

## How It Works

1. **Hook registration**: Plugin registers `pre_tool_call` and `post_tool_call` hooks
2. **Interception**: When `terminal` tool executes `git push`, `pre_tool_call` fires
3. **Pre-push hooks**: Runs all configured `pre_push` hooks via `eval_hooks.py`
4. **Execution**: If not blocked, original `git push` executes
5. **Post-push hooks**: `post_tool_call` fires, runs `post_push` hooks
6. **Telemetry**: JSONL emitted throughout, Markdown report generated

## Repository Structure

```
git-push-telemetry/
├── SKILL.md                    # Skill documentation
├── plugin.yaml                 # Plugin manifest with full hook_mapping defaults
├── README.md                   # This file
├── scripts/                    # Implementation scripts
│   ├── __init__.py
│   ├── eval_hooks.py           # Hook command resolution & execution
│   ├── git_push_hooks.py       # pre_tool_call / post_tool_call hooks
│   ├── git_push_middleware.py  # Legacy middleware (reference)
│   ├── git_push_report.py      # Markdown report generation
│   ├── repo_state.py           # Git repo state snapshot
│   └── telemetry.py            # JSONL telemetry (OTLP disabled)
├── templates/
│   └── report.md.template      # Markdown report template
└── references/
    └── hook-evaluation.md      # Hook configuration reference
```

## Development

```bash
# Test hooks directly
cd ~/.hermes/plugins/git_push_telemetry
python scripts/test_hooks_direct.py

# Check telemetry
tail -f ~/.hermes/logs/git-push-telemetry.jsonl

# View latest report
ls -lt ~/.hermes/cache/scratch/git-push-report-*.md | head -1
```

## License

MIT
# Test
# Trigger hooks test
