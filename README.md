# Auto Agree Permissions

Portable local auto-approval helper for Claude Code and Codex.

It includes:

- a dependency-free Python bootstrap script
- a dependency-free terminal confirmation helper
- a reusable Codex/Claude skill folder
- safe, all, and off modes
- backup-before-edit behavior for user settings

This is not GUI click automation. It uses Claude Code hooks and Codex config
files. The optional terminal helper only targets terminal prompts and sends
keyboard input to Terminal/iTerm2 when explicitly run.

## Quick Start

Install the Claude Code hook in safe mode:

```sh
python3 auto_agree_bootstrap.py install --mode safe
```

Switch Claude Code to approve everything handled by the hook:

```sh
python3 auto_agree_bootstrap.py mode all
```

Turn Claude Code auto approval off:

```sh
python3 auto_agree_bootstrap.py mode off
```

Remove the Claude Code hook:

```sh
python3 auto_agree_bootstrap.py uninstall
```

Show status:

```sh
python3 auto_agree_bootstrap.py status
```

## Codex

Enable Codex approve-everything mode:

```sh
python3 auto_agree_bootstrap.py codex-all
```

Restore Codex values changed by this tool:

```sh
python3 auto_agree_bootstrap.py codex-off
```

Safe Codex mode:

```sh
python3 auto_agree_bootstrap.py codex-safe
```

## Terminal Confirmation Prompts

Run a command under a managed pseudo-terminal:

```sh
python3 terminal_auto_approve.py run --mode all -- npm install
```

Watch an already-open macOS terminal window:

```sh
python3 terminal_auto_approve.py watch --app Terminal --mode all
python3 terminal_auto_approve.py watch --app iTerm2 --mode all
```

The helper recognizes common prompts such as `Continue? [y/N]`, `Press Enter to
continue`, highlighted `Yes/Allow/Continue` rows, and numbered `1. Yes` menus.

Hard safety rules still apply: it never enters passwords, passphrases, API keys,
OTP/2FA codes, or similar secrets. In `safe` mode it also refuses prompts whose
recent terminal context looks destructive, such as `sudo`, `rm -rf`, production
deploys, migrations, destructive git operations, or cloud write commands.

## Reusable Skill

Copy this folder into your Codex skills directory:

```text
skills/auto-agree-permissions/
```

Then use the bundled script:

```sh
python3 skills/auto-agree-permissions/scripts/auto_agree_bootstrap.py install --mode safe
```

The copied skill also includes:

```sh
python3 skills/auto-agree-permissions/scripts/terminal_auto_approve.py run --mode all -- your-command
```

## What It Changes

Claude Code:

- writes hook script to `~/.claude-auto-agree/auto_agree_hook.py`
- writes config to `~/.claude-auto-agree/config.json`
- appends audit logs to `~/.claude-auto-agree/log.jsonl`
- merges hook entries into `~/.claude/settings.json`

Codex:

- writes top-level `approval_policy` and `sandbox_mode` in `~/.codex/config.toml`
- stores original values in `~/.claude-auto-agree/bootstrap_state.json`

Settings files are backed up before mutation.

## Modes

- `safe`: allow routine read/dev commands and workspace-local edits.
- `all`: allow every Claude Code permission request the hook can handle.
- `off`: make no decision and let Claude Code show normal prompts.

`all` is high power. App-level deny rules, managed policy, and hard safety
checks may still override it.

## Requirements

- macOS or Linux
- Python 3.9+
- Claude Code for Claude hook usage
- Codex for Codex config usage
- macOS Accessibility permission for `terminal_auto_approve.py watch`

## License

MIT
