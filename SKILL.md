---
name: git-push-telemetry
category: software-development
version: 1.0.0
author: Hermes Agent
license: MIT
description: Intercepts git push, runs hooks, emits telemetry, reports.
tags:
- git
- hooks
- telemetry
- observability
- pre-push
related_skills:
- sast-quality-gates
- project-standards-skill-project-standards
- requirements-manager-skill
- observability-design
metadata:
  hermes:
    tags:
    - git
    - hooks
    - telemetry
    - observability
    - pre-push
    related_skills:
    - sast-quality-gates
    - project-standards-skill-project-standards
    - requirements-manager-skill
    - observability-design
---

# Git Push Telemetry Skill

Intercepts `git push` commands, executes pre/post hooks from participating skills, emits OTLP + JSONL telemetry, and generates standardized markdown reports.

## When to Use
- Any git repository that needs telemetry on pushes
- When you want to run skill hooks (security, standards, requirements) before push
- When you need OTLP/JSONL telemetry for observability
- When you want standardized markdown reports of push execution

## Architecture

### Current Implementation: Hermes Plugin (FIXED ✅)
The plugin in `~/.hermes/plugins/git_push_telemetry/` **loads correctly** and registers a `tool_execution` middleware that intercepts `git push` commands **when executed through the Hermes `terminal` tool** (i.e., from within a Hermes session/chat/TUI).

**How it works:**
1. Plugin loads at Hermes startup (enabled in `config.yaml` under `plugins.enabled`)
2. Plugin's `register(ctx)` registers `telemetry_middleware` for `tool_execution` events
3. When Hermes terminal tool invokes a command containing `git push`, middleware intercepts
4. Runs pre-push hooks via `eval_hooks.py` (subprocess calls to skill commands)
5. Calls `next_call(args)` to execute the actual `git push` via terminal tool
6. Runs post-push hooks, captures repo state, generates markdown report
7. Emits OTLP/JSONL telemetry to `~/.hermes/logs/git-push-telemetry.jsonl`

**It does NOT work as a standalone `.git/hooks/pre-push`** because:
- Git hooks receive refspecs via stdin and `remote url` as argv — middleware expects Hermes tool context
- No `next_call` function exists in raw git hook execution
- Middleware uses `threading` + `asyncio` which assumes Hermes runtime environment

### Previous Bug (Fixed)
The plugin had incorrect internal imports (`git_push_telemetry.scripts.*`) assuming a package structure that didn't exist. Fixed by changing to relative imports (`from telemetry import ...`, etc.).

## Installation

### As Hermes Plugin (Current — Works Inside Hermes Sessions)
No manual installation needed. The plugin is enabled in `config.yaml`:
```yaml
plugins:
  enabled:
    - git_push_telemetry
```
It activates automatically for any `terminal` tool call containing `git push` within a Hermes session.

## Configuration
Edit `plugin.yaml`:
```yaml
config_schema:
  enabled: true
  otlp_endpoint: "http://localhost:4318/v1/traces"
  jsonl_log_path: "~/.hermes/logs/git-push-telemetry.jsonl"
  hooks_timeout_seconds: 300
  fail_on_hook_failure: true
  hook_mapping:
    sast-quality-gates:
      pre_push: [pre_push_security, pre_push_full_gate]
      post_push: [post_gate_fail]
    project-standards-skill-project-standards:
      pre_push: [validate-branch, validate-commit, validate-all-fix-auto]
      post_push: [validate_lockfile]
    requirements-manager-skill:
      pre_push: [ensure_dependencies]
      post_push: [validate_lockfile]
```

## Hook Mapping
| Skill | Phase | Hooks |
|-------|-------|-------|
| sast-quality-gates | pre_push | pre_push_security, pre_push_full_gate |
| sast-quality-gates | post_push | post_gate_fail |
| project-standards-skill-project-standards | pre_push | validate-branch, validate-commit, validate-all-fix-auto |
| project-standards-skill-project-standards | post_push | validate_lockfile |
| requirements-manager-skill | pre_push | ensure_dependencies |
| requirements-manager-skill | post_push | validate_lockfile |

## Telemetry Output

