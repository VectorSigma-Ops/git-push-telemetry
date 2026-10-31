# Contributing to {project}

## Getting Started
1. Fork the repo
2. Create branch: `git checkout -b {project}/feature/your-feature`
3. Make changes
4. Commit: `git commit -m "feat({project}): your change"`
5. Push: `git push origin {project}/feature/your-feature`
6. Open PR

## Commit Message Format
`<type>({project}): <subject>`

Types: feat, fix, docs, style, refactor, perf, test, build, ci, chore, revert

## Code Standards
- Run `hermes standards validate` before commit
- Run `validate-code.py` before push
- Tests must pass
- Coverage >= threshold

## PR Requirements
- Title: conventional commit format
- Description: what + why
- Tests pass
- CI passes
