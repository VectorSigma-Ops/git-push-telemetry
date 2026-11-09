"""Registry-owned slash command execution (thin slice).

Invariant: an executor's output depends only on ``ctx.args`` / ``ctx.options`` — never on
``ctx.surface`` — so the core text is identical across surfaces for a fixed context (enforced by
tests/hermes_cli/test_commands_execute.py).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from agent.i18n import t  # type: ignore[reportMissingImports]

__all__ = [
    "EXECUTORS",
    "CommandContext",
    "CommandReply",
    "execute_command",
    "resolve_executor",
    "run_execute",
]


@dataclass(frozen=True)
class CommandContext:
    """Surface-provided inputs for a shared command executor."""

    surface: str = "cli"
    args: str = ""
    options: Mapping[str, Any] = field(default_factory=dict)
    config_get: Callable[[str, Any], Any] | None = None


@dataclass(frozen=True)
class CommandReply:
    """Canonical result of a shared executor: surface-independent ``text`` plus the structured
    ``data`` it derived so a surface can re-render with its own decoration."""

    text: str
    data: Mapping[str, Any] = field(default_factory=dict)
    format: str = "plain"


def _exec_version(ctx: CommandContext) -> CommandReply:
    """Core /version text — the banner version label."""
    from hermes_cli.banner import format_banner_version_label  # type: ignore[reportMissingImports]

    return CommandReply(format_banner_version_label())


def _exec_egress(ctx: CommandContext) -> CommandReply:
    """Core /egress text — Docker egress proxy status."""
    from hermes_cli.proxy_cli import format_status_text  # type: ignore[reportMissingImports]

    return CommandReply(format_status_text())


def _exec_profile(ctx: CommandContext) -> CommandReply:
    """Core /profile data — active profile name + home directory.

    A multiplexed gateway may pre-resolve the per-source profile/home via ``options``
    (``profile_name`` / ``home_display``); otherwise process-level values are used.
    """
    from hermes_cli.profiles import get_active_profile_name  # type: ignore[reportMissingImports]
    from hermes_constants import display_hermes_home  # type: ignore[reportMissingImports]

    profile_name = str(ctx.options.get("profile_name") or "").strip() or get_active_profile_name()
    home_display = str(ctx.options.get("home_display") or "").strip() or display_hermes_home()
    try:
        from hermes_cli.profiles import format_profile_label, get_profile_dir, read_profile_meta  # type: ignore[reportMissingImports]

        display = read_profile_meta(get_profile_dir(profile_name)).get("display_name", "")
        label = format_profile_label(profile_name, display)
    except Exception:
        label = profile_name
    return CommandReply(
        t("gateway.profile.plain", profile=label, home=home_display),
        data={"profile": profile_name, "home": home_display},
    )


def _exec_requirements(ctx: CommandContext) -> CommandReply:
    """Core /requirements - delegate to requirements-manager-skill CLI."""
    return CommandReply("Requirements command not implemented", data={"error": "not implemented"})


def _exec_bundles(ctx: CommandContext) -> CommandReply:
    """Core /bundles data — installed skill bundles listing."""
    try:
        from agent.skill_bundles import _bundles_dir, list_bundles
    except Exception as exc:
        return CommandReply(t("gateway.bundles.unavailable", error=exc), data={"error": str(exc)})
    bundles = list_bundles()
    bundles_dir = str(_bundles_dir())
    if not bundles:
        return CommandReply(
            t("gateway.bundles.none_plain", dir=bundles_dir),
            data={"bundles": [], "dir": bundles_dir},
        )
    lines = [t("gateway.bundles.header_plain", count=len(bundles))]
    for info in bundles:
        skills = info.get("skills", [])
        desc = info.get("description") or t("gateway.bundles.default_desc", count=len(skills))
        lines.append(
            t("gateway.bundles.item_plain", slug=info["slug"], desc=desc, count=len(skills))
        )
        lines.extend(f"    · {s}" for s in skills)
    lines.append(t("gateway.bundles.invoke_hint_plain"))
    return CommandReply("\n".join(lines), data={"bundles": bundles, "dir": bundles_dir})


def _skill_commands() -> dict:
    """Registered skill commands, or ``{}`` when the skill subsystem is unavailable."""
    try:
        from agent.skill_commands import get_skill_commands

        return get_skill_commands() or {}
    except Exception:
        return {}


def _exec_help(ctx: CommandContext) -> CommandReply:
    """Core gateway /help body (pre platform mention decoration)."""
    from hermes_cli.commands import gateway_help_lines

    allowed = ctx.options.get("allowed_commands")
    lines = [t("gateway.help.header"), *gateway_help_lines(allowed)]
    skill_cmds = _skill_commands() if allowed is None else {}
    if skill_cmds:
        lines.append(t("gateway.help.skill_header", count=len(skill_cmds)))
        sorted_cmds = sorted(skill_cmds)
        lines.extend(f"`{cmd}` — {skill_cmds[cmd]['description']}" for cmd in sorted_cmds[:10])
        if len(sorted_cmds) > 10:
            lines.append(t("gateway.help.more_use_commands", count=len(sorted_cmds) - 10))
    return CommandReply("\n".join(lines), format="markdown")


def _exec_commands(ctx: CommandContext) -> CommandReply:
    """Core gateway /commands body — paginated command + skill listing.

    ``ctx.options["page_size"]`` is a surface parameter (Telegram uses 15, everything else 20).
    """
    from hermes_cli.commands import gateway_help_lines

    allowed = ctx.options.get("allowed_commands")
    entries = list(gateway_help_lines(allowed))
    skill_cmds = _skill_commands() if allowed is None else {}
    if skill_cmds:
        lines.append(t("gateway.help.skill_header", count=len(skill_cmds)))
        sorted_cmds = sorted(skill_cmds)
        lines.extend(f"`{cmd}` — {skill_cmds[cmd]['description']}" for cmd in sorted_cmds[:10])
        if len(sorted_cmds) > 10:
            lines.append(t("gateway.help.more_use_commands", count=len(sorted_cmds) - 10))
    page_size = ctx.options.get("page_size", 20)
    requested_page = max(1, int(ctx.options.get("page", 1)))
    total_pages = max(1, (len(entries) + page_size - 1) // page_size)
    page = max(1, min(requested_page, total_pages))
    start = (page - 1) * page_size
    lines = [
        t("gateway.commands.header", total=len(entries), page=page, total_pages=total_pages),
        "",
        *entries[start : start + page_size],
    ]
    if total_pages > 1:
        nav_parts = ([t("gateway.commands.nav_prev", page=page - 1)] if page > 1 else []) + (
            [t("gateway.commands.nav_next", page=page + 1)] if page < total_pages else []
        )
        lines.extend(["", " | ".join(nav_parts)])
    if page != requested_page:
        lines.append(t("gateway.commands.out_of_range", requested=requested_page, page=page))
    return CommandReply("\n".join(lines), format="markdown")


EXECUTORS: dict[str, Callable[[CommandContext], CommandReply]] = {
    "version": _exec_version,
    "egress": _exec_egress,
    "profile": _exec_profile,
    "bundles": _exec_bundles,
    "requirements": _exec_requirements,
    "gateway_help": _exec_help,
    "gateway_commands": _exec_commands,
}


def resolve_executor(cmd_def: Any) -> Callable[[CommandContext], CommandReply] | None:
    """Return the shared executor for ``cmd_def`` (or None when not migrated)."""
    return EXECUTORS.get(getattr(cmd_def, "execute", None) or "")


def run_execute(cmd_def: Any, ctx: CommandContext) -> CommandReply | None:
    """Run ``cmd_def``'s registry-owned executor, if any."""
    fn = resolve_executor(cmd_def)
    return None if fn is None else fn(ctx)


def execute_command(name: str, ctx: CommandContext) -> CommandReply:
    """Run the shared executor for ``name``; ``LookupError`` when unknown or not migrated."""
    from hermes_cli.commands import resolve_command

    cmd_def = resolve_command(name)
    reply = run_execute(cmd_def, ctx) if cmd_def is not None else None
    if reply is None:
        raise LookupError(f"no registry-owned executor for /{name}")
    return reply