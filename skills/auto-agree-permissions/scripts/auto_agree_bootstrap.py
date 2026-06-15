#!/usr/bin/env python3
"""Portable Auto Agree bootstrap for Claude Code and Codex.

This file is intentionally dependency-free and can be copied by itself. It
writes a small Claude Code hook into ~/.claude-auto-agree and can also manage
Codex approval settings.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import time_ns
from typing import Any


HOOK_ID = "auto-agree-portable-hook"
VALID_MODES = ("safe", "all", "off")
HOOK_EVENTS = ("PreToolUse", "PermissionRequest")
CODEX_KEYS = ("approval_policy", "sandbox_mode")
CODEX_ALL = {"approval_policy": "never", "sandbox_mode": "danger-full-access"}
CODEX_SAFE = {"approval_policy": "on-request", "sandbox_mode": "workspace-write"}


HOOK_SOURCE = r'''#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import shlex
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VALID_MODES = {"safe", "all", "off"}
DEFAULT_CONFIG = {"mode": "safe", "log": True}
WRITE_TOOLS = {"Edit", "MultiEdit", "NotebookEdit", "Write"}
READ_TOOLS = {"Glob", "Grep", "LS", "Read"}
SAFE_FIRST_WORDS = {
    "cat", "date", "du", "env", "file", "find", "git", "grep", "head",
    "jq", "ls", "nl", "npm", "pnpm", "pwd", "python", "python3", "rg",
    "sed", "sort", "tail", "test", "tree", "uname", "wc", "which", "yarn",
}
SAFE_GIT = {"status", "diff", "log", "show", "fetch", "ls-remote", "ls-files", "rev-parse", "remote", "grep", "blame"}
SAFE_PACKAGE = {"test", "tests", "lint", "check", "build", "typecheck", "format:check"}
DANGEROUS_WORDS = {"sudo", "su", "rm", "rmdir", "chmod", "chown", "dd", "diskutil", "launchctl", "mkfs", "mount", "reboot", "shutdown", "umount"}
PROTECTED_PARTS = {".git", ".claude", ".ssh", ".gnupg", "Keychains"}
PROFILE_NAMES = {".bash_profile", ".bashrc", ".profile", ".zprofile", ".zshenv", ".zshrc", "config.fish"}
SENSITIVE_NAME_RE = re.compile(r"(^\.env($|\.)|secret|credential|token|private[_-]?key|id_rsa|id_ed25519|\.pem$|\.key$)", re.I)
SECRET_VALUE_RE = re.compile(r"(?i)(api[_-]?key|token|secret|password|passwd|authorization|bearer)(\s*[=:]\s*)([^\s\"']+)")


def config_dir() -> Path:
    return Path(os.environ.get("CLAUDE_AUTO_AGREE_HOME", "~/.claude-auto-agree")).expanduser()


def config_path() -> Path:
    return config_dir() / "config.json"


def log_path() -> Path:
    return config_dir() / "log.jsonl"


def load_config() -> dict[str, Any]:
    config = dict(DEFAULT_CONFIG)
    try:
        if config_path().exists():
            loaded = json.loads(config_path().read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                config.update(loaded)
    except Exception:
        pass
    env_mode = os.environ.get("CLAUDE_AUTO_AGREE_MODE")
    if env_mode:
        config["mode"] = env_mode
    if config.get("mode") not in VALID_MODES:
        config["mode"] = "safe"
    config["log"] = bool(config.get("log", True))
    return config


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if not isinstance(value, str):
        return value
    text = SECRET_VALUE_RE.sub(r"\1\2[REDACTED]", value)
    return re.sub(r"(?i)(sk-[A-Za-z0-9_-]{12,}|sk-ant-[A-Za-z0-9_-]+)", "[REDACTED]", text)


def summarize(value: Any, limit: int = 500) -> str:
    value = redact(value)
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 3] + "..."


def tool_name(payload: dict[str, Any]) -> str:
    for key in ("tool_name", "toolName", "tool"):
        if isinstance(payload.get(key), str):
            return str(payload[key])
    permission = payload.get("permission") or payload.get("permission_request")
    if isinstance(permission, dict):
        for key in ("tool_name", "toolName", "tool"):
            if isinstance(permission.get(key), str):
                return str(permission[key])
    return ""


def tool_input(payload: dict[str, Any]) -> Any:
    for key in ("tool_input", "toolInput", "input", "parameters"):
        if key in payload:
            return payload[key]
    permission = payload.get("permission") or payload.get("permission_request")
    if isinstance(permission, dict):
        for key in ("tool_input", "toolInput", "input", "parameters"):
            if key in permission:
                return permission[key]
    return {}


def command_from(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("command", "cmd", "script"):
            if isinstance(value.get(key), str):
                return str(value[key])
    return ""


def split_command(command: str) -> list[str]:
    try:
        return shlex.split(command, posix=True)
    except ValueError:
        return command.split()


def has_dangerous_shell(command: str) -> bool:
    lowered = command.lower()
    if ("curl" in lowered or "wget" in lowered) and re.search(r"\|\s*(sh|bash|zsh|python|python3)\b", lowered):
        return True
    if re.search(r"(^|\s)(rm)\s+(-[A-Za-z]*[rf][A-Za-z]*|-[A-Za-z]*r[A-Za-z]*f)", command):
        return True
    if re.search(r"(^|[;&|]\s*)(sudo|su|chmod|chown|dd|diskutil|launchctl|mkfs|mount|reboot|shutdown|umount)\b", lowered):
        return True
    if re.search(r"\b(git)\s+(reset|clean|push|rebase|merge|checkout|switch|restore)\b", lowered):
        return True
    if re.search(r"\b(kubectl|terraform|aws|gcloud|az|vercel|flyctl|railway|supabase)\b", lowered):
        return True
    return False


def bash_safe(command: str) -> tuple[str, str]:
    command = re.sub(r"\s+", " ", command.strip())
    if not command:
        return "none", "empty command"
    if has_dangerous_shell(command):
        return "none", "dangerous command"
    tokens = split_command(command)
    if not tokens:
        return "none", "empty command"
    first = Path(tokens[0]).name
    if first not in SAFE_FIRST_WORDS:
        return "none", f"unknown command {first}"
    if first == "git":
        sub = tokens[1] if len(tokens) > 1 else ""
        return ("allow", "safe git command") if sub in SAFE_GIT else ("none", "git subcommand needs review")
    if first in {"npm", "pnpm", "yarn"}:
        if len(tokens) >= 2 and (tokens[1] in SAFE_PACKAGE or tokens[1] in {"install", "i"}):
            return "allow", "safe package command"
        if len(tokens) >= 3 and tokens[1] == "run" and tokens[2] in SAFE_PACKAGE:
            return "allow", "safe package script"
        return "none", "package command needs review"
    return "allow", "safe read/dev command"


def path_from_input(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("file_path", "path", "notebook_path"):
            if isinstance(value.get(key), str):
                return str(value[key])
    return value if isinstance(value, str) else ""


def path_safe(raw_path: str, cwd: str | None) -> tuple[str, str]:
    if not raw_path:
        return "none", "missing path"
    base = Path(cwd or os.getcwd()).expanduser().resolve()
    target = Path(raw_path).expanduser()
    if not target.is_absolute():
        target = base / target
    try:
        resolved = target.resolve(strict=False)
        resolved.relative_to(base)
    except Exception:
        return "none", "path outside workspace"
    parts = set(resolved.parts)
    if parts & PROTECTED_PARTS or resolved.name in PROFILE_NAMES or SENSITIVE_NAME_RE.search(resolved.name):
        return "none", "protected or sensitive path"
    return "allow", "workspace path"


def decide(payload: dict[str, Any], mode: str | None = None) -> tuple[str, str]:
    mode = mode or str(load_config().get("mode", "safe"))
    if mode == "off":
        return "none", "mode off"
    if mode == "all":
        return "allow", "all mode"
    if mode != "safe":
        return "none", "unknown mode"
    name = tool_name(payload)
    value = tool_input(payload)
    if name == "Bash":
        return bash_safe(command_from(value))
    if name in READ_TOOLS:
        return "allow", "safe read tool"
    if name in WRITE_TOOLS:
        return path_safe(path_from_input(value), payload.get("cwd") or payload.get("working_directory"))
    return "none", "unknown tool"


def write_log(payload: dict[str, Any], mode: str, decision: str, reason: str) -> None:
    if not load_config().get("log", True):
        return
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "decision": decision,
        "reason": reason,
        "hook_event_name": payload.get("hook_event_name") or payload.get("hookEventName"),
        "cwd": payload.get("cwd") or payload.get("working_directory"),
        "tool_name": tool_name(payload),
        "summary": summarize(tool_input(payload)),
    }
    try:
        config_dir().mkdir(parents=True, exist_ok=True)
        with log_path().open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(redact(event), ensure_ascii=False, sort_keys=True) + "\n")
    except Exception:
        pass


def run(payload: dict[str, Any]) -> dict[str, Any] | None:
    mode = str(load_config().get("mode", "safe"))
    decision, reason = decide(payload, mode)
    write_log(payload, mode, decision, reason)
    if decision != "allow":
        return None
    return {
        "hookSpecificOutput": {"hookEventName": payload.get("hook_event_name") or "PermissionRequest", "permissionDecision": "allow", "permissionDecisionReason": reason},
        "permissionDecision": "allow",
        "permissionDecisionReason": reason,
    }


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    output = run(payload)
    if output:
        print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def config_dir() -> Path:
    return Path(os.environ.get("CLAUDE_AUTO_AGREE_HOME", "~/.claude-auto-agree")).expanduser()


def config_path() -> Path:
    return config_dir() / "config.json"


def hook_path() -> Path:
    return config_dir() / "auto_agree_hook.py"


def state_path() -> Path:
    return config_dir() / "bootstrap_state.json"


def claude_settings_path() -> Path:
    return Path(os.environ.get("CLAUDE_SETTINGS_PATH", "~/.claude/settings.json")).expanduser()


def codex_config_path() -> Path:
    return Path(os.environ.get("CODEX_CONFIG_PATH", "~/.codex/config.toml")).expanduser()


def backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    target = path.with_name(f"{path.name}.auto-agree-backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{time_ns()}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, target)
    return target


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"Expected JSON object in {path}")
    return data


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_state() -> dict[str, Any]:
    data = read_json(state_path())
    data.setdefault("codex", {})
    return data


def write_state(data: dict[str, Any]) -> None:
    write_json(state_path(), data)


def write_hook() -> None:
    target = hook_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(HOOK_SOURCE, encoding="utf-8")
    target.chmod(0o755)


def ensure_config(mode: str) -> None:
    if mode not in VALID_MODES:
        raise SystemExit(f"Unsupported mode: {mode}")
    config = {"mode": mode, "log": True}
    if config_path().exists():
        current = read_json(config_path())
        if current.get("mode") in VALID_MODES:
            config["mode"] = str(current["mode"])
        config["log"] = bool(current.get("log", True))
    config["mode"] = mode
    write_json(config_path(), config)


def managed_command() -> str:
    return f"python3 {json.dumps(str(hook_path()))}"


def is_managed_hook(hook: Any) -> bool:
    if not isinstance(hook, dict):
        return False
    if hook.get("id") == HOOK_ID:
        return True
    command = hook.get("command")
    return isinstance(command, str) and str(hook_path()) in command


def remove_managed_hooks(settings: dict[str, Any]) -> int:
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return 0
    removed = 0
    for event in list(hooks):
        groups = hooks.get(event)
        if not isinstance(groups, list):
            continue
        new_groups = []
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                new_groups.append(group)
                continue
            kept = []
            for hook in group["hooks"]:
                if is_managed_hook(hook):
                    removed += 1
                else:
                    kept.append(hook)
            if kept:
                copied = dict(group)
                copied["hooks"] = kept
                new_groups.append(copied)
        if new_groups:
            hooks[event] = new_groups
        else:
            hooks.pop(event, None)
    if not hooks:
        settings.pop("hooks", None)
    return removed


def install(args: argparse.Namespace) -> None:
    write_hook()
    ensure_config(args.mode)
    path = claude_settings_path()
    settings = read_json(path)
    backup(path)
    remove_managed_hooks(settings)
    hooks = settings.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise SystemExit(f"settings.hooks in {path} must be an object")
    entry = {
        "matcher": ".*",
        "hooks": [{"type": "command", "command": managed_command(), "timeout": 5, "id": HOOK_ID}],
    }
    for event in HOOK_EVENTS:
        groups = hooks.setdefault(event, [])
        if not isinstance(groups, list):
            raise SystemExit(f"settings.hooks.{event} in {path} must be a list")
        groups.append(json.loads(json.dumps(entry)))
    write_json(path, settings)
    print(f"Installed Claude Code Auto Agree hook: {hook_path()}")
    print(f"Mode: {args.mode}")


def uninstall(_: argparse.Namespace) -> None:
    path = claude_settings_path()
    settings = read_json(path)
    backup(path)
    removed = remove_managed_hooks(settings)
    write_json(path, settings)
    print(f"Removed {removed} managed hook(s) from {path}")


def set_mode(args: argparse.Namespace) -> None:
    write_hook()
    ensure_config(args.mode)
    print(f"Mode set to {args.mode}")


def parse_top_level(text: str) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    pattern = re.compile(r"^\s*([A-Za-z0-9_.-]+)\s*=\s*(.*?)\s*(?:#.*)?$")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            break
        match = pattern.match(line)
        if match and match.group(1) in CODEX_KEYS and match.group(1) not in found:
            found[match.group(1)] = {"present": True, "value": match.group(2).strip()}
    for key in CODEX_KEYS:
        found.setdefault(key, {"present": False, "value": None})
    return found


def write_codex(assignments: dict[str, str]) -> None:
    path = codex_config_path()
    original = path.read_text(encoding="utf-8") if path.exists() else ""
    state = read_state()
    codex = state.setdefault("codex", {})
    codex.setdefault("config_path", str(path))
    codex.setdefault("original", parse_top_level(original))
    write_state(state)
    backup(path)

    lines = original.splitlines()
    new_lines = []
    in_top = True
    key_re = re.compile(r"^\s*([A-Za-z0-9_.-]+)\s*=")
    skip_blank = False
    for line in lines:
        stripped = line.strip()
        if stripped == "# Auto Agree managed Codex approval settings":
            skip_blank = True
            continue
        if in_top and stripped.startswith("[") and stripped.endswith("]"):
            in_top = False
        if skip_blank and not stripped:
            skip_blank = False
            continue
        skip_blank = False
        match = key_re.match(line)
        if in_top and match and match.group(1) in CODEX_KEYS:
            continue
        new_lines.append(line)

    managed = ["# Auto Agree managed Codex approval settings"]
    managed.extend(f'{key} = "{value}"' for key, value in assignments.items())
    if new_lines and new_lines[0].strip():
        managed.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(managed + new_lines).rstrip() + "\n", encoding="utf-8")


def restore_codex(_: argparse.Namespace) -> None:
    path = codex_config_path()
    state = read_state()
    original = state.get("codex", {}).get("original")
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    backup(path)

    lines = current.splitlines()
    new_lines = []
    in_top = True
    key_re = re.compile(r"^\s*([A-Za-z0-9_.-]+)\s*=")
    skip_blank = False
    for line in lines:
        stripped = line.strip()
        if stripped == "# Auto Agree managed Codex approval settings":
            skip_blank = True
            continue
        if in_top and stripped.startswith("[") and stripped.endswith("]"):
            in_top = False
        if skip_blank and not stripped:
            skip_blank = False
            continue
        skip_blank = False
        match = key_re.match(line)
        if in_top and match and match.group(1) in CODEX_KEYS:
            continue
        new_lines.append(line)

    restore = []
    if isinstance(original, dict):
        for key in CODEX_KEYS:
            item = original.get(key, {})
            if isinstance(item, dict) and item.get("present"):
                restore.append(f"{key} = {item.get('value')}")
    if restore and new_lines and new_lines[0].strip():
        restore.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(restore + new_lines).rstrip() + "\n", encoding="utf-8")
    state.setdefault("codex", {}).pop("original", None)
    write_state(state)
    print(f"Restored managed Codex approval settings in {path}")


def codex_all(_: argparse.Namespace) -> None:
    write_codex(CODEX_ALL)
    print(f"Codex approve-everything mode enabled: {codex_config_path()}")


def codex_safe(_: argparse.Namespace) -> None:
    write_codex(CODEX_SAFE)
    print(f"Codex safe review mode enabled: {codex_config_path()}")


def hook_installed(settings: dict[str, Any]) -> bool:
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return False
    for groups in hooks.values():
        if not isinstance(groups, list):
            continue
        for group in groups:
            if not isinstance(group, dict):
                continue
            for hook in group.get("hooks", []):
                if is_managed_hook(hook):
                    return True
    return False


def current_codex() -> dict[str, Any]:
    path = codex_config_path()
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    parsed = parse_top_level(text)
    values = {}
    for key, item in parsed.items():
        value = item.get("value") if item.get("present") else None
        if isinstance(value, str) and len(value) >= 2 and value[0] == value[-1] == '"':
            value = value[1:-1]
        values[key] = value
    values["enabled"] = values.get("approval_policy") == "never" and values.get("sandbox_mode") == "danger-full-access"
    values["safe"] = values.get("approval_policy") == "on-request" and values.get("sandbox_mode") == "workspace-write"
    return values


def status(_: argparse.Namespace) -> None:
    config = read_json(config_path())
    codex = current_codex()
    print(f"Claude hook installed: {'yes' if hook_installed(read_json(claude_settings_path())) else 'no'}")
    print(f"Mode: {config.get('mode', 'safe')}")
    print(f"Hook: {hook_path()}")
    print(f"Config: {config_path()}")
    print(f"Claude settings: {claude_settings_path()}")
    print(f"Codex config: {codex_config_path()}")
    print(f"Codex approval_policy: {codex.get('approval_policy') or '(unset)'}")
    print(f"Codex sandbox_mode: {codex.get('sandbox_mode') or '(unset)'}")
    print(f"Codex approve everything: {'yes' if codex.get('enabled') else 'no'}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Portable Auto Agree bootstrap for Claude Code and Codex")
    sub = parser.add_subparsers(dest="command", required=True)
    install_parser = sub.add_parser("install", help="Install Claude Code hooks")
    install_parser.add_argument("--mode", choices=VALID_MODES, default="safe")
    install_parser.set_defaults(func=install)
    mode_parser = sub.add_parser("mode", help="Set Claude Code hook mode")
    mode_parser.add_argument("mode", choices=VALID_MODES)
    mode_parser.set_defaults(func=set_mode)
    sub.add_parser("uninstall", help="Remove Claude Code hooks").set_defaults(func=uninstall)
    sub.add_parser("codex-all", help="Set Codex approval_policy=never and sandbox_mode=danger-full-access").set_defaults(func=codex_all)
    sub.add_parser("codex-safe", help="Set Codex approval_policy=on-request and sandbox_mode=workspace-write").set_defaults(func=codex_safe)
    sub.add_parser("codex-off", help="Restore Codex keys changed by this bootstrap").set_defaults(func=restore_codex)
    sub.add_parser("status", help="Show current status").set_defaults(func=status)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

