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

### Current Implementation: Hermes Plugin with Hooks (FIXED ✅)
The plugin in `~/.hermes/plugins/git_push_telemetry/` **loads correctly** and registers `pre_tool_call` / `post_tool_call` hooks that intercept `git push` commands **when executed through the Hermes `terminal` tool** (i.e., from within a Hermes session/chat/TUI).

**How it works:**
1. Plugin loads at Hermes startup (enabled in `config.yaml` under `plugins.enabled`)
2. Plugin's `register(ctx)` registers `git_push_pre_tool_call` for `pre_tool_call` and `git_push_post_tool_call` for `post_tool_call`
3. When Hermes terminal tool invokes a command containing `git push`, `pre_tool_call` hook intercepts
4. Runs pre-push hooks via `eval_hooks.py` (subprocess calls to skill commands), stores state in `_pending_pushes`
5. If hooks fail and `fail_on_hook_failure: true`, returns block directive (fail-closed)
6. Hermes executes the actual `git push` via terminal tool
7. `post_tool_call` hook runs: retrieves pending state, runs post-push hooks, captures repo state, generates markdown report
8. Emits JSONL telemetry to `~/.hermes/logs/git-push-telemetry.jsonl`

**It does NOT work as a standalone `.git/hooks/pre-push`** because:
- Git hooks receive refspecs via stdin and `remote url` as argv — hooks expect Hermes tool context
- No `next_call` function exists in raw git hook execution
- Hooks use `threading` + `asyncio` which assumes Hermes runtime environment

### Fixed: Architecture — Middleware → Hooks
**Previous:** `tool_execution` middleware. **Problem:** Only intercepts agent-loop tool calls; TUI, CLI `hermes chat -q`, and `execute_code(terminal=...)` bypass middleware.

**Fixed:** Migrated to `pre_tool_call` / `post_tool_call` hooks. These fire on **every** tool execution regardless of entry point (TUI, CLI, API, cron, agent loop).

```python
# In git_push_hooks.py
def pre_tool_call(**ctx):
    if ctx.get("tool_name") != "terminal":
        return
    cmd = ctx.get("args", {}).get("command", "")
    if "git push" not in cmd:
        return
    # run pre-push hooks


def post_tool_call(**ctx):
    if ctx.get("tool_name") != "terminal":
        return
    cmd = ctx.get("args", {}).get("command", "")
    if "git push" not in cmd:
        return
    # run post-push hooks, generate report
```

## Installation

### As Independent Repo (Recommended — Portable, Complete)
The skill + plugin is published as a standalone repo that can be cloned directly:
```bash
# Clone to Hermes plugins directory (includes skill docs + plugin implementation)
git clone https://github.com/VectorSigma-Ops/git-push-telemetry.git ~/.hermes/plugins/git_push_telemetry

# Enable in config.yaml:
plugins:
  enabled:
    - git_push_telemetry

# Restart Hermes gateway:
systemctl --user restart hermes-gateway
```

**This repo contains BOTH the skill documentation (for `hermes skill install`) AND the complete plugin implementation (scripts/, templates/, references/).** It works independently of the Hermes repo.

### As Hermes Plugin (Alternative — Inside Hermes Sessions Only)
If you only need it within Hermes sessions and have the skill in-repo:
```yaml
plugins:
  enabled:
    - git_push_telemetry
```
It activates automatically for any `terminal` tool call containing `git push` within a Hermes session.

## Hook Mapping
| Skill | Phase | Hooks |
|-------|-------|-------|
| sast-quality-gates | pre_push | pre_push_security, pre_push_full_gate |
| sast-quality-gates | post_push | post_gate_fail |
| project-standards-skill-project-standards | pre_push | validate-branch, validate-commit, validate-all-fix-auto |
| project-standards-skill-project-standards | post_push | validate_lockfile |
| requirements-manager-skill | pre_push | ensure_dependencies |
| requirements-manager-skill | post_push | validate_lockfile |
| capability-optimizer | pre_push | daily_analysis, code_review |
| capability-optimizer | post_push | daily_improvement |
| rate-limiter-skill-rate-limiter | pre_push | check_limits |
| rate-limiter-skill-rate-limiter | post_push | auto_improve |
| paid-model-guard | pre_push | check_models |
| paid-model-guard | post_push | audit_catalog |
| quota-monitor | pre_push | check_quotas |
| quota-monitor | post_push | alert |
| observability | pre_push | check_health |
| observability | post_push | emit_metrics |

**Total: 8 skills, 18 hooks.** The full `hook_mapping` is in `plugin.yaml` `config_schema.hook_mapping.default` so it works out-of-the-box.

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
1. Fork to your GitHub account (e.g., `VectorSigma-Ops/hermes-agent`) via `gh repo fork`
2. Add fork as remote: `git remote add fork git@github.com:VectorSigma-Ops/hermes-agent.git`
3. Push to fork with explicit refspec: `git push fork HEAD:feature-branch` or `git push fork branch:main`
4. Open PR via GitHub UI or `gh pr create`

**Critical:** `git push fork HEAD` is rejected — use explicit `git push fork <branch>:<target>` refspec.

