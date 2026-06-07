from __future__ import annotations
from pathlib import Path
from typing import Any
import json, shutil, time
from x1_all_tools.registry import ToolSpec, object_schema
from x1_all_tools.security import safe_join, require_program, run_subprocess, shell_command_args, validate_command

def docker_build(context: str = ".", tag: str = "x1-app:latest", dockerfile: str | None = None, runtime=None) -> dict[str, Any]:
    require_program("docker")
    ctx = safe_join(runtime.workspace, context)
    args = ["docker", "build", "-t", tag]
    if dockerfile:
        args += ["-f", str(safe_join(runtime.workspace, dockerfile))]
    args.append(str(ctx))
    return run_subprocess(args, runtime.workspace, runtime.merged_env(), runtime.shell_timeout * 20, runtime.max_output_chars)

def docker_run(image: str, name: str | None = None, ports: list[str] | None = None, env: dict[str, str] | None = None, detach: bool = True, args: list[str] | None = None, runtime=None) -> dict[str, Any]:
    require_program("docker")
    cmd = ["docker", "run"]
    if detach:
        cmd.append("-d")
    if name:
        cmd += ["--name", name]
    for p in ports or []:
        cmd += ["-p", str(p)]
    for k, v in (env or {}).items():
        cmd += ["-e", f"{k}={v}"]
    cmd.append(image)
    cmd.extend([str(a) for a in (args or [])])
    return run_subprocess(cmd, runtime.workspace, runtime.merged_env(), runtime.shell_timeout * 5, runtime.max_output_chars)

def docker_logs(container: str, tail: int = 200, runtime=None) -> dict[str, Any]:
    require_program("docker")
    return run_subprocess(["docker", "logs", "--tail", str(tail), container], runtime.workspace, runtime.merged_env(), runtime.shell_timeout, runtime.max_output_chars)

def docker_stop(container: str, remove: bool = False, runtime=None) -> dict[str, Any]:
    require_program("docker")
    results = [run_subprocess(["docker", "stop", container], runtime.workspace, runtime.merged_env(), runtime.shell_timeout, runtime.max_output_chars)]
    if remove:
        results.append(run_subprocess(["docker", "rm", container], runtime.workspace, runtime.merged_env(), runtime.shell_timeout, runtime.max_output_chars))
    return {"results": results}

def deploy_local(src: str, dst: str, clean: bool = False, runtime=None) -> dict[str, Any]:
    source = safe_join(runtime.workspace, src)
    dest = safe_join(runtime.workspace, dst)
    if clean and dest.exists():
        if dest.is_dir():
            shutil.rmtree(dest)
        else:
            dest.unlink()
    dest.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, dest, dirs_exist_ok=True)
    else:
        shutil.copy2(source, dest)
    return {"src": str(source), "dst": str(dest), "deployed": True}

def deploy_vps(src: str, host: str, remote_path: str, user: str | None = None, key_path: str | None = None, runtime=None) -> dict[str, Any]:
    require_program("scp")
    source = safe_join(runtime.workspace, src)
    dest = (user + "@" if user else "") + host + ":" + remote_path
    cmd = ["scp", "-r"]
    if key_path:
        cmd += ["-i", str(safe_join(runtime.workspace, key_path))]
    cmd += [str(source), dest]
    return run_subprocess(cmd, runtime.workspace, runtime.merged_env(), runtime.shell_timeout * 20, runtime.max_output_chars)

def deploy_github_pages(path: str = ".", branch: str = "gh-pages", message: str = "Deploy GitHub Pages", runtime=None) -> dict[str, Any]:
    require_program("git")
    root = safe_join(runtime.workspace, path)
    # This assumes the repo is already configured with a remote.
    results = []
    results.append(run_subprocess(["git", "checkout", "-B", branch], root, runtime.merged_env(), runtime.shell_timeout, runtime.max_output_chars))
    results.append(run_subprocess(["git", "add", "-A"], root, runtime.merged_env(), runtime.shell_timeout, runtime.max_output_chars))
    results.append(run_subprocess(["git", "commit", "-m", message], root, runtime.merged_env(), runtime.shell_timeout, runtime.max_output_chars))
    results.append(run_subprocess(["git", "push", "origin", branch, "--force"], root, runtime.merged_env(), runtime.shell_timeout * 10, runtime.max_output_chars))
    return {"branch": branch, "results": results}

