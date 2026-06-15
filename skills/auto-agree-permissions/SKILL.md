---
name: auto-agree-permissions
description: Install and operate a local permission auto-approval helper for Claude Code, Codex, and terminal confirmation prompts. Use when a user wants Claude Code or Codex to stop asking for routine tool approvals, wants bypass-like behavior, wants terminal prompts auto-confirmed, or wants a portable setup that can be copied to another machine.
---

# Auto Agree Permissions

Use this skill when the user wants a local, user-level permission approval helper
for Claude Code, Codex, or terminal confirmation prompts.

The skill ships dependency-free scripts:

```sh
python3 scripts/auto_agree_bootstrap.py install --mode safe
python3 scripts/terminal_auto_approve.py run --mode all -- your-command
```

The script installs a Claude Code `PreToolUse` and `PermissionRequest` hook at:

```text
~/.claude-auto-agree/auto_agree_hook.py
```

It stores config and logs at:

```text
~/.claude-auto-agree/config.json
~/.claude-auto-agree/log.jsonl
```

## Modes

- `safe`: allow routine read/dev commands and workspace-local edits.
- `all`: allow every Claude Code permission request handled by the hook.
- `off`: make no decision; Claude Code shows normal prompts.

## Common Commands

Install Claude Code hook in safe mode:

```sh
python3 scripts/auto_agree_bootstrap.py install --mode safe
```

Switch Claude Code to all mode:

```sh
python3 scripts/auto_agree_bootstrap.py mode all
```

Turn Claude Code auto approval off:

```sh
python3 scripts/auto_agree_bootstrap.py mode off
```

Remove the Claude Code hook:

```sh
python3 scripts/auto_agree_bootstrap.py uninstall
```

Enable Codex approve-everything mode:

```sh
python3 scripts/auto_agree_bootstrap.py codex-all
```

Restore Codex settings changed by the bootstrap:

```sh
python3 scripts/auto_agree_bootstrap.py codex-off
```

Show status:

```sh
python3 scripts/auto_agree_bootstrap.py status
```

Run a command and auto-answer known terminal confirmation prompts:

```sh
python3 scripts/terminal_auto_approve.py run --mode all -- your-command arg1 arg2
```

Watch an already-open macOS Terminal/iTerm2 window:

```sh
python3 scripts/terminal_auto_approve.py watch --app Terminal --mode all
python3 scripts/terminal_auto_approve.py watch --app iTerm2 --mode all
```

## Operating Rules

- Default to `safe` unless the user explicitly asks for approval of everything.
- Explain that `all` is high power and can still be overridden by app policy or
  hard safety checks.
- Do not use mouse or keyboard automation for Claude permission dialogs. Use the
  hook/config path.
- For terminal prompts, prefer `terminal_auto_approve.py run` when starting a new
  command. Use `watch` only when the prompt is already open in Terminal/iTerm2.
- Never auto-enter passwords, API keys, OTP/2FA codes, or similar secrets.
- Do not paste secrets into chat. The hook log redacts obvious token-like values.
- Existing Claude Code or Codex sessions may need a new session or app restart
  before config changes are picked up.
