def _run_post_hooks_async(run_id: str, repo_path: Path, push_context: dict[str, Any]) -> dict[str, list]:
    """Run post-push hooks with timeout."""
    config = get_config()
    hook_mapping = config.get("hook_mapping", {})
    # Filter to only post_push hooks
    post_hooks = {skill: {"post_push": hooks.get("post_push", [])} for skill, hooks in hook_mapping.items() if hooks.get("post_push")}
    telemetry = get_or_create_telemetry(run_id)

    async def _async_run():
        with telemetry.span(
            "post_hooks",
            {
                "git.push.post_hooks.planned": sum(len(m.get("post_push", [])) for m in hook_mapping.values()),
            },
        ):
            hook_results = evaluate_hooks(
                post_hooks,
                repo_path,
                is_tag_push=push_context.get("push_tags", False),
                timeout=config.get("hooks_timeout_seconds", 300),
                fail_fast=False
            )
            return hook_results

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        # Add timeout wrapper for the entire post-hooks execution
        timeout_seconds = config.get("hooks_timeout_seconds", 300)
        return loop.run_until_complete(asyncio.wait_for(_async_run(), timeout=timeout_seconds))
    except asyncio.TimeoutError:
        logger.warning(f"Post-hooks timed out after {timeout_seconds}s for run_id={run_id}")
        # Return timeout error for all planned post-hooks
        config = get_config()
        hook_mapping = config.get("hook_mapping", {})
        post_hooks = {skill: {"post_push": hooks.get("post_push", [])} for skill, hooks in hook_mapping.items() if hooks.get("post_push")}
        timeout_results = {}
        for skill, hooks_dict in post_hooks.items():
            for hook in hooks_dict.get("post_push", []):
                timeout_results.setdefault(skill, []).append(
                    HookResult(
                        skill=skill,
                        hook=hook,
                        status="FAIL",
                        duration_ms=0,
                        exit_code=-1,
                        stdout="",
                        stderr=f"Post-hook timed out after {timeout_seconds}s",
                        findings={},
                        details=f"Timeout after {timeout_seconds}s"
                    )
                )
        return timeout_results
    except Exception as e:
        logger.error(f"Post-hooks error for run_id={run_id}: {e}")
        logger.error(traceback.format_exc())
        return {"error": [HookResult("error", "error", "ERROR", 0, -1, "", str(e), {}, "Post-hooks exception")]}
    finally:
        loop.close()