#!/usr/bin/env python3
"""Auto-answer known terminal confirmation prompts.

This standalone helper is dependency-free. It supports two workflows:

- run a command inside a managed pseudo-terminal
- watch macOS Terminal/iTerm2 and send approval keystrokes

It deliberately refuses password, token, OTP, and API-key prompts even in all
mode.
"""

from __future__ import annotations

import argparse
import json
import os
import pty
import re
import select
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


VALID_MODES = ("safe", "all", "off")
DEFAULT_CONFIG = {"mode": "safe", "log": True}
SECRET_PROMPT_RE = re.compile(
    r"(?i)(password|passphrase|verification code|one[- ]time code|2fa|mfa|otp|secret|api key)\s*[:：]?\s*$"
)
ANSI_CSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
ANSI_OSC_RE = re.compile(r"\x1b\][^\a]*(?:\a|\x1b\\)")
DANGEROUS_CONTEXT_RE = re.compile(
    r"(?i)(rm\s+-[A-Za-z]*[rf]|sudo\b|chmod\b|chown\b|dd\b|diskutil\b|mkfs\b|"
    r"drop\s+database|truncate\s+table|terraform\s+apply|terraform\s+destroy|"
    r"kubectl\s+delete|helm\s+upgrade|git\s+(push|reset|clean|rebase)|"
    r"\bdeploy\b|\bproduction\b|\bmigration\b|\bmigrate\b)"
)
SECRET_VALUE_RE = re.compile(
    r"(?i)(api[_-]?key|token|secret|password|passwd|authorization|bearer)(\s*[=:]\s*)([^\s\"']+)"
)


@dataclass(frozen=True)
class TerminalDecision:
    action: str
    reason: str
    matched: str = ""


PROMPT_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "press-enter",
        re.compile(r"(?i)(press|hit|type)\s+(enter|return)\s+(to\s+)?(continue|proceed|accept|approve)"),
        "enter",
    ),
    (
        "explicit-yes",
        re.compile(
            r"(?i:(continue|proceed|approve|allow|accept|confirm|do you want|would you like)).{0,120}"
            r"(\[y/N\]|\(y/N\)|\[[Yy][Ee][Ss]/[Nn][Oo]\]|\([Yy][Ee][Ss]/[Nn][Oo]\))"
        ),
        "yes_enter",
    ),
    (
        "default-yes",
        re.compile(
            r"(?i:(continue|proceed|approve|allow|accept|confirm|do you want|would you like)).{0,120}"
            r"(\[Y/n\]|\(Y/n\))"
        ),
        "enter",
    ),
    (
        "selected-yes",
        re.compile(r"(?im)^\s*(\u276f|>|=>|\u25b6|\u279c)\s*(yes|allow|approve|accept|continue|proceed)\b"),
        "enter",
    ),
    (
        "numbered-yes",
        re.compile(r"(?im)^\s*(1|\u2460)[.)]?\s+(yes|allow|approve|accept|continue|proceed)\b"),
        "one_enter",
    ),
    (
        "approve-line",
        re.compile(r"(?im)^\s*(allow|approve|accept|continue|proceed)\s*$"),
        "enter",
    ),
)


def config_dir() -> Path:
    return Path(os.environ.get("CLAUDE_AUTO_AGREE_HOME", "~/.claude-auto-agree")).expanduser()


def config_path() -> Path:
    return config_dir() / "config.json"


def terminal_log_path() -> Path:
    return config_dir() / "terminal_log.jsonl"


