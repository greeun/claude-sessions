# claude-sessions

**Languages:** **English** · [한국어](README.ko.md)

> Browse, search, resume, back up, and relocate every local Claude Code session from your terminal.

`claude-sessions` is a single-file Python CLI that indexes every session transcript Claude Code has ever written under `~/.claude/projects/`, then gives you an interactive `fzf`-style picker and a set of subcommands to manage them.

**Why?** Claude Code's built-in `/resume` only shows sessions that were started in the **current folder**. If you ran `claude` from many different directories you have no way to see the full history or jump back into a session you started somewhere else. This tool fixes that — it treats `~/.claude/projects/` as a queryable database of your conversations.

```
 claude-sessions v0.1.0  86/86   ↑↓ move  PgUp/PgDn page  Enter open  Space mark  Del delete  Esc quit
>
   LAST ACTIVITY     SESSION      MSGS  MESSAGE
 ● 2026-04-11 15:41  f6b0b565   [  42]  로컬 시스템에서 작업했던 모든 세션 목록을 조회하는 스킬…
   2026-04-11 15:40  125ac1ac   [ 416]  biz-plan-harness 스킬을 이용해서 "경계선지능 학습자 대안…
   2026-04-11 15:26  f6e7aced   [ 202]  생성할 콘텐츠는 경계선 학습자를 위한 것으로 수준 또는 레벨…
 📁  ~/.claude/skills
```

---

## Features

- **Global session index** — scans `~/.claude/projects/**/*.jsonl` across every folder you've ever run Claude Code in.
- **Interactive picker** with live keyword filter, arrow-key navigation, multi-select, and resume-in-place.
- **Full-text search** across user and assistant messages with snippet previews.
- **Transcript viewer** that also expands sub-agent conversations dispatched via the `Task` tool.
- **Backup / restore** — archive old sessions to a `tar.gz` bundle and bring them back later.
- **Relocate** — rewrite a session's recorded working directory when Claude Code was started in folder A but the real work happened in folder B.
- **Metadata cache** under `~/.cache/claude-sessions/index.json` — first run takes a few seconds to index, subsequent runs are near-instant (mtime/size-based invalidation).
- **Zero dependencies** — pure Python stdlib. No `pip install` step.

---

## Installation

1. Clone or drop the folder anywhere you like, for example under `~/.claude/skills/claude-sessions/`:

    ```bash
    git clone https://github.com/greeun/claude-sessions ~/.claude/skills/claude-sessions
    ```

2. Make the script executable and link it onto your `$PATH`:

    ```bash
    chmod +x ~/.claude/skills/claude-sessions/sessions.py
    mkdir -p ~/.local/bin
    ln -sf ~/.claude/skills/claude-sessions/sessions.py ~/.local/bin/claude-sessions
    ```

3. Verify:

    ```bash
    claude-sessions --version
    # claude-sessions v0.1.0
    ```

Make sure `~/.local/bin` is on your `PATH` (most shell setups already include it). The script requires Python 3.9+ and has no third-party dependencies.

### Optional: shell alias

If you open the picker often, add a short alias to your shell rc file. Put one of these in `~/.zshrc`, `~/.bashrc`, or `~/.config/fish/config.fish`:

```bash
# Bash / Zsh
alias cs='claude-sessions'

# Fish
alias cs 'claude-sessions'
```

Then reload:

```bash
# Bash
source ~/.bashrc
# Zsh
source ~/.zshrc
# Fish
source ~/.config/fish/config.fish
```

After that, `cs` opens the picker, `cs search "foo"` runs a search, `cs list --days 7` lists the last week, and so on — every subcommand and flag works the same as `claude-sessions`.

> **Heads up** — run `type cs` first to make sure the name isn't already taken on your system. If it conflicts, pick something else like `csess`, `cses`, or `clh`.

> **Note** — `claude-sessions` only reads and manages files under `~/.claude/projects/` and `~/.cache/claude-sessions/`. It never touches your repositories, and destructive commands (`delete`, `backup --delete`, `relocate` without `--keep-original`) always prompt for confirmation unless you pass `-y`.

---

## Quick start

