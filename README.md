# Auto Agree Permissions

Portable local auto-approval helper for Claude Code and Codex.

It includes:

- a dependency-free Python bootstrap script
- a reusable Codex/Claude skill folder
- safe, all, and off modes
- backup-before-edit behavior for user settings

This is not GUI click automation. It uses Claude Code hooks and Codex config
files.

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

## Reusable Skill

Copy this folder into your Codex skills directory:

```text
skills/auto-agree-permissions/
```

Then use the bundled script:

```sh
python3 skills/auto-agree-permissions/scripts/auto_agree_bootstrap.py install --mode safe
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

## License

MIT

