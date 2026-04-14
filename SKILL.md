---
name: claude-sessions
description: Browse, search, resume, back up, restore, and relocate every local Claude Code session stored under ~/.claude/projects/. Use when the user asks to "list sessions", "search past conversations", "find a session where I did X", "resume an old session", "back up old sessions", "restore from backup", "세션 목록", "이전 대화 검색", "세션 백업/복원", or wants to recover context from work across any project folder.
---

# claude-sessions

Scans every `~/.claude/projects/**/*.jsonl` transcript on the local machine and lets the user **list, search, view, resume, back up, restore, and relocate** Claude Code sessions — regardless of which folder they were originally started in. Also exposes sub-agent (Task-dispatched) transcripts.

## When to Use

- "로컬에서 작업했던 모든 세션 보여줘" / "list my sessions"
- "며칠 전에 X 작업했던 세션 찾아줘" / "find the session where I did X"
- "이 세션 이어서 작업할래" / "resume the X session"
- "90일 넘은 세션 백업해줘" / "back up old sessions"
- "백업한 세션 복원해줘" / "restore a backup"
- "세션의 작업 폴더를 B로 바꿔줘" / "relocate session cwd"
- "서브에이전트가 뭘 했는지 보여줘" / "show me what the sub-agents did"
- Any request to recover context from a past conversation across any folder.

## The Tool

All functionality lives in `sessions.py`. It has **no dependencies** (stdlib only) and is installed as a shell command at `~/.local/bin/claude-sessions`. Always prefer the shell wrapper:

```bash
claude-sessions <subcommand> [args]
# or (equivalent, if the symlink is missing)
python3 ~/.claude/skills/claude-sessions/sessions.py <subcommand> [args]
```

Current version: run `claude-sessions --version` (should print `v0.1.0` or newer). The version is also shown in the picker header and list output.

First run takes a few seconds to index all sessions; subsequent runs are near-instant thanks to `~/.cache/claude-sessions/index.json` (invalidated by mtime/size changes).

## Subcommands

### `pick` — interactive picker (default)
```bash
claude-sessions              # same as `claude-sessions pick`
claude-sessions pick --days 7 --cwd ~/project
```
A curses TUI. Use for all multi-session browsing tasks; do not dump large lists to chat. Note: `pick` requires a real TTY — it does not work when called through non-interactive Bash tool calls from the agent. For agent-initiated workflows, use `list` / `search` instead and present results yourself.

**Keybindings**
- `↑↓` / `Ctrl-P/N` — move
- `PgUp` / `PgDn` / `Home` / `End` — page / jump
- *letters* — live filter (session id + cwd + first message; single keyword only, since Space is reserved)
- `/` — full-text search across every session's transcript; type query + `Enter` to run, `Esc` to cancel, empty query + `Enter` to clear. Supports OR via `|` and is case-insensitive. Matched rows show the hit snippet in place of the first message
- `Backspace` / `Ctrl-U` — edit / clear filter
- `Space` — toggle mark on current row (multi-select)
- `Ctrl-X` — clear all marks
- `Del` / `Fn+Delete` — delete marked (or current) session(s) with a confirmation modal
- `Enter` — `cd` into the session's cwd and exec `claude --resume <id>`
- `Esc` — quit

### `list` — table of sessions
```bash
claude-sessions list [--limit N] [--cwd PATH] [--days N]
```
Prints a plain table (newest first). Good for chat output; cap it with `--limit` (default 30).

### `search` — full-text keyword search
```bash
claude-sessions search "<query>" [--limit N] [--cwd PATH] [-i]
```
- Substring match on user + assistant text.
- `-i` — case-insensitive
- Query supports OR via `|` — e.g. `"nextjs|remix"`.
- Each hit shows up to 3 matching snippets with timestamps.

### `show` — print a session transcript
```bash
claude-sessions show <id-or-prefix> [--max-chars N] [--with-subagents]
```
- `<id-or-prefix>` — 8+ characters is usually enough; ambiguous prefixes are rejected.
- Also matches sub-agent ids (`agent-<hex>`) stored under `<parent-id>/subagents/`.
- `--with-subagents` — after the parent transcript, append every sub-agent dispatched from this session with its `agentType` and `description`.

### `subagents` — list sub-agents of a session
```bash
claude-sessions subagents <parent-id>
```
Lists every sub-agent the parent session spawned: id, agent type, message count, last activity, description, first prompt.

### `resume` — print a `cd + claude --resume` command
```bash
claude-sessions resume <id-or-prefix> [--print-only]
```
Reads the session's original `cwd` from inside the JSONL and builds the exact shell command. `--print-only` outputs just the one-liner so it can be piped or shown to the user. Interactive resume is easier via the picker's Enter key.

