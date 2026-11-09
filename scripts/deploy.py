"""
Deployment module for git-push-telemetry.
Supports deploying to multiple HERMES nodes via SSH, Docker, or Kubernetes.
"""

import json
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class DeploymentTargetType(Enum):
    SSH = "ssh"
    DOCKER = "docker"
    KUBERNETES = "kubernetes"
    LOCAL = "local"


@dataclass
class DeploymentTarget:
    """Configuration for a deployment target."""

    name: str
    type: DeploymentTargetType
    host: str = ""
    user: str = "hermes"
    port: int = 22
    key_path: str = ""
    working_dir: str = "/home/hermes/git-push-telemetry"
    docker_image: str = ""
    docker_container: str = ""
    k8s_namespace: str = "default"
    k8s_deployment: str = ""
    health_check_url: str = ""
    health_check_timeout: int = 30
    pre_deploy_cmd: str = ""
    post_deploy_cmd: str = ""
    env_vars: dict[str, str] = field(default_factory=dict)
    timeout: int = 60
    rollback_on_failure: bool = True


@dataclass
class DeploymentConfig:
    """Deployment configuration."""

    targets: list[DeploymentTarget] = field(default_factory=list)
    parallel: bool = True
    rollback_on_failure: bool = True
    timeout: int = 300


DEFAULT_CONFIG_PATH = Path("/home/hermes/git-push-telemetry-repo/deploy-config.json")


def load_deployment_config(config_path: Path | None = None) -> DeploymentConfig:
    """Load deployment configuration from JSON file."""
    path = config_path or DEFAULT_CONFIG_PATH
    if not path.exists():
        return DeploymentConfig()
    with Path(path).open() as f:
        data = json.load(f)
    targets = []
    for t in data.get("targets", []):
        targets.append(
            DeploymentTarget(
                name=t["name"],
                type=DeploymentTargetType(t["type"]),
                host=t.get("host", ""),
                user=t.get("user", "hermes"),
                port=t.get("port", 22),
                key_path=t.get("key_path", ""),
                working_dir=t.get("working_dir", "/home/hermes/git-push-telemetry"),
                docker_image=t.get("docker_image", ""),
                docker_container=t.get("docker_container", ""),
                k8s_namespace=t.get("k8s_namespace", "default"),
                k8s_deployment=t.get("k8s_deployment", ""),
                health_check_url=t.get("health_check_url", ""),
                health_check_timeout=t.get("health_check_timeout", 30),
                pre_deploy_cmd=t.get("pre_deploy_cmd", ""),
                post_deploy_cmd=t.get("post_deploy_cmd", ""),
                env_vars=t.get("env_vars", {}),
                timeout=t.get("timeout", 60),
                rollback_on_failure=t.get("rollback_on_failure", True),
            )
        )
    return DeploymentConfig(
        targets=targets,
        parallel=data.get("parallel", True),
        rollback_on_failure=data.get("rollback_on_failure", True),
        timeout=data.get("timeout", 300),
    )


def save_deployment_config(config: DeploymentConfig, config_path: Path | None = None):
    """Save deployment configuration to JSON file."""
    path = config_path or DEFAULT_CONFIG_PATH
    data = {
        "targets": [],
        "parallel": config.parallel,
        "rollback_on_failure": config.rollback_on_failure,
        "timeout": config.timeout,
    }
    for t in config.targets:
        data["targets"].append(
            {
                "name": t.name,
                "type": t.type.value,
                "host": t.host,
                "user": t.user,
                "port": t.port,
                "key_path": t.key_path,
                "working_dir": t.working_dir,
                "docker_image": t.docker_image,
                "docker_container": t.docker_container,
                "k8s_namespace": t.k8s_namespace,
                "k8s_deployment": t.k8s_deployment,
                "health_check_url": t.health_check_url,
                "health_check_timeout": t.health_check_timeout,
                "pre_deploy_cmd": t.pre_deploy_cmd,
                "post_deploy_cmd": t.post_deploy_cmd,
                "env_vars": t.env_vars,
                "timeout": t.timeout,
                "rollback_on_failure": t.rollback_on_failure,
            }
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    with Path(path, "w").open() as f:
        json.dump(data, f, indent=2)


def create_default_config():
    """Create a default deployment config template."""
    config = DeploymentConfig(
        targets=[
            DeploymentTarget(
                name="hermes-prod-1",
                type=DeploymentTargetType.SSH,
                host="hermes-prod-1.example.com",
                user="hermes",
                working_dir="/home/hermes/git-push-telemetry",
                health_check_url="http://localhost:8080/health",
            ),
            DeploymentTarget(
                name="hermes-staging",
                type=DeploymentTargetType.DOCKER,
                docker_image="ghcr.io/vectorsigma-ops/git-push-telemetry:latest",
                docker_container="hermes-gpt",
                health_check_url="http://localhost:8080/health",
            ),
            DeploymentTarget(
                name="hermes-k8s",
                type=DeploymentTargetType.KUBERNETES,
                k8s_namespace="hermes",
                k8s_deployment="git-push-telemetry",
                health_check_url="http://git-push-telemetry.hermes.svc.cluster.local/health",
            ),
        ],
        parallel=True,
        rollback_on_failure=True,
        timeout=300,
    )
    save_deployment_config(config)
    return config


def run_ssh_command(
    target: DeploymentTarget, command: str, timeout: int = 60
) -> tuple[bool, str, str]:
    """Run command via SSH."""
    ssh_cmd = ["ssh"]
    if target.key_path:
        ssh_cmd.extend(["-i", target.key_path])
    ssh_cmd.extend(
        [
            "-p",
            str(target.port),
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            "-o",
            "ConnectTimeout=10",
        ]
    )
    env = os.environ.copy()
    if target.env_vars:
        env.update(target.env_vars)
    ssh_cmd.append(f"{target.user}@{target.host}")
    ssh_cmd.append(command)
    try:
        result = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=timeout)
        return (result.returncode == 0, result.stdout, result.stderr)
    except subprocess.TimeoutExpired:
        return (False, "", f"SSH timeout after {timeout}s")
    except Exception as e:
        return (False, "", str(e))


def deploy_ssh(target: DeploymentTarget, repo_path: Path, version: str) -> tuple[bool, str]:
    """Deploy to SSH target."""
    _check_1()
    rsync_cmd = [
        "rsync",
        "-avz",
        "--delete",
        "-e",
        f"ssh -p {target.port} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null",
    ]
    if target.key_path:
        rsync_cmd.extend(
            [
                "-e",
                f"ssh -i {target.key_path} -p {target.port} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null",
            ]
        )
    rsync_cmd.extend([f"{repo_path}/", f"{target.user}@{target.host}:{target.working_dir}/"])
    _handle_2()
    post_commands = [
        f"cd {target.working_dir} && git checkout {version}",
        f"cd {target.working_dir} && pip install -e . --quiet",
        f"cd {target.working_dir} && python -m pytest tests/ -q --tb=short || true",
    ]
    if target.post_deploy_cmd:
        post_commands.append(target.post_deploy_cmd)
    for cmd in post_commands:
        success, out, err = run_ssh_command(target, cmd, target.timeout)
        _check_3()
    _check_4()
    return (True, f"Deployed version {version} to {target.name}")


def deploy_docker(target: DeploymentTarget, repo_path: Path, version: str) -> tuple[bool, str]:
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
        return (False, f"Docker deploy error: {e}")