def load_config() -> dict[str, Any]:
    config = dict(DEFAULT_CONFIG)
    try:
        if config_path().exists():
            loaded = json.loads(config_path().read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                config.update(loaded)
    except Exception:
        pass
    return config


def normalize_mode(mode: str | None) -> str:
    if mode in VALID_MODES:
        return str(mode)
    env_mode = os.environ.get("CLAUDE_AUTO_AGREE_MODE")
    if env_mode in VALID_MODES:
        return env_mode
    config_mode = load_config().get("mode", "safe")
    return str(config_mode) if config_mode in VALID_MODES else "safe"


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return SECRET_VALUE_RE.sub(lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]", value)
    return value


def summarize(value: str, limit: int = 500) -> str:
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def recent_text(text: str, limit: int = 4000) -> str:
    text = ANSI_OSC_RE.sub("", text)
    text = ANSI_CSI_RE.sub("", text)
    text = text.replace("\r", "\n")
    return text[-limit:]


def decide_terminal_prompt(text: str, mode: str | None = None) -> TerminalDecision:
    mode = normalize_mode(mode)
    if mode == "off":
        return TerminalDecision("none", "mode off")

    window = recent_text(text)
    if SECRET_PROMPT_RE.search(window):
        return TerminalDecision("none", "secret prompt")

    dangerous = DANGEROUS_CONTEXT_RE.search(window) is not None
    for name, pattern, action in PROMPT_PATTERNS:
        match = pattern.search(window)
        if not match:
            continue
        if dangerous and mode != "all":
            return TerminalDecision("none", "dangerous context", name)
        return TerminalDecision(action, f"{mode} matched {name}", name)

    return TerminalDecision("none", "no prompt")


def action_bytes(action: str) -> bytes:
    if action == "enter":
        return b"\n"
    if action == "yes_enter":
        return b"y\n"
    if action == "one_enter":
        return b"1\n"
    return b""


def log_terminal_event(source: str, mode: str, decision: TerminalDecision, summary: str, dry_run: bool) -> None:
    if not bool(load_config().get("log", True)):
        return
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "mode": mode,
        "action": decision.action,
        "reason": decision.reason,
        "matched": decision.matched,
        "dry_run": dry_run,
        "summary": summarize(summary),
    }
    try:
        path = terminal_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(redact(payload), ensure_ascii=False, sort_keys=True) + "\n")
    except Exception:
        pass


def run_command(command: Sequence[str], mode: str, timeout: float | None = None, dry_run: bool = False) -> int:
    if not command:
        raise SystemExit("run requires a command after --")

    mode = normalize_mode(mode)
    master_fd, slave_fd = pty.openpty()
    process = subprocess.Popen(
        list(command),
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        close_fds=True,
    )
    os.close(slave_fd)

    start = time.monotonic()
    buffer = ""
    last_signature = ""
    try:
        while True:
            if timeout is not None and time.monotonic() - start > timeout:
                process.terminate()
                return 124

            ready, _, _ = select.select([master_fd], [], [], 0.2)
            if master_fd in ready:
                try:
                    data = os.read(master_fd, 4096)
                except OSError:
                    data = b""
                if data:
                    sys.stdout.buffer.write(data)
                    sys.stdout.buffer.flush()
                    buffer = recent_text(buffer + data.decode("utf-8", errors="replace"))
                    decision = decide_terminal_prompt(buffer, mode)
                    signature = f"{decision.action}:{decision.matched}:{buffer[-200:]}"
                    if process.poll() is None and decision.action != "none" and signature != last_signature:
                        log_terminal_event("terminal-run", mode, decision, buffer, dry_run)
                        if not dry_run:
                            try:
                                os.write(master_fd, action_bytes(decision.action))
                            except OSError:
                                pass
                        last_signature = signature
                        buffer = ""

            if process.poll() is not None:
                while True:
                    ready, _, _ = select.select([master_fd], [], [], 0)
                    if master_fd not in ready:
                        break
                    try:
                        data = os.read(master_fd, 4096)
                    except OSError:
                        break
                    if not data:
                        break
                    sys.stdout.buffer.write(data)
                    sys.stdout.buffer.flush()
                return int(process.returncode or 0)
    finally:
        try:
            os.close(master_fd)
        except OSError:
            pass