```bash
claude-sessions                     # open the interactive picker (default)
claude-sessions list --limit 20     # table of the 20 most-recent sessions
claude-sessions list --days 7       # only sessions touched in the last week
claude-sessions search "migration"  # full-text search
claude-sessions show 125ac1ac       # print a session transcript
claude-sessions resume 125ac1ac     # cd into its cwd and `claude --resume`
claude-sessions stats --top 10      # per-project session counts
```

### The interactive picker

Running `claude-sessions` with no arguments launches a curses TUI:

| Key                 | Action                                                           |
|---------------------|------------------------------------------------------------------|
| `↑` `↓` / `Ctrl-P/N`| Move selection                                                   |
| `PgUp` `PgDn`       | Page up / down                                                   |
| `Home` `End`        | Jump to first / last                                             |
| *type letters*      | Live filter by session id, cwd, or first message                 |
| `Backspace`         | Edit the filter                                                  |
| `Ctrl-U`            | Clear the filter                                                 |
| `Space`             | Toggle a mark on the current row (multi-select)                  |
| `Ctrl-X`            | Clear all marks                                                  |
| `Del` / `Fn+Delete` | Delete marked (or current) session(s) — with confirmation modal  |
| `Enter`             | `cd` to the session's cwd and `claude --resume <id>`             |
| `Esc`               | Quit                                                             |

When you press `Enter`, `claude-sessions` replaces its own process with `claude --resume <id>` inside the session's original working directory, so you land directly in the resumed conversation. When you exit Claude Code, your shell stays where it started.

---

## Commands reference

All commands support `--help`. Subcommand summaries:

| Command      | What it does                                                                                     |
|--------------|--------------------------------------------------------------------------------------------------|
| `pick`       | Interactive picker (default when no subcommand is given).                                        |
| `list`       | Print a table of recent sessions. Flags: `--limit N`, `--cwd PREFIX`, `--days N`.                |
| `search`     | Full-text search across user & assistant text. Flags: `-i`, `--cwd PREFIX`, `--limit N`. Query supports `a\|b` for OR. |
| `show`       | Print a session transcript. Flags: `--max-chars N`, `--with-subagents`.                          |
| `resume`     | Print (or let you pipe) a `cd + claude --resume` one-liner. Flag: `--print-only`.                |
| `subagents`  | List every sub-agent transcript dispatched from a parent session.                                |
| `backup`     | Archive old sessions into a single `tar.gz` (plus a JSON manifest).                              |
| `restore`    | Restore a backup archive. Flags: `--cwd PREFIX`, `--on-conflict skip\|overwrite\|rename`, `--dry-run`. |
| `relocate`   | Rewrite a session's recorded `cwd` and move it to the matching project directory.               |
| `stats`      | Per-project session counts and totals.                                                          |

### `list` / `pick` — browse sessions

```bash
claude-sessions list --limit 30
claude-sessions pick --days 14 --cwd ~/project/acme
```

`pick` is the curses picker; `list` prints the same data as a plain table so you can pipe it to `grep`, `less`, etc.

### `search` — full-text search

```bash
claude-sessions search "rate limiter" -i --limit 20
claude-sessions search "nextjs|remix" --cwd ~/project
```

Each hit shows up to three matching snippets with the session id, cwd, and timestamp so you can jump back to the right conversation.

### `show` — read a transcript

```bash
claude-sessions show 125ac1ac                  # parent session only
claude-sessions show 125ac1ac --with-subagents # + every sub-agent dispatched
claude-sessions show agent-aafeba26            # sub-agent by id prefix
```

`show` will accept any 8+-character prefix, including the `agent-<hex>` ids used by sub-agent transcripts stored under `<parent-id>/subagents/`.

### `subagents` — see what Task dispatched

```bash
claude-sessions subagents 125ac1ac
```

Lists every sub-agent the parent session spawned, including the agent type, message count, and first prompt — pulled from the `.meta.json` files Claude Code writes next to each sub-agent transcript.

### `resume` — jump back into a session

```bash
claude-sessions resume 125ac1ac            # prints a cd + claude --resume command
claude-sessions resume 125ac1ac --print-only | bash   # execute it directly
```

The picker's Enter key uses the same underlying logic.

### `backup` — archive old sessions

```bash
claude-sessions backup --dry-run                          # preview
claude-sessions backup --days 90                          # archive 90+ day old sessions
claude-sessions backup --before 2025-01-01 --delete       # archive + remove originals
claude-sessions backup --cwd ~/project/acme --out acme.tgz
```

- Writes a compressed tarball of each session's `.jsonl` plus a `manifest.json` describing the archive (`created_at`, `cutoff`, per-session metadata).
- Default output path is `~/.claude/backups/sessions-<timestamp>.tar.gz`.
- `--delete` removes the originals only after the archive succeeds; `--force` overrides that safety check if some files failed to archive.

### `restore` — unpack a backup

```bash
claude-sessions restore ~/.claude/backups/sessions-20260411-153000.tar.gz --dry-run
claude-sessions restore <archive> --on-conflict rename
claude-sessions restore <archive> --cwd ~/project/acme
```

Restored files go back into `~/.claude/projects/`, the cache is invalidated, and next run re-indexes them. Conflict policies are `skip` (default), `overwrite`, or `rename` (keeps the existing file and writes the restored copy under `<id>.restored-<timestamp>.jsonl`).

### `relocate` — fix the recorded cwd

When you start Claude Code in folder A but the real work happens in folder B (via `cd`, `Bash`, etc.), Claude Code still records A as the session's working directory. `relocate` rewrites every event's `cwd` field **and** moves the `.jsonl` into B's project directory, so both `claude --resume` and `claude-sessions resume` drop you into the right place:

```bash
claude-sessions relocate f6b0b565 ~/project/actual-work --dry-run
claude-sessions relocate f6b0b565 ~/project/actual-work
claude-sessions relocate f6b0b565 ~/project/actual-work --keep-original
```

Sub-agent transcripts stored under `<parent-id>/subagents/` are moved (or copied with `--keep-original`) alongside the parent.

### `stats` — per-project overview

```bash
claude-sessions stats --top 15
```

Prints totals plus the busiest project folders by session count.

---

## How it works

Claude Code stores every session as a JSON-Lines file at:

```
~/.claude/projects/<encoded-cwd>/<session-id>.jsonl
```

The `<encoded-cwd>` part is the session's starting working directory with every non-alphanumeric character (except `-`) replaced by `-`. So `/Users/me/.claude/skills` becomes `-Users-me--claude-skills`. Each line of the file is a JSON event (`type: user | assistant | tool_use | ...`) and contains a `cwd` field recorded at capture time.

Sub-agents dispatched via the `Task` tool are stored alongside the parent session:

```
~/.claude/projects/<cwd-dir>/<parent-id>/subagents/
  ├── agent-<hex>.jsonl       # the sub-agent transcript
  └── agent-<hex>.meta.json   # { agentType, description }
```

`claude-sessions` reads both top-level sessions and sub-agent transcripts. The index is cached at `~/.cache/claude-sessions/index.json` keyed by absolute path, modification time, and size — unchanged files are read straight from the cache.

---

## Data safety

- **Reads only by default** — `list`, `search`, `show`, `subagents`, `stats`, `resume`, and `pick` (without `d`/`Del`) never modify anything.
- **Confirmation on destructive ops** — `delete` in the picker uses a modal prompt; `backup --delete`, `restore`, and `relocate` prompt on the CLI unless `-y` is given.
- **Atomic writes** — `relocate` writes the new file to a `.tmp` path and renames on success, so an interrupted run never leaves a half-written session.
- **Reversible `backup`** — until you pass `--delete`, originals are left in place. The archive is a plain `tar.gz` you can inspect with `tar -tzf`.
- **Cache is disposable** — delete `~/.cache/claude-sessions/index.json` at any time; the next run rebuilds it.

---

## Versioning

`claude-sessions --version` prints the current version, and the picker header carries it too. Update the `__version__` string at the top of `sessions.py` when you cut a release.

Current version: **0.1.0**

---

## License

MIT (or whatever license fits your distribution — update this section if you fork).
