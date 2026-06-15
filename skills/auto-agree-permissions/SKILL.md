---
name: auto-agree-permissions
description: Install and operate a local permission auto-approval helper for Claude Code and Codex. Use when a user wants Claude Code or Codex to stop asking for routine tool approvals, wants bypass-like behavior, or wants a portable setup that can be copied to another machine.
---

# Auto Agree Permissions

Use this skill when the user wants a local, user-level permission approval helper
for Claude Code or Codex.

The skill ships a dependency-free bootstrap script:

```sh
python3 scripts/auto_agree_bootstrap.py install --mode safe
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

## Operating Rules

- Default to `safe` unless the user explicitly asks for approval of everything.
- Explain that `all` is high power and can still be overridden by app policy or
  hard safety checks.
- Do not use mouse or keyboard automation for Claude permission dialogs. Use the
  hook/config path.
- Do not paste secrets into chat. The hook log redacts obvious token-like values.
- Existing Claude Code or Codex sessions may need a new session or app restart
  before config changes are picked up.