### JSONL Log (`~/.hermes/logs/git-push-telemetry.jsonl`)
```json
{"event": "git_push_telemetry.intercept.start", "data": {"repo_path": "/path", "run_id": "abc123"}, "timestamp": 1792703408.86}
{"event": "git_push_telemetry.pre_hooks.start", "data": {"hooks_planned": 6, "run_id": "abc123"}, "timestamp": 1792703408.86}
{"event": "git_push_telemetry.pre_hooks.end", "data": {"duration_ms": 19273, "status": "OK"}, "timestamp": 1792703428.13}
{"event": "git_push_telemetry.report.generated", "data": {"report_length": 3485, "run_id": "..."}, "timestamp": 1792703428.14}
```

### Markdown Report
Sections:
1. **Push Context** - repo, branch, commit, force, tags
2. **Pre-Push Hook Evaluation** - table with skill, hook, status, duration, exit code, findings, details
3. **Push Execution** - exit code, duration, stdout, stderr, result
4. **Post-Push Hook Evaluation** - same table format
5. **Repository State Snapshot** - branches, tags, commits, remote status
6. **Telemetry Summary** - durations, percentages, hook counts
7. **Final Verdict** - PASS/FAIL/BLOCKED/SKIPPED

## Hook Execution Flow
```
# Only when git push runs via Hermes terminal tool:
terminal(command="git push origin main")
  -> telemetry_middleware(**ctx)
    -> intercept.start event
    -> run_pre_hooks()
      -> evaluate_hooks(phase=pre_push)
      -> runs skill hooks via subprocess
    -> next_call(args)  # actual git push via terminal tool
    -> run_post_hooks()
      -> evaluate_hooks(phase=post_push)
    -> state_snapshot()
    -> generate_report()
    -> report.generated event
```

## Upstream Push Workflow (NousResearch/hermes-agent)
The upstream repo requires write access. Standard workflow:
1. Fork to your GitHub account (e.g., `VectorSigma-Ops/hermes-agent`)
2. Add fork as remote: `git remote add fork git@github.com:VectorSigma-Ops/hermes-agent.git`
3. Push to fork: `git push fork HEAD:feature-branch`
4. Open PR via GitHub UI or `gh pr create`

**The middleware will intercept step 3 ONLY if run via Hermes terminal tool.** Direct shell `git push` bypasses it entirely.

## Known Issues / Pitfalls

### Middleware Is Not a Git Hook
- Copying `git_push_middleware.py` to `.git/hooks/pre-push` **does not work**
- Git hooks have a different interface (stdin refspecs, argv remote/url)
- Middleware requires Hermes tool context (`next_call`, `tool_name`, `args`)
- Telemetry logs only show pushes made through Hermes terminal tool

### Hook Failures
- `sast-quality-gates/pre_push_security`: fails if `audit_gate` module not installed
- `project-standards-skill-project-standards/*`: skip if `hermes standards` command not available
- `requirements-manager-skill/*`: skip if `hermes requirements` command not available

> **Fix**: Ensure skills are installed in the execution environment, or adjust `hook_mapping` to only include available skills.

### Fixed: Internal Import Bug
The plugin originally had incorrect imports (`git_push_telemetry.scripts.*`) assuming a package structure. Fixed in `git_push_report.py` to use relative imports (`from telemetry import ...`, etc.).

### Telemetry Dependencies
- Requires `opentelemetry` Python packages for OTLP export
- Falls back gracefully if not installed (JSONL still works)
- OTLP endpoint default: `http://localhost:4318/v1/traces`

## File Structure
```
~/.hermes/skills/software-development/git-push-telemetry/
├── SKILL.md
├── plugin.yaml
├── templates/
│   └── report.md.template
└── references/
    └── hook-evaluation.md

~/.hermes/.local/git-push-telemetry/  # Runtime copy for middleware
├── git_push_middleware.py
├── git_push_report.py
├── eval_hooks.py
├── repo_state.py
├── telemetry.py
├── plugin.yaml
└── templates/report.md.template
```

## Testing
```bash
# Test via Hermes terminal tool (only way middleware activates)
# In a Hermes session:
> terminal(command="cd /path/to/repo && git push origin main")

# Check telemetry (generated only for Hermes-terminal pushes)
cat ~/.hermes/logs/git-push-telemetry.jsonl

# Check report (generated only for Hermes-terminal pushes)
cat ~/.hermes/cache/scratch/git-push-report-<run_id>.md

# Direct shell git push will NOT be intercepted:
# git push origin main  # no telemetry, no hooks, no report
```

## Migration Checklist (Plugin Working ✅)
- [x] Plugin loads in `hermes plugins list`
- [x] `git push` from Hermes chat intercepted via middleware
- [x] Telemetry and reports generated
- [ ] Test with all configured skills (sast-quality-gates, project-standards, requirements-manager)