# watchdiff

VSCode extension that hooks into opencode's SSE event stream and auto-navigates to file edits as they happen.

## How it works

- Connects to `opencode serve` on configured ports via SSE (`/event` endpoint)
- Listens for `session.diff` and `file.edited` events
- On edit: opens the file, scrolls to the changed hunk, highlights it green for 4s
- Status bar shows connection count — click to toggle on/off

## Build

**Requirements:** Node.js, npm

```bash
pnpm install -g @vscode/vsce
cd watchdiff
vsce package --no-dependencies --allow-missing-repository
```

This produces `watchdiff-0.3.0.vsix`.

## Install

```bash
code --install-extension watchdiff-0.3.0.vsix
```

Or: VSCode → Extensions → `...` → Install from VSIX

## Settings

Open via: `Ctrl+Shift+P` → `WatchDiff: Open Settings`

| Setting | Default | Description |
|---|---|---|
| `watchdiff.ports` | `[4096]` | opencode server ports — add `5096, 6096` etc |
| `watchdiff.username` | `""` | Basic Auth username (OPENCODE_USER) |
| `watchdiff.password` | `""` | Basic Auth password (OPENCODE_PASSWORD) |
| `watchdiff.watchDir` | `""` | Override watch directory (OPENCODE_WATCH_DIR). Defaults to VSCode workspace root |

Example `settings.json`:
```json
{
  "watchdiff.ports": [4096, 5096, 6096],
  "watchdiff.username": "myuser",
  "watchdiff.password": "mypassword",
  "watchdiff.watchDir": "/path/to/project"
}
```

## Usage

1. Start `opencode serve` (default port 4096)
2. Open your project in VSCode
3. Status bar shows `👁 watchdiff 1/1` when connected
4. Run opencode — VSCode auto-navigates to each edit as it happens