def cron_create(name: str, command: str, schedule: str, cwd: str = ".", install: bool = False, runtime=None) -> dict[str, Any]:
    validate_command(command, runtime)
    item = {"name": name, "command": command, "schedule": schedule, "cwd": cwd, "created_at": time.time()}
    jobs = runtime.state.setdefault("cron.jobs", [])
    # Replace existing by name.
    jobs[:] = [j for j in jobs if j.get("name") != name]
    jobs.append(item)
    installed = False
    install_result = None
    if install:
        require_program("crontab")
        workdir = safe_join(runtime.workspace, cwd)
        line = f'{schedule} cd "{workdir}" && {command} # x1:{name}'
        current = run_subprocess(["bash", "-lc", "crontab -l 2>/dev/null || true"], runtime.workspace, runtime.merged_env(), runtime.shell_timeout, runtime.max_output_chars)["stdout"]
        new = "\n".join([l for l in current.splitlines() if f"# x1:{name}" not in l] + [line]) + "\n"
        install_result = run_subprocess(["crontab", "-"], runtime.workspace, runtime.merged_env(), runtime.shell_timeout, runtime.max_output_chars, input_text=new)
        installed = install_result.get("returncode") == 0
    return {"job": item, "installed": installed, "install_result": install_result}

def cron_list(runtime=None) -> dict[str, Any]:
    return {"jobs": runtime.state.setdefault("cron.jobs", [])}

TOOLS = [
    ToolSpec("docker.build", "Build a Docker image using Docker CLI.", object_schema({"context": {"type": "string", "default": "."}, "tag": {"type": "string", "default": "x1-app:latest"}, "dockerfile": {"type": ["string", "null"], "default": None}}, []), docker_build),
    ToolSpec("docker.run", "Run a Docker container.", object_schema({"image": {"type": "string"}, "name": {"type": ["string", "null"], "default": None}, "ports": {"type": ["array", "null"], "default": None}, "env": {"type": ["object", "null"], "default": None}, "detach": {"type": "boolean", "default": True}, "args": {"type": ["array", "null"], "default": None}}, ["image"]), docker_run),
    ToolSpec("docker.logs", "Read Docker container logs.", object_schema({"container": {"type": "string"}, "tail": {"type": "integer", "default": 200}}, ["container"]), docker_logs),
    ToolSpec("docker.stop", "Stop a Docker container.", object_schema({"container": {"type": "string"}, "remove": {"type": "boolean", "default": False}}, ["container"]), docker_stop),
    ToolSpec("deploy.local", "Copy files/folders locally within workspace.", object_schema({"src": {"type": "string"}, "dst": {"type": "string"}, "clean": {"type": "boolean", "default": False}}, ["src", "dst"]), deploy_local),
    ToolSpec("deploy.vps", "Deploy to a VPS using scp if available.", object_schema({"src": {"type": "string"}, "host": {"type": "string"}, "remote_path": {"type": "string"}, "user": {"type": ["string", "null"], "default": None}, "key_path": {"type": ["string", "null"], "default": None}}, ["src", "host", "remote_path"]), deploy_vps),
    ToolSpec("deploy.github_pages", "Deploy current git repo to gh-pages branch.", object_schema({"path": {"type": "string", "default": "."}, "branch": {"type": "string", "default": "gh-pages"}, "message": {"type": "string", "default": "Deploy GitHub Pages"}}, []), deploy_github_pages),
    ToolSpec("cron.create", "Create a runtime cron job definition and optionally install via crontab.", object_schema({"name": {"type": "string"}, "command": {"type": "string"}, "schedule": {"type": "string"}, "cwd": {"type": "string", "default": "."}, "install": {"type": "boolean", "default": False}}, ["name", "command", "schedule"]), cron_create),
    ToolSpec("cron.list", "List runtime cron job definitions.", object_schema({}, []), cron_list),
]