def deploy_kubernetes(target: DeploymentTarget, version: str) -> tuple[bool, str]:
    """Deploy to Kubernetes."""
    try:
        image = (
            f"{target.docker_image}:{version}"
            if target.docker_image
            else f"git-push-telemetry:{version}"
        )
        result = subprocess.run(
            [
                "kubectl",
                "set",
                "image",
                f"deployment/{target.k8s_deployment}",
                f"{target.k8s_deployment}={image}",
                "-n",
                target.k8s_namespace,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            return (False, f"kubectl set image failed: {result.stderr}")
        result = subprocess.run(
            [
                "kubectl",
                "rollout",
                "status",
                f"deployment/{target.k8s_deployment}",
                "-n",
                target.k8s_namespace,
                "--timeout=5m",
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            subprocess.run(
                [
                    "kubectl",
                    "rollout",
                    "undo",
                    f"deployment/{target.k8s_deployment}",
                    "-n",
                    target.k8s_namespace,
                ],
                capture_output=True,
                timeout=60,
            )
            return (False, f"Rollout failed: {result.stderr}")
        if target.health_check_url:
            success, msg = wait_for_health(target)
            if not success:
                return (False, f"Health check failed: {msg}")
        return (True, f"Kubernetes deployment {target.k8s_deployment} updated to {version}")
    except subprocess.TimeoutExpired:
        return (False, "Kubernetes operation timeout")
    except Exception as e:
        return (False, f"Kubernetes deploy error: {e}")


def deploy_local(target: DeploymentTarget, repo_path: Path, version: str) -> tuple[bool, str]:
    """Deploy locally (for single-node setups)."""
    try:
        subprocess.run(["git", "checkout", version], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(
            ["pip", "install", "-e", ".", "--quiet"], cwd=repo_path, check=True, capture_output=True
        )
        subprocess.run(
            ["python", "-m", "pytest", "tests/", "-q", "--tb=short"],
            cwd=repo_path,
            capture_output=True,
        )
        if target.health_check_url:
            success, msg = wait_for_health(target)
            if not success:
                return (False, f"Health check failed: {msg}")
        return (True, f"Local deployment of {version} complete")
    except subprocess.CalledProcessError as e:
        return (False, f"Local deploy failed: {e}")
    except Exception as e:
        return (False, f"Local deploy error: {e}")


def wait_for_health(target: DeploymentTarget, max_retries: int = 10) -> tuple[bool, str]:
    """Wait for health check endpoint to respond."""
    import urllib.error
    import urllib.request

    url = target.health_check_url
    timeout = target.health_check_timeout
    for i in range(max_retries):
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    return (True, "Health check passed")
        except urllib.error.URLError:
            pass
        except Exception:
            pass
        if i < max_retries - 1:
            time.sleep(3)
    return (False, f"Health check failed after {max_retries} retries")


def deploy_target(target: DeploymentTarget, repo_path: Path, version: str) -> tuple[bool, str]:
    """Deploy to a single target based on its type."""
    deployers = {
        DeploymentTargetType.SSH: deploy_ssh,
        DeploymentTargetType.DOCKER: deploy_docker,
        DeploymentTargetType.KUBERNETES: deploy_kubernetes,
        DeploymentTargetType.LOCAL: deploy_local,
    }
    deployer = deployers.get(target.type)
    if not deployer:
        return (False, f"Unknown deployment type: {target.type}")
    return deployer(target, repo_path, version)


def deploy_all(
    config: DeploymentConfig, repo_path: Path, version: str, parallel: bool = None
) -> dict[str, tuple[bool, str]]:
    """Deploy to all configured targets."""
    if parallel is None:
        parallel = config.parallel
    results = {}
    if parallel:
        with ThreadPoolExecutor(max_workers=len(config.targets)) as executor:
            future_to_target = {
                executor.submit(deploy_target, target, repo_path, version): target
                for target in config.targets
            }
            for future in as_completed(future_to_target):
                target = future_to_target[future]
                try:
                    results[target.name] = future.result()
                except Exception as e:
                    results[target.name] = (False, f"Deployment exception: {e}")
    else:
        for target in config.targets:
            results[target.name] = deploy_target(target, repo_path, version)
    return results


def get_current_version(repo_path: Path) -> str:
    """Get current git version/tag."""
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--exact-match"],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=repo_path, capture_output=True, text=True
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Deploy git-push-telemetry to HERMES nodes")
    parser.add_argument(
        "--repo", default="/home/hermes/git-push-telemetry-repo", help="Repository path"
    )
    parser.add_argument("--config", help="Deployment config file")
    parser.add_argument("--target", help="Deploy to specific target only")
    parser.add_argument("--version", help="Version to deploy (default: current git tag/commit)")
    parser.add_argument("--parallel", action="store_true", default=True, help="Parallel deployment")
    parser.add_argument("--serial", action="store_false", dest="parallel", help="Serial deployment")
    parser.add_argument(
        "--create-config", action="store_true", help="Create default config template"
    )
    args = parser.parse_args()
    repo_path = Path(args.repo).resolve()
    if args.create_config:
        create_default_config()
        sys.exit(0)
    config = load_deployment_config(Path(args.config) if args.config else None)
    if not config.targets:
        sys.exit(1)
    if args.target:
        config.targets = [t for t in config.targets if t.name == args.target]
        if not config.targets:
            sys.exit(1)
    version = args.version or get_current_version(repo_path)
    results = deploy_all(config, repo_path, version, parallel=args.parallel)
    all_success = True
    for _target_name, (success, _msg) in results.items():
        icon = "✅" if success else "❌"
        if not success:
            all_success = False
    if not all_success:
        sys.exit(1)


def _check_1(target):
    """Extracted condition helper."""
    if target.pre_deploy_cmd:
        success, out, err = run_ssh_command(target, target.pre_deploy_cmd, target.timeout)
        if not success:
            return (False, f"Pre-deploy failed: {err}")


def _handle_2():
    """Extracted try/except helper."""
    try:
        result = subprocess.run(rsync_cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            return (False, f"Rsync failed: {result.stderr}")
    except subprocess.TimeoutExpired:
        return (False, "Rsync timeout")
    except Exception:
        return (False, f"Rsync error: {e}")


def _check_3(target):
    """Extracted condition helper."""
    if not success:
        if target.rollback_on_failure:
            run_ssh_command(target, f"cd {target.working_dir} && git checkout -", target.timeout)
        return (False, f"Post-deploy failed ({cmd}): {err}")


def _check_4(target):
    """Extracted condition helper."""
    if target.health_check_url:
        success, msg = wait_for_health(target)
        if not success:
            if target.rollback_on_failure:
                run_ssh_command(
                    target, f"cd {target.working_dir} && git checkout -", target.timeout
                )
            return (False, f"Health check failed: {msg}")
