#!/usr/bin/env python3
"""Fix the deploy.py file by restoring the original deploy_docker function."""

import re
from pathlib import Path

file_path = Path("/home/hermes/git-push-telemetry-repo/scripts/deploy.py")
content = file_path.read_text()

# The original deploy_docker function
original_deploy_docker = '''def deploy_docker(target: DeploymentTarget, repo_path: Path, version: str) -> tuple[bool, str]:
    """Deploy via Docker."""
    tag = f"{target.docker_image}:{version}"
    latest_tag = f"{target.docker_image}:latest"
    try:
        result = subprocess.run(
            ["docker", "build", "-t", tag, "-t", latest_tag, str(repo_path)],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            return (False, f"Docker build failed: {result.stderr}")
        if "/" in target.docker_image and (not target.docker_image.startswith("localhost")):
            for t in [tag, latest_tag]:
                result = subprocess.run(
                    ["docker", "push", t], capture_output=True, text=True, timeout=120
                )
                if result.returncode != 0:
                    return (False, f"Docker push failed: {result.stderr}")
        if target.host:
            ssh_cmd = f"docker pull {latest_tag} && docker stop {target.docker_container} || true && docker rm {target.docker_container} || true && docker run -d --name {target.docker_container} --restart unless-stopped -p 8080:8080 {latest_tag}"
            success, out, err = run_ssh_command(target, ssh_cmd, target.timeout)
            if not success:
                return (False, f"Docker deploy failed: {err}")
        else:
            subprocess.run(["docker", "stop", target.docker_container], capture_output=True)
            subprocess.run(["docker", "rm", target.docker_container], capture_output=True)
            subprocess.run(
                [
                    "docker",
                    "run",
                    "-d",
                    "--name",
                    target.docker_container,
                    "--restart",
                    "unless-stopped",
                    "-p",
                    "8080:8080",
                    latest_tag,
                ],
                check=True,
            )
        if target.health_check_url:
            success, msg = wait_for_health(target)
            if not success:
                return (False, f"Health check failed: {msg}")
        return (True, f"Docker image {tag} deployed to {target.name}")
    except subprocess.TimeoutExpired:
        return (False, "Docker operation timeout")
    except Exception as e:
        return (False, f"Docker deploy error: {e}")'''

# Find and replace the broken deploy_docker function
pattern = r"def deploy_docker\(_target: DeploymentTarget, _repo_path: Path, _version: str\) -> tuple\[bool, str\]:.*?(?=\n\ndef deploy_kubernetes)"

new_content = re.sub(pattern, original_deploy_docker, content, flags=re.DOTALL)

if new_content == content:
    # Debug
    match = re.search(r"deploy_docker", content)
    if match:
        pass
else:
    file_path.write_text(new_content)

# Now also remove the _handle_1 function since it's no longer needed
# But keep it for now as other functions might call it
# Actually, let's check if _handle_1 is called elsewhere