### `backup` — archive old sessions into a tar.gz
```bash
claude-sessions backup [--days N] [--before YYYY-MM-DD] [--cwd PREFIX] \
                       [--out PATH] [--delete] [--force] [--dry-run] [-y]
```
- Archives sessions whose last activity is older than the cutoff (default `--days 90`).
- Output defaults to `~/.claude/backups/sessions-<timestamp>.tar.gz`.
- The archive contains each `.jsonl` plus a `manifest.json` describing the batch.
- `--delete` removes originals only after the archive succeeds; add `--force` to delete even if some files failed.
- Prompts for confirmation unless `-y`. Always run with `--dry-run` first when unsure.

### `restore` — restore sessions from a backup
```bash
claude-sessions restore <archive.tar.gz> [--cwd PREFIX] \
                        [--on-conflict skip|overwrite|rename] [--dry-run] [-y]
```
- Unpacks `projects/**/*.jsonl` back under `~/.claude/projects/`.
- `--on-conflict skip` (default) keeps existing files untouched; `overwrite` replaces them; `rename` writes the restored copy as `<id>.restored-<ts>.jsonl`.
- Reads the archive's `manifest.json` so `--cwd` can filter which sessions to restore.
- Invalidates the cache on success; next run re-indexes.

### `relocate` — rewrite a session's cwd
```bash
claude-sessions relocate <id-or-prefix> <new-cwd> \
                         [--keep-original] [--force] [--dry-run] [-y]
```
Use when Claude Code was launched in folder A but the real work happened in folder B. This rewrites the `cwd` field on every event in the JSONL **and** moves the file into B's project directory, so both `claude --resume` and `claude-sessions resume` drop the user into B.

- `--keep-original` — copy instead of move (A still has the session).
- `--force` — allow relocating even if B doesn't yet exist.
- Sub-agent transcripts (`<parent-id>/subagents/`) move along with the parent.
- Uses atomic `.tmp` → rename for safety.

### `stats` — per-project overview
```bash
claude-sessions stats [--top N]
```
Total session count, total message count, plus the busiest project directories.

## How to Use With the User

1. **Clarify scope first** for broad requests. Ask whether they want all sessions, a specific project folder, a date range, or a keyword — never dump 80+ sessions into chat.
2. **Prefer `list` / `search` inside agent workflows.** `pick` needs a real TTY — it only works when the user runs `claude-sessions` themselves in their terminal. If the user asks for interactive browsing, tell them to run `claude-sessions` directly.
3. **Run commands via Bash** with the `claude-sessions` wrapper. Keep output manageable with `--limit`, `--days`, or `--cwd` filters.
4. **Present results as a table in chat**, not raw stdout. Include the 8-char session prefix, timestamp, shortened cwd (`~/...`), message count, and the first user message or matched snippet.
5. **Confirm destructive operations.** For `backup --delete`, `restore`, and `relocate`, start with `--dry-run`, show the plan, then proceed only after the user approves. Add `-y` once confirmed so you don't stall on the interactive prompt.
6. **For resume**, remind the user they can either:
    - run `claude-sessions` in their terminal and hit `Enter` on the target row, or
    - run `claude-sessions resume <id> --print-only | bash` to execute the `cd + claude --resume` one-liner directly.

## Notes on the Data

- Each `.jsonl` file is one session; its filename (minus extension) is the session id.
- The parent directory name is the session's starting `cwd` with every non-alphanumeric character (except `-`) collapsed to `-`. `claude-sessions` reads the real `cwd` from inside the JSONL rather than decoding the directory name.
- Only `type: user` and `type: assistant` events are counted/searched. `file-history-snapshot`, `summary`, and tool-only events are ignored.
- `message.content` is a string for user messages and an array of blocks (text, tool_use, tool_result) for assistant messages; the tool concatenates text blocks only.
- Sub-agent transcripts dispatched via the `Task` tool live under `<parent-id>/subagents/agent-<hex>.jsonl` with a sibling `.meta.json` that stores `agentType` and `description`. They're excluded from top-level counts but are still searchable and viewable via `show` / `subagents`.

## Do Not

- Do not use `Read` on large `.jsonl` files directly — they are huge and noisy. Always go through `claude-sessions`.
- Do not modify or delete files under `~/.claude/projects/` with `rm` / `mv` / `tar`. Use `claude-sessions delete` (picker), `backup`, `restore`, or `relocate` — they keep the cache and sub-agent layout consistent.
- Do not run `pick` from agent tool calls (no TTY). Use `list` / `search` to gather data and present it yourself.
- Do not skip confirmation prompts on destructive commands without first showing the user what will change.