def osascript(script: str) -> str:
    result = subprocess.run(
        ["/usr/bin/osascript", "-e", script],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout


def frontmost_app_name() -> str:
    return osascript('tell application "System Events" to get name of first application process whose frontmost is true').strip()


def terminal_contents(app: str) -> str:
    if app == "auto":
        app = frontmost_app_name()
    if app == "Terminal":
        return osascript('tell application "Terminal" to if exists front window then get contents of selected tab of front window').strip()
    if app in {"iTerm", "iTerm2"}:
        return osascript('tell application "iTerm2" to if exists current window then get contents of current session of current window').strip()
    raise RuntimeError(f"Unsupported terminal app: {app}. Supported: Terminal, iTerm2, auto")


def send_action_to_terminal(app: str, action: str) -> None:
    if app == "auto":
        app = frontmost_app_name()
    prefix = ""
    if action == "yes_enter":
        prefix = 'keystroke "y"\n  '
    elif action == "one_enter":
        prefix = 'keystroke "1"\n  '
    elif action != "enter":
        return
    osascript(
        f'''tell application "{app}" to activate
tell application "System Events"
  {prefix}key code 36
end tell'''
    )


def watch_terminal(app: str, mode: str, interval: float, once: bool, dry_run: bool) -> int:
    mode = normalize_mode(mode)
    last_signature = ""
    print(f"Watching {app} terminal prompts in {mode} mode. Press Ctrl-C to stop.")
    while True:
        try:
            contents = terminal_contents(app)
            decision = decide_terminal_prompt(contents, mode)
            signature = f"{decision.action}:{decision.matched}:{recent_text(contents)[-200:]}"
            if decision.action != "none" and signature != last_signature:
                print(f"terminal-watch: {decision.action} ({decision.reason})")
                log_terminal_event(f"terminal-watch:{app}", mode, decision, contents, dry_run)
                if not dry_run:
                    send_action_to_terminal(app, decision.action)
                last_signature = signature
            if once:
                return 0 if decision.action != "none" else 1
            time.sleep(interval)
        except KeyboardInterrupt:
            return 130
        except Exception as exc:
            print(f"terminal-watch error: {exc}", file=sys.stderr)
            if once:
                return 1
            time.sleep(interval)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Auto approve known terminal confirmation prompts")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run a command in a managed pseudo-terminal")
    run_parser.add_argument("--mode", choices=VALID_MODES, default=None)
    run_parser.add_argument("--timeout", type=float, default=None)
    run_parser.add_argument("--dry-run", action="store_true")
    run_parser.add_argument("run_command", nargs=argparse.REMAINDER)

    watch_parser = subparsers.add_parser("watch", help="Watch macOS Terminal/iTerm2 and send approval keystrokes")
    watch_parser.add_argument("--app", default="auto", choices=("auto", "Terminal", "iTerm2", "iTerm"))
    watch_parser.add_argument("--mode", choices=VALID_MODES, default=None)
    watch_parser.add_argument("--interval", type=float, default=0.5)
    watch_parser.add_argument("--once", action="store_true")
    watch_parser.add_argument("--dry-run", action="store_true")

    decide_parser = subparsers.add_parser("decide", help="Print the decision for text from stdin")
    decide_parser.add_argument("--mode", choices=VALID_MODES, default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "run":
        command = list(args.run_command)
        if command and command[0] == "--":
            command = command[1:]
        return run_command(command, normalize_mode(args.mode), args.timeout, args.dry_run)
    if args.command == "watch":
        return watch_terminal(args.app, normalize_mode(args.mode), args.interval, args.once, args.dry_run)
    if args.command == "decide":
        decision = decide_terminal_prompt(sys.stdin.read(), normalize_mode(args.mode))
        print(json.dumps(decision.__dict__, ensure_ascii=False, sort_keys=True))
        return 0 if decision.action != "none" else 1
    parser.error(f"unknown command {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