**The hooks will intercept step 3 ONLY if run via Hermes terminal tool.** Direct shell `git push` bypasses them entirely.

## Known Issues / Pitfalls

### Hooks Are Not Git Hooks
- Copying hook files to `.git/hooks/pre-push` **does not work**
- Git hooks have a different interface (stdin refspecs, argv remote/url)
- Hooks require Hermes tool context (`task_id`, `session_id`, `tool_call_id`)
- Telemetry logs only show pushes made through Hermes terminal tool

### Hook Failures
- `sast-quality-gates/pre_push_security`: fails if `audit_gate` module not installed
- `project-standards-skill-project-standards/*`: skip if `hermes standards` command not available
- `requirements-manager-skill/*`: skip if `hermes requirements` command not available

> **Fix**: Ensure skills are installed in the execution environment, or adjust `hook_mapping` to only include available skills.

### Fixed: OTLP Conflict
**OpenTelemetry tracer provider conflict with Langfuse** ("Overriding of current TracerProvider is not allowed"). Fixed by disabling OTLP entirely — telemetry now JSONL-only (deterministic, no external deps).

### Fixed: Internal Import Bug
The plugin originally had incorrect imports (`git_push_telemetry.scripts.*`) assuming a package structure. Fixed in `git_push_report.py` to use relative imports (`from telemetry import ...`, etc.).

### Fixed: Module Shadowing When Running External Skill Hooks
**Problem**: When `eval_hooks.py` runs project-standards hooks from a repo that has its own `scripts/` directory (e.g., the git-push-telemetry repo itself), Python imports the local `scripts/` package instead of the project-standards skill's `scripts/`.

**Fix**: Run the hook from the skill directory with explicit PYTHONPATH:
```python
# In resolve_hook_command for project-standards-skill-project-standards:
skill_path = get_skill_path(
    skill
)  # /home/hermes/.hermes/skills/infrastructure/project-standards-skill-project-standards
cwd = skill_path  # Run from skill dir, not repo dir
cmd = [hermes_python, "-m", "scripts.cli", "branch", "--target-path", str(repo_path)]
```
And in `run_hook`:
```python
if skill == "project-standards-skill-project-standards" and skill_path:
    cwd = skill_path  # Override repo_path for this skill
```

**General Pattern for External Skill Hooks** (applies to ANY skill invoked via git-push-telemetry):
```python
# 1. Find the skill directory
skill_path = get_skill_path(skill)

# 2. Build command using python -m <skill_module>.<entry_point>
#    This avoids 'hermes <command>' which requires skill to be loaded in Hermes

# 3. Set execution context
env = os.environ.copy()
env["PYTHONPATH"] = f"{skill_path}:{env.get('PYTHONPATH', '')}"
cwd = skill_path  # Critical: run FROM skill dir to avoid module shadowing

# 4. Execute
subprocess.run(cmd, cwd=cwd, env=env, ...)
```

**Why this works**: The `python -m scripts.cli` runs the module relative to `cwd`. When `cwd` is the skill directory, `scripts.cli` resolves to the skill's CLI module, not the repo's local `scripts/` package. The `PYTHONPATH` ensures any skill-internal imports also resolve correctly.

### Telemetry
- JSONL-only (deterministic, no external deps)
- OTLP endpoint config retained for compatibility but unused
- Output: `~/.hermes/logs/git-push-telemetry.jsonl`

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
# Test via Hermes terminal tool (hooks activate)
# In a Hermes session:
> terminal(command="cd /path/to/repo && git push origin main")

# Check telemetry (generated only for Hermes-terminal pushes)
cat ~/.hermes/logs/git-push-telemetry.jsonl

# Check report (generated only for Hermes-terminal pushes)
cat ~/.hermes/cache/scratch/git-push-report-<run_id>.md

# Direct shell git push will NOT be intercepted:
# git push origin main  # no telemetry, no hooks, no report
```

## Independent Repo Structure
```
git-push-telemetry/  (VectorSigma-Ops/git-push-telemetry)
├── SKILL.md                    # Skill documentation
├── plugin.yaml                 # Manifest with full hook_mapping defaults
├── README.md                   # Installation instructions
├── .gitignore
├── scripts/                    # All implementation modules
│   ├── __init__.py
│   ├── eval_hooks.py
│   ├── git_push_hooks.py       # pre_tool_call / post_tool_call hooks
│   ├── git_push_middleware.py  # Legacy reference
│   ├── git_push_report.py
│   ├── repo_state.py
│   └── telemetry.py
├── templates/
│   └── report.md.template
├── references/
│   └── hook-evaluation.md
└── test_hooks_direct.py
```

## Migration Checklist (Plugin Working ✅)
- [x] Plugin loads in `hermes plugins list`
- [x] `git push` from Hermes chat intercepted via hooks
- [x] Telemetry and reports generated (JSONL-only)
- [ ] Test with all configured skills (sast-quality-gates, project-standards, requirements-manager, capability-optimizer, rate-limiter, paid-model-guard, debian-server-maintenance, quota-monitor, mem0-router, memory-system-validation, hermes-model-setup, observability, blockchain, security)