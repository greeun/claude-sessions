#!/usr/bin/env python3
"""Browse and search local Claude Code session history.

Data source: ~/.claude/projects/<encoded-cwd>/<session-id>.jsonl
Each line of a .jsonl file is one event. We only index user/assistant messages.
"""
from __future__ import annotations

__version__ = "0.2.0"

import argparse
import json
import os
import re
import sys
import tarfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Iterator

PROJECTS_DIR = Path.home() / ".claude" / "projects"
HOME = str(Path.home())
CACHE_PATH = Path.home() / ".cache" / "claude-sessions" / "index.json"


def shorten_path(p: str) -> str:
    if p and p.startswith(HOME):
        return "~" + p[len(HOME):]
    return p or "?"


def parse_ts(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def fmt_ts(dt: datetime | None) -> str:
    if not dt:
        return "?"
    return dt.astimezone().strftime("%Y-%m-%d %H:%M")


def extract_text(content) -> str:
    """Pull plain text out of a message.content (str or list of blocks)."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                parts.append(block.get("text", ""))
            elif btype == "tool_use":
                name = block.get("name", "")
                parts.append(f"[tool_use:{name}]")
            elif btype == "tool_result":
                tr = block.get("content")
                if isinstance(tr, str):
                    parts.append(tr)
                elif isinstance(tr, list):
                    for sub in tr:
                        if isinstance(sub, dict) and sub.get("type") == "text":
                            parts.append(sub.get("text", ""))
        return "\n".join(p for p in parts if p)
    return str(content)


@dataclass
class SessionMeta:
    session_id: str
    path: Path
    cwd: str = ""
    first_ts: datetime | None = None
    last_ts: datetime | None = None
    msg_count: int = 0
    first_user_msg: str = ""
    git_branch: str = ""


def iter_jsonl(path: Path) -> Iterator[dict]:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return


def load_session_meta(path: Path, fast: bool = False) -> SessionMeta | None:
    """Read a session's metadata. `fast=True` uses mtime for last_ts and stops
    scanning once cwd + first_user_msg are known (still counts messages).
    """
    meta = SessionMeta(session_id=path.stem, path=path)
    if fast:
        try:
            meta.last_ts = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        except OSError:
            pass
    for evt in iter_jsonl(path):
        etype = evt.get("type")
        if etype not in ("user", "assistant"):
            continue
        meta.msg_count += 1
        ts = parse_ts(evt.get("timestamp"))
        if ts and not fast:
            if not meta.first_ts or ts < meta.first_ts:
                meta.first_ts = ts
            if not meta.last_ts or ts > meta.last_ts:
                meta.last_ts = ts
        elif ts and fast and not meta.first_ts:
            meta.first_ts = ts
        if not meta.cwd and evt.get("cwd"):
            meta.cwd = evt["cwd"]
        if not meta.git_branch and evt.get("gitBranch"):
            meta.git_branch = evt["gitBranch"]
        if etype == "user" and not meta.first_user_msg:
            msg = evt.get("message") or {}
            text = extract_text(msg.get("content")).strip()
            if text and not text.startswith("[tool_use:"):
                meta.first_user_msg = text
    if meta.msg_count == 0:
        return None
    return meta


def all_session_files(include_subagents: bool = False) -> list[Path]:
    """Return top-level session JSONL files.

    Subagent transcripts live under `<parent_dir>/<parent_id>/subagents/*.jsonl`;
    they're excluded by default so indexing doesn't double-count them.
    """
    if not PROJECTS_DIR.exists():
        return []
    out: list[Path] = []
    for p in PROJECTS_DIR.rglob("*.jsonl"):
        if not include_subagents and "subagents" in p.parts:
            continue
        out.append(p)
    out.sort()
    return out


def all_subagent_files() -> list[Path]:
    if not PROJECTS_DIR.exists():
        return []
    return sorted(PROJECTS_DIR.rglob("subagents/*.jsonl"))


def _load_cache() -> dict:
    try:
        with CACHE_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_cache(cache: dict) -> None:
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = CACHE_PATH.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(cache, f)
        tmp.replace(CACHE_PATH)
    except OSError:
        pass


def _meta_to_cache(m: SessionMeta) -> dict:
    return {
        "session_id": m.session_id,
        "cwd": m.cwd,
        "first_ts": m.first_ts.isoformat() if m.first_ts else None,
        "last_ts": m.last_ts.isoformat() if m.last_ts else None,
        "msg_count": m.msg_count,
        "first_user_msg": m.first_user_msg,
        "git_branch": m.git_branch,
    }


def _meta_from_cache(d: dict, path: Path) -> SessionMeta:
    return SessionMeta(
        session_id=d["session_id"],
        path=path,
        cwd=d.get("cwd", ""),
        first_ts=parse_ts(d.get("first_ts")),
        last_ts=parse_ts(d.get("last_ts")),
        msg_count=d.get("msg_count", 0),
        first_user_msg=d.get("first_user_msg", ""),
        git_branch=d.get("git_branch", ""),
    )


def load_all_sessions(
    cwd_filter: str | None = None,
    days: int | None = None,
    fast: bool = True,
    progress: bool = False,
) -> list[SessionMeta]:
    cutoff = None
    if days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    files = all_session_files()
    cache = _load_cache()
    entries = cache.setdefault("entries", {})
    dirty = False
    out: list[SessionMeta] = []
    total = len(files)
    show = progress and sys.stderr.isatty()
    miss_count = 0
    for i, p in enumerate(files, 1):
        try:
            st = p.stat()
        except OSError:
            continue
        key = str(p)
        cached = entries.get(key)
        meta: SessionMeta | None
        if cached and cached.get("mtime") == st.st_mtime and cached.get("size") == st.st_size:
            meta = _meta_from_cache(cached, p)
        else:
            miss_count += 1
            if show:
                sys.stderr.write(f"\rIndexing sessions… {i}/{total}")
                sys.stderr.flush()
            meta = load_session_meta(p, fast=fast)
            if meta:
                entries[key] = {
                    **_meta_to_cache(meta),
                    "mtime": st.st_mtime,
                    "size": st.st_size,
                }
                dirty = True
        if not meta:
            continue
        if cwd_filter and not meta.cwd.startswith(cwd_filter):
            continue
        if cutoff and (not meta.last_ts or meta.last_ts < cutoff):
            continue
        out.append(meta)
    # Prune stale cache entries
    existing_keys = {str(p) for p in files}
    stale = [k for k in entries if k not in existing_keys]
    for k in stale:
        del entries[k]
        dirty = True
    if dirty:
        _save_cache(cache)
    if show:
        sys.stderr.write("\r" + " " * 50 + "\r")
        sys.stderr.flush()
    out.sort(key=lambda m: m.last_ts or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return out


def truncate(s: str, n: int) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


# ---------- subcommands ----------

def cmd_list(args: argparse.Namespace) -> int:
    sessions = load_all_sessions(cwd_filter=args.cwd, days=args.days, progress=True)
    if args.limit:
        sessions = sessions[: args.limit]
    if not sessions:
        print("(no sessions found)")
        return 0
    print(f"claude-sessions v{__version__}")
    print(f"{'LAST ACTIVITY':<17} {'SESSION':<10} {'MSGS':>5}  CWD / FIRST MESSAGE")
    print("-" * 100)
    for s in sessions:
        sid = s.session_id[:8]
        ts = fmt_ts(s.last_ts)
        cwd = shorten_path(s.cwd)
        first = truncate(s.first_user_msg, 70) or "(no user message)"
        print(f"{ts:<17} {sid:<10} {s.msg_count:>5}  {cwd}")
        print(f"{'':17} {'':10} {'':>5}  → {first}")
    print(f"\n{len(sessions)} session(s).")
    return 0


def compile_query(q: str, case_insensitive: bool) -> re.Pattern:
    parts = [re.escape(p) for p in q.split("|")]
    pattern = "|".join(parts)
    flags = re.IGNORECASE if case_insensitive else 0
    return re.compile(pattern, flags)


def cmd_search(args: argparse.Namespace) -> int:
    regex = compile_query(args.query, args.ignore_case)
    hits: list[tuple[SessionMeta, list[tuple[datetime | None, str, str]]]] = []
    for p in all_session_files():
        meta = SessionMeta(session_id=p.stem, path=p)
        matches: list[tuple[datetime | None, str, str]] = []
        for evt in iter_jsonl(p):
            etype = evt.get("type")
            if etype not in ("user", "assistant"):
                continue
            meta.msg_count += 1
            ts = parse_ts(evt.get("timestamp"))
            if ts and (not meta.last_ts or ts > meta.last_ts):
                meta.last_ts = ts
            if not meta.cwd and evt.get("cwd"):
                meta.cwd = evt["cwd"]
            text = extract_text((evt.get("message") or {}).get("content"))
            if not text:
                continue
            m = regex.search(text)
            if m:
                start = max(0, m.start() - 40)
                end = min(len(text), m.end() + 80)
                snippet = text[start:end].replace("\n", " ")
                matches.append((ts, etype, snippet))
        if matches and (not args.cwd or meta.cwd.startswith(args.cwd)):
            hits.append((meta, matches))
    hits.sort(key=lambda h: h[0].last_ts or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    if args.limit:
        hits = hits[: args.limit]
    if not hits:
        print(f"(no matches for {args.query!r})")
        return 0
    for meta, matches in hits:
        print(f"\n● {meta.session_id[:8]}  {fmt_ts(meta.last_ts)}  {shorten_path(meta.cwd)}  ({len(matches)} hit(s))")
        for ts, role, snippet in matches[:3]:
            print(f"    [{role}] {truncate(snippet, 140)}")
        if len(matches) > 3:
            print(f"    … +{len(matches) - 3} more")
    print(f"\n{len(hits)} session(s) matched.")
    return 0


def subagents_dir(parent_path: Path) -> Path:
    """Directory that stores sub-agent transcripts for a given parent session."""
    return parent_path.parent / parent_path.stem / "subagents"


def list_subagents(parent_path: Path) -> list[tuple[Path, dict]]:
    """Return [(jsonl_path, meta_dict)] sorted by mtime (oldest first)."""
    d = subagents_dir(parent_path)
    if not d.is_dir():
        return []
    out: list[tuple[Path, dict]] = []
    for jp in sorted(d.glob("*.jsonl"), key=lambda p: p.stat().st_mtime):
        meta_path = jp.with_suffix(".meta.json")
        meta: dict = {}
        if meta_path.exists():
            try:
                with meta_path.open("r", encoding="utf-8") as f:
                    meta = json.load(f)
            except (OSError, json.JSONDecodeError):
                pass
        out.append((jp, meta))
    return out


def _print_transcript(path: Path, max_chars: int, indent: str = "") -> int:
    count = 0
    for evt in iter_jsonl(path):
        etype = evt.get("type")
        if etype not in ("user", "assistant"):
            continue
        ts = fmt_ts(parse_ts(evt.get("timestamp")))
        text = extract_text((evt.get("message") or {}).get("content")).strip()
        if not text:
            continue
        if len(text) > max_chars:
            text = text[:max_chars] + f"… (+{len(text) - max_chars} chars)"
        prefix = "🧑" if etype == "user" else "🤖"
        print(f"\n{indent}{prefix} [{ts}]")
        for line in text.splitlines() or [""]:
            print(f"{indent}{line}")
        count += 1
    return count


def cmd_show(args: argparse.Namespace) -> int:
    target = find_session(args.session_id)
    if not target:
        print(f"(no session matching {args.session_id!r})", file=sys.stderr)
        return 1
    print(f"Session:  {target.session_id}")
    print(f"Cwd:      {target.cwd}")
    print(f"Started:  {fmt_ts(target.first_ts)}")
    print(f"Last:     {fmt_ts(target.last_ts)}")
    print(f"Messages: {target.msg_count}")
    subs = list_subagents(target.path)
    if subs:
        print(f"Subagents: {len(subs)}"
              + ("  (use --with-subagents to expand)" if not args.with_subagents else ""))
    print("-" * 80)
    _print_transcript(target.path, args.max_chars)
    if args.with_subagents and subs:
        print("\n" + "=" * 80)
        print(f"  SUBAGENTS ({len(subs)})")
        print("=" * 80)
        for i, (sub_path, meta) in enumerate(subs, 1):
            agent_type = meta.get("agentType", "?")
            desc = meta.get("description", "(no description)")
            print(f"\n┌─ [{i}/{len(subs)}] {sub_path.stem}")
            print(f"│  type: {agent_type}")
            print(f"│  desc: {desc}")
            print("└" + "─" * 79)
            _print_transcript(sub_path, args.max_chars, indent="  ")
    return 0


def cmd_subagents(args: argparse.Namespace) -> int:
    target = find_session(args.session_id)
    if not target:
        print(f"(no session matching {args.session_id!r})", file=sys.stderr)
        return 1
    subs = list_subagents(target.path)
    if not subs:
        print(f"(session {target.session_id[:8]} has no subagents)")
        return 0
    print(f"Parent:   {target.session_id}")
    print(f"Cwd:      {shorten_path(target.cwd)}")
    print(f"Subagents: {len(subs)}")
    print("-" * 80)
    for i, (sub_path, meta) in enumerate(subs, 1):
        agent_type = meta.get("agentType", "?")
        desc = meta.get("description", "")
        try:
            ts = datetime.fromtimestamp(sub_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        except OSError:
            ts = "?"
        msg_count = sum(
            1 for e in iter_jsonl(sub_path) if e.get("type") in ("user", "assistant")
        )
        first_user = ""
        for e in iter_jsonl(sub_path):
            if e.get("type") == "user":
                txt = extract_text((e.get("message") or {}).get("content")).strip()
                if txt and not txt.startswith("[tool_use:"):
                    first_user = txt
                    break
        print(f"\n[{i}] {sub_path.stem}")
        print(f"    type: {agent_type}   msgs: {msg_count}   last: {ts}")
        if desc:
            print(f"    desc: {desc}")
        if first_user:
            print(f"    → {truncate(first_user, 90)}")
    print()
    print(f"Use: claude-sessions show <subagent-id> [--max-chars N]")
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    target = find_session(args.session_id)
    if not target:
        print(f"(no session matching {args.session_id!r})", file=sys.stderr)
        return 1
    cwd = target.cwd or "."
    cmd = f'cd "{cwd}" && claude --resume {target.session_id}'
    if args.print_only:
        print(cmd)
        return 0
    print(f"Session:  {target.session_id}")
    print(f"Cwd:      {cwd}")
    print(f"Last:     {fmt_ts(target.last_ts)}")
    print()
    print("Run this command to jump back into the session:")
    print()
    print(f"    {cmd}")
    print()
    print("(In Claude Code, prefix with `!` to execute it in the current session.)")
    return 0


def _tui_search_prompt(stdscr, initial: str = "") -> str | None:
    """Bottom-line editable prompt for full-text search. Returns None on Esc,
    or the (possibly empty) query on Enter."""
    import curses
    h, w = stdscr.getmaxyx()
    buf = initial
    curses.curs_set(1)
    try:
        while True:
            line = f" / {buf}"
            try:
                stdscr.addnstr(h - 1, 0, line.ljust(w - 1), w - 1,
                               curses.color_pair(2) | curses.A_BOLD)
                cx = min(w - 1, len(line))
                stdscr.move(h - 1, cx)
                stdscr.refresh()
            except curses.error:
                pass
            ch = stdscr.getch()
            if ch == 27:  # Esc — cancel
                return None
            if ch in (10, 13):  # Enter — accept (may be empty)
                return buf
            if ch in (curses.KEY_BACKSPACE, 127, 8):
                buf = buf[:-1]
            elif ch == 21:  # ^U — clear
                buf = ""
            elif 32 <= ch < 127:
                buf += chr(ch)
    finally:
        curses.curs_set(0)


def _tui_run_search(stdscr, sessions: list[SessionMeta], query: str) -> dict[str, str] | None:
    """Scan every session's JSONL for the query. Returns {session_id: snippet}
    or None if the user cancelled with Esc."""
    import curses
    regex = compile_query(query, case_insensitive=True)
    hits: dict[str, str] = {}
    h, w = stdscr.getmaxyx()
    total = len(sessions)
    stdscr.nodelay(True)
    try:
        for i, s in enumerate(sessions, 1):
            try:
                ch = stdscr.getch()
                if ch == 27:
                    return None
            except curses.error:
                pass
            if i == 1 or i == total or i % 5 == 0:
                msg = f" Searching {i}/{total}…  (Esc to cancel) "
                try:
                    stdscr.addnstr(h - 1, 0, msg.ljust(w - 1), w - 1,
                                   curses.color_pair(2) | curses.A_BOLD)
                    stdscr.refresh()
                except curses.error:
                    pass
            try:
                for evt in iter_jsonl(s.path):
                    if evt.get("type") not in ("user", "assistant"):
                        continue
                    text = extract_text((evt.get("message") or {}).get("content"))
                    if not text:
                        continue
                    m = regex.search(text)
                    if m:
                        start = max(0, m.start() - 40)
                        end = min(len(text), m.end() + 80)
                        hits[s.session_id] = text[start:end].replace("\n", " ")
                        break
            except OSError:
                continue
        return hits
    finally:
        stdscr.nodelay(False)


def _pick_ui(stdscr, sessions: list[SessionMeta]):
    import curses
    curses.curs_set(0)
    try:
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_CYAN)  # selection
        curses.init_pair(2, curses.COLOR_YELLOW, -1)  # header
        curses.init_pair(3, curses.COLOR_GREEN, -1)  # id
        curses.init_pair(4, curses.COLOR_BLUE, -1)  # cwd
        curses.init_pair(5, curses.COLOR_RED, -1)   # danger
        curses.init_pair(6, curses.COLOR_MAGENTA, -1)  # mark
    except curses.error:
        pass
    stdscr.nodelay(False)
    stdscr.keypad(True)

    query = ""
    sel = 0
    top = 0
    marked: set[str] = set()
    toast: str = ""
    search_query: str = ""
    search_hits: dict[str, str] | None = None  # None = search not active

    def filtered() -> list[SessionMeta]:
        if search_hits is not None:
            pool = [s for s in sessions if s.session_id in search_hits]
        else:
            pool = sessions
        if not query:
            return pool
        q = query.lower()
        out = []
        for s in pool:
            hay = f"{s.session_id} {s.cwd} {s.first_user_msg}".lower()
            if q in hay:
                out.append(s)
        return out

    def confirm_delete(targets: list[SessionMeta]) -> bool:
        n = len(targets)
        box_w = min(72, max(40, stdscr.getmaxyx()[1] - 6))
        preview = targets[:5]
        box_h = 7 + len(preview)
        h2, w2 = stdscr.getmaxyx()
        y0 = max(0, (h2 - box_h) // 2)
        x0 = max(0, (w2 - box_w) // 2)
        win = curses.newwin(box_h, box_w, y0, x0)
        win.keypad(True)
        try:
            win.box()
            title = f" Delete {n} session{'s' if n != 1 else ''}? "
            win.addnstr(0, max(2, (box_w - len(title)) // 2), title,
                        box_w - 4, curses.color_pair(5) | curses.A_BOLD)
            for i, s in enumerate(preview):
                label = truncate(
                    f"{s.session_id[:8]}  {shorten_path(s.cwd)}",
                    box_w - 6,
                )
                win.addnstr(2 + i, 3, f"• {label}", box_w - 6)
            if n > len(preview):
                win.addnstr(2 + len(preview), 3,
                            f"  … +{n - len(preview)} more", box_w - 6)
            msg = "This cannot be undone."
            win.addnstr(box_h - 3, 3, msg, box_w - 6,
                        curses.color_pair(5))
            prompt = " [y] Yes    [n/Esc] No "
            win.addnstr(box_h - 2, 3, prompt, box_w - 6, curses.A_BOLD)
            win.refresh()
            while True:
                k = win.getch()
                if k in (ord("y"), ord("Y")):
                    return True
                if k in (ord("n"), ord("N"), 27, 10, 13):
                    return False
        finally:
            del win
            stdscr.touchwin()
            stdscr.refresh()

    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        items = filtered()
        if sel >= len(items):
            sel = max(0, len(items) - 1)
        if sel < top:
            top = sel

        mark_hint = f"  ✓{len(marked)}" if marked else ""
        search_hint = (
            f"  🔎 {search_query!r}→{len(search_hits)}"
            if search_hits is not None else ""
        )
        header = (f" claude-sessions v{__version__}  {len(items)}/{len(sessions)}{mark_hint}{search_hint}"
                  "   ↑↓ move  Enter open  Space mark  / search  Del delete  Esc quit ")
        col_header = f"   {'LAST ACTIVITY':<16}  {'SESSION':<8}  {'MSGS':>6}  MESSAGE"
        try:
            stdscr.addnstr(0, 0, header.ljust(w), w, curses.color_pair(2) | curses.A_BOLD)
            prompt = f"> {query}"
            stdscr.addnstr(1, 0, prompt.ljust(w), w, curses.A_BOLD)
            stdscr.addnstr(2, 0, col_header.ljust(w - 1), w - 1,
                           curses.A_DIM | curses.A_UNDERLINE)
        except curses.error:
            pass

        list_top = 3
        list_h = max(1, h - list_top - 1)
        if sel >= top + list_h:
            top = sel - list_h + 1

        for i in range(list_h):
            idx = top + i
            if idx >= len(items):
                break
            s = items[idx]
            ts = fmt_ts(s.last_ts)
            sid = s.session_id[:8]
            is_sel = idx == sel
            is_marked = s.session_id in marked
            mark = "●" if is_marked else " "
            if search_hits is not None and s.session_id in search_hits:
                tail_raw = search_hits[s.session_id]
            else:
                tail_raw = s.first_user_msg or "(no user msg)"
            tail = truncate(tail_raw, max(20, w - 38))
            line = f" {mark} {ts}  {sid}  [{s.msg_count:>4}]  {tail}"
            if is_sel:
                attr = curses.color_pair(1)
            elif is_marked:
                attr = curses.color_pair(6) | curses.A_BOLD
            else:
                attr = curses.A_NORMAL
            try:
                stdscr.addnstr(list_top + i, 0, line.ljust(w), w, attr)
            except curses.error:
                pass

        # status line: cwd of the selected item, or a transient toast.
        if toast:
            try:
                stdscr.addnstr(h - 1, 0, f" {toast} ".ljust(w - 1), w - 1,
                               curses.color_pair(5) | curses.A_BOLD)
            except curses.error:
                pass
            toast = ""
        elif items:
            s = items[sel]
            info = f" 📁  {shorten_path(s.cwd)}"
            try:
                stdscr.addnstr(h - 1, 0, info.ljust(w - 1), w - 1, curses.A_DIM)
            except curses.error:
                pass
        else:
            try:
                stdscr.addnstr(h - 1, 0, " (no matches) ", w - 1, curses.A_DIM)
            except curses.error:
                pass

        stdscr.refresh()
        ch = stdscr.getch()

        if ch in (curses.KEY_UP, 16):  # ^P
            sel = max(0, sel - 1)
        elif ch in (curses.KEY_DOWN, 14):  # ^N
            sel = min(max(0, len(items) - 1), sel + 1)
        elif ch == curses.KEY_NPAGE:
            sel = min(max(0, len(items) - 1), sel + list_h)
        elif ch == curses.KEY_PPAGE:
            sel = max(0, sel - list_h)
        elif ch == curses.KEY_HOME:
            sel = 0
        elif ch == curses.KEY_END:
            sel = max(0, len(items) - 1)
        elif ch in (10, 13):  # Enter
            if items:
                return items[sel]
        elif ch == 27:  # Esc
            return None
        elif ch == 32:  # Space — toggle mark on current row
            if items:
                sid = items[sel].session_id
                if sid in marked:
                    marked.discard(sid)
                else:
                    marked.add(sid)
                if sel < len(items) - 1:
                    sel += 1
        elif ch in (curses.KEY_DC, 330):  # Delete / Fn+Delete — delete flow
            targets: list[SessionMeta]
            if marked:
                targets = [s for s in sessions if s.session_id in marked]
            elif items:
                targets = [items[sel]]
            else:
                targets = []
            if targets and confirm_delete(targets):
                deleted = 0
                errors = 0
                cache = _load_cache()
                entries = cache.setdefault("entries", {})
                for s in targets:
                    try:
                        s.path.unlink()
                        entries.pop(str(s.path), None)
                        deleted += 1
                    except OSError:
                        errors += 1
                _save_cache(cache)
                dead_ids = {s.session_id for s in targets}
                sessions[:] = [s for s in sessions if s.session_id not in dead_ids]
                marked -= dead_ids
                sel = max(0, min(sel, len(filtered()) - 1))
                top = max(0, min(top, max(0, len(filtered()) - 1)))
                toast = f"Deleted {deleted} session(s)" + (f", {errors} failed" if errors else "")
        elif ch in (curses.KEY_BACKSPACE, 127, 8):
            query = query[:-1]
            sel = 0
            top = 0
        elif ch == 21:  # ^U — clear query
            query = ""
            sel = 0
            top = 0
        elif ch == 24:  # ^X — clear all marks
            marked.clear()
        elif ch == ord('/'):  # full-text search across all session transcripts
            q = _tui_search_prompt(stdscr, initial=search_query)
            if q is None:
                pass  # cancelled — keep previous search state
            elif q == "":
                search_query = ""
                search_hits = None
                sel = 0
                top = 0
                toast = "Search cleared"
            else:
                result = _tui_run_search(stdscr, sessions, q)
                if result is None:
                    toast = "Search cancelled"
                else:
                    search_query = q
                    search_hits = result
                    sel = 0
                    top = 0
                    toast = f"Search: {len(result)} session(s) matched"
        elif 33 <= ch < 127:  # printable (excluding space, which is mark)
            query += chr(ch)
            sel = 0
            top = 0


def cmd_pick(args: argparse.Namespace) -> int:
    import curses
    print("Loading sessions…", file=sys.stderr, end="", flush=True)
    sessions = load_all_sessions(
        cwd_filter=args.cwd,
        days=args.days,
        progress=True,
    )
    if not sessions:
        print("\r(no sessions found)            ")
        return 0
    try:
        selected = curses.wrapper(_pick_ui, sessions)
    except KeyboardInterrupt:
        return 0
    if not selected:
        return 0
    cwd = selected.cwd or "."
    sid = selected.session_id
    print(f"→ cd {shorten_path(cwd)} && claude --resume {sid[:8]}…")
    if not os.path.isdir(cwd):
        print(f"(cwd no longer exists: {cwd})", file=sys.stderr)
        return 1
    try:
        os.chdir(cwd)
    except OSError as e:
        print(f"Cannot cd to {cwd}: {e}", file=sys.stderr)
        return 1
    try:
        os.execvp("claude", ["claude", "--resume", sid])
    except FileNotFoundError:
        print("`claude` not found on PATH.", file=sys.stderr)
        return 1


def encode_cwd(cwd: str) -> str:
    """Mirror Claude Code's directory naming for project folders.

    Any character that isn't [A-Za-z0-9-] becomes '-'. So `/` and `.` both
    collapse to dashes. Example:
      /Users/me/.claude/skills  →  -Users-me--claude-skills
    """
    return re.sub(r"[^A-Za-z0-9\-]", "-", cwd)


def cmd_relocate(args: argparse.Namespace) -> int:
    """Rewrite a session's recorded cwd to a different folder.

    Useful when Claude Code was launched in folder A but the actual work
    happened in folder B — this moves the session JSONL to B's project
    directory and rewrites the `cwd` field on every event, so `resume` and
    `claude --resume` both jump into B.
    """
    target = find_session(args.session_id)
    if not target:
        print(f"(no session matching {args.session_id!r})", file=sys.stderr)
        return 1
    new_cwd = str(Path(args.new_cwd).expanduser())
    if not new_cwd.startswith("/"):
        new_cwd = str(Path(new_cwd).resolve())

    if not args.force and not Path(new_cwd).is_dir():
        print(f"Target folder does not exist: {new_cwd}\n"
              f"(use --force to relocate anyway)", file=sys.stderr)
        return 1

    if new_cwd == target.cwd:
        print(f"Session already has cwd={new_cwd} — nothing to do.")
        return 0

    new_project_dir = PROJECTS_DIR / encode_cwd(new_cwd)
    new_path = new_project_dir / target.path.name

    if new_path.exists():
        print(f"Target path already exists: {new_path}\n"
              f"(a session with the same id lives there — refusing to overwrite)",
              file=sys.stderr)
        return 1

    old_subdir = target.path.parent / target.path.stem  # subagents live here
    new_subdir = new_project_dir / target.path.stem

    print(f"Session:  {target.session_id}")
    print(f"From cwd: {shorten_path(target.cwd)}")
    print(f"To   cwd: {shorten_path(new_cwd)}")
    print(f"File:     {shorten_path(str(target.path))}")
    print(f"     →    {shorten_path(str(new_path))}")
    if old_subdir.is_dir():
        print(f"Subagents: {shorten_path(str(old_subdir))}")
        print(f"      →    {shorten_path(str(new_subdir))}")
    if args.keep_original:
        print("Mode:     copy (originals will be kept)")
    else:
        print("Mode:     move")

    if args.dry_run:
        print("(dry run — nothing changed)")
        return 0

    if not args.yes:
        reply = input("Proceed? [y/N] ").strip().lower()
        if reply not in ("y", "yes"):
            print("Aborted.")
            return 0

    # Rewrite the JSONL with updated cwd on each event
    new_project_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = new_path.with_suffix(".jsonl.tmp")
    rewritten = 0
    try:
        with target.path.open("r", encoding="utf-8", errors="replace") as src, \
             tmp_path.open("w", encoding="utf-8") as dst:
            for line in src:
                stripped = line.strip()
                if not stripped:
                    dst.write(line)
                    continue
                try:
                    evt = json.loads(stripped)
                except json.JSONDecodeError:
                    dst.write(line)
                    continue
                if "cwd" in evt:
                    evt["cwd"] = new_cwd
                    rewritten += 1
                dst.write(json.dumps(evt, ensure_ascii=False) + "\n")
        tmp_path.replace(new_path)
    except OSError as e:
        print(f"Failed to write new session file: {e}", file=sys.stderr)
        tmp_path.unlink(missing_ok=True)
        return 1

    # Move (or copy) the subagents directory if it exists
    sub_moved = False
    if old_subdir.is_dir():
        try:
            if args.keep_original:
                import shutil
                shutil.copytree(old_subdir, new_subdir)
            else:
                new_subdir.parent.mkdir(parents=True, exist_ok=True)
                old_subdir.rename(new_subdir)
            sub_moved = True
            # Rewrite cwd inside each subagent JSONL too
            if new_subdir.is_dir():
                for sub_jsonl in new_subdir.glob("subagents/*.jsonl"):
                    _rewrite_cwd_inplace(sub_jsonl, new_cwd)
        except OSError as e:
            print(f"Warning: could not relocate subagents dir: {e}", file=sys.stderr)

    if not args.keep_original:
        try:
            target.path.unlink()
        except OSError as e:
            print(f"Warning: failed to remove original {target.path}: {e}", file=sys.stderr)

    # Invalidate cache (next run re-indexes the new path)
    try:
        CACHE_PATH.unlink()
    except OSError:
        pass

    print(f"✓ Relocated session (rewrote cwd on {rewritten} event(s))"
          + (", subagents moved" if sub_moved else ""))
    return 0


def _rewrite_cwd_inplace(path: Path, new_cwd: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with path.open("r", encoding="utf-8", errors="replace") as src, \
             tmp.open("w", encoding="utf-8") as dst:
            for line in src:
                stripped = line.strip()
                if not stripped:
                    dst.write(line)
                    continue
                try:
                    evt = json.loads(stripped)
                except json.JSONDecodeError:
                    dst.write(line)
                    continue
                if "cwd" in evt:
                    evt["cwd"] = new_cwd
                dst.write(json.dumps(evt, ensure_ascii=False) + "\n")
        tmp.replace(path)
    except OSError:
        tmp.unlink(missing_ok=True)


def cmd_backup(args: argparse.Namespace) -> int:
    """Archive sessions older than a cutoff into a single tar.gz.

    Selects sessions whose last activity is older than --days (or --before),
    writes them to a tar.gz (default under ~/.claude/backups/), and optionally
    removes the originals with --delete.
    """
    # Determine cutoff
    cutoff: datetime
    if args.before:
        try:
            cutoff = datetime.strptime(args.before, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            print(f"--before must be YYYY-MM-DD (got {args.before!r})", file=sys.stderr)
            return 2
    else:
        days = args.days if args.days is not None else 90
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    sessions = load_all_sessions(progress=True)
    old = [s for s in sessions if s.last_ts and s.last_ts < cutoff]
    if args.cwd:
        old = [s for s in old if s.cwd.startswith(args.cwd)]

    if not old:
        print(f"(no sessions older than {cutoff.astimezone().strftime('%Y-%m-%d')})")
        return 0

    total_bytes = 0
    for s in old:
        try:
            total_bytes += s.path.stat().st_size
        except OSError:
            pass

    def human(n: int) -> str:
        for unit in ("B", "KB", "MB", "GB"):
            if n < 1024:
                return f"{n:.1f}{unit}" if unit != "B" else f"{n}{unit}"
            n /= 1024
        return f"{n:.1f}TB"

    cutoff_label = cutoff.astimezone().strftime("%Y-%m-%d")
    print(f"Sessions older than {cutoff_label}: {len(old)} ({human(total_bytes)})")

    if args.dry_run:
        for s in old[:20]:
            print(f"  {s.session_id[:8]}  {fmt_ts(s.last_ts):<17}  {shorten_path(s.cwd)}")
        if len(old) > 20:
            print(f"  … +{len(old) - 20} more")
        print("(dry run — nothing written)")
        return 0

    # Output path
    if args.out:
        out_path = Path(args.out).expanduser()
    else:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        out_path = Path.home() / ".claude" / "backups" / f"sessions-{stamp}.tar.gz"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not args.yes:
        action = "archive and DELETE" if args.delete else "archive"
        print(f"Will {action} {len(old)} session(s) → {shorten_path(str(out_path))}")
        reply = input("Proceed? [y/N] ").strip().lower()
        if reply not in ("y", "yes"):
            print("Aborted.")
            return 0

    # Build manifest + tar
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "cutoff": cutoff.isoformat(),
        "count": len(old),
        "sessions": [
            {
                "session_id": s.session_id,
                "cwd": s.cwd,
                "first_ts": s.first_ts.isoformat() if s.first_ts else None,
                "last_ts": s.last_ts.isoformat() if s.last_ts else None,
                "msg_count": s.msg_count,
                "first_user_msg": s.first_user_msg,
                "relpath": str(s.path.relative_to(PROJECTS_DIR)),
            }
            for s in old
        ],
    }
    projects_parent = PROJECTS_DIR.parent  # ~/.claude
    written = 0
    failed: list[str] = []
    try:
        with tarfile.open(out_path, "w:gz") as tar:
            mf_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
            mf_info = tarfile.TarInfo(name="manifest.json")
            mf_info.size = len(mf_bytes)
            mf_info.mtime = int(datetime.now().timestamp())
            import io
            tar.addfile(mf_info, io.BytesIO(mf_bytes))
            for i, s in enumerate(old, 1):
                try:
                    arcname = f"projects/{s.path.relative_to(PROJECTS_DIR)}"
                    tar.add(str(s.path), arcname=arcname)
                    written += 1
                except OSError as e:
                    failed.append(f"{s.session_id}: {e}")
                if sys.stderr.isatty():
                    sys.stderr.write(f"\rArchiving… {i}/{len(old)}")
                    sys.stderr.flush()
        if sys.stderr.isatty():
            sys.stderr.write("\r" + " " * 40 + "\r")
    except OSError as e:
        print(f"Backup failed: {e}", file=sys.stderr)
        return 1

    archive_size = out_path.stat().st_size
    print(f"✓ Wrote {written}/{len(old)} sessions → {shorten_path(str(out_path))} ({human(archive_size)})")
    if failed:
        print(f"  {len(failed)} file(s) failed to archive", file=sys.stderr)
        for f in failed[:5]:
            print(f"    {f}", file=sys.stderr)

    if args.delete:
        if failed and not args.force:
            print("Refusing to delete originals because some files failed to archive (use --force to override).",
                  file=sys.stderr)
            return 1
        cache = _load_cache()
        entries = cache.setdefault("entries", {})
        deleted = 0
        for s in old:
            # Only delete the ones we actually archived
            if f"{s.session_id}" in {t.split(":")[0] for t in failed}:
                continue
            try:
                s.path.unlink()
                entries.pop(str(s.path), None)
                deleted += 1
            except OSError as e:
                print(f"  Could not remove {s.path}: {e}", file=sys.stderr)
        _save_cache(cache)
        print(f"✓ Removed {deleted} original session file(s).")

    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    """Restore sessions from a backup tar.gz created by `backup`.

    Extracts `projects/**/*.jsonl` members back under ~/.claude/projects/,
    handling existing-file conflicts via --on-conflict.
    """
    archive = Path(args.archive).expanduser()
    if not archive.exists():
        print(f"Archive not found: {archive}", file=sys.stderr)
        return 1

    try:
        tar = tarfile.open(archive, "r:*")
    except tarfile.TarError as e:
        print(f"Cannot open archive: {e}", file=sys.stderr)
        return 1

    manifest: dict | None = None
    members: list[tarfile.TarInfo] = []
    try:
        for m in tar.getmembers():
            if not m.isfile():
                continue
            if m.name == "manifest.json":
                try:
                    f = tar.extractfile(m)
                    if f is not None:
                        manifest = json.loads(f.read().decode("utf-8"))
                except Exception:
                    pass
                continue
            if m.name.startswith("projects/") and m.name.endswith(".jsonl"):
                members.append(m)

        if not members:
            print("(archive contains no session files)")
            return 0

        # Filter by cwd prefix if requested (uses manifest when available)
        cwd_filter = args.cwd
        manifest_by_rel: dict[str, dict] = {}
        if manifest:
            for entry in manifest.get("sessions", []):
                rel = entry.get("relpath")
                if rel:
                    manifest_by_rel[rel] = entry

        if cwd_filter:
            kept = []
            for m in members:
                rel = m.name[len("projects/"):]
                meta = manifest_by_rel.get(rel)
                meta_cwd = (meta or {}).get("cwd", "")
                if meta_cwd.startswith(cwd_filter):
                    kept.append(m)
            members = kept

        total_bytes = sum(m.size for m in members)

        def human(n: int) -> str:
            nf = float(n)
            for unit in ("B", "KB", "MB", "GB"):
                if nf < 1024:
                    return f"{nf:.1f}{unit}" if unit != "B" else f"{int(nf)}{unit}"
                nf /= 1024
            return f"{nf:.1f}TB"

        print(f"Archive: {shorten_path(str(archive))}")
        if manifest:
            print(f"Created: {manifest.get('created_at', '?')}")
            print(f"Cutoff:  {manifest.get('cutoff', '?')}")
        print(f"Files:   {len(members)} ({human(total_bytes)})")

        # Decide destinations and conflict resolution
        dest_root = PROJECTS_DIR
        conflicts: list[tuple[tarfile.TarInfo, Path]] = []
        plans: list[tuple[tarfile.TarInfo, Path, str]] = []  # (member, dest_path, action)
        for m in members:
            rel = m.name[len("projects/"):]
            dest = dest_root / rel
            action = "write"
            if dest.exists():
                if args.on_conflict == "skip":
                    action = "skip"
                elif args.on_conflict == "overwrite":
                    action = "overwrite"
                elif args.on_conflict == "rename":
                    action = "rename"
                conflicts.append((m, dest))
            plans.append((m, dest, action))

        if conflicts:
            print(f"Conflicts: {len(conflicts)} existing file(s)  → policy: {args.on_conflict}")

        if args.dry_run:
            print("\nPlan (dry run):")
            counts = {"write": 0, "skip": 0, "overwrite": 0, "rename": 0}
            for m, dest, action in plans[:20]:
                rel = m.name[len("projects/"):]
                meta = manifest_by_rel.get(rel, {})
                label = meta.get("first_user_msg") or rel
                print(f"  [{action:<9}] {truncate(label, 80)}")
                counts[action] = counts.get(action, 0) + 1
            if len(plans) > 20:
                print(f"  … +{len(plans) - 20} more")
            summary = ", ".join(f"{k}:{v}" for k, v in counts.items() if v)
            print(f"\n({summary}) — nothing written")
            return 0

        if not args.yes:
            reply = input(f"Restore {len(plans)} file(s) to {shorten_path(str(dest_root))}? [y/N] ").strip().lower()
            if reply not in ("y", "yes"):
                print("Aborted.")
                return 0

        written = 0
        skipped = 0
        errors = 0
        for i, (m, dest, action) in enumerate(plans, 1):
            if action == "skip":
                skipped += 1
                continue
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                if action == "rename" and dest.exists():
                    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
                    dest = dest.with_suffix(f".restored-{stamp}.jsonl")
                src = tar.extractfile(m)
                if src is None:
                    errors += 1
                    continue
                with open(dest, "wb") as out:
                    while True:
                        chunk = src.read(65536)
                        if not chunk:
                            break
                        out.write(chunk)
                written += 1
            except OSError as e:
                errors += 1
                print(f"  Failed {m.name}: {e}", file=sys.stderr)
            if sys.stderr.isatty():
                sys.stderr.write(f"\rRestoring… {i}/{len(plans)}")
                sys.stderr.flush()
        if sys.stderr.isatty():
            sys.stderr.write("\r" + " " * 40 + "\r")

        # Invalidate the cache so next list/pick re-indexes restored files
        try:
            CACHE_PATH.unlink()
        except OSError:
            pass

        print(f"✓ Restored {written} file(s)" +
              (f", skipped {skipped}" if skipped else "") +
              (f", {errors} error(s)" if errors else ""))
        return 1 if errors else 0
    finally:
        tar.close()


def cmd_stats(args: argparse.Namespace) -> int:
    sessions = load_all_sessions()
    total_msgs = sum(s.msg_count for s in sessions)
    print(f"Total sessions: {len(sessions)}")
    print(f"Total messages: {total_msgs}")
    if not sessions:
        return 0
    by_cwd: dict[str, tuple[int, int, datetime | None]] = {}
    for s in sessions:
        count, msgs, last = by_cwd.get(s.cwd, (0, 0, None))
        if not last or (s.last_ts and s.last_ts > last):
            last = s.last_ts
        by_cwd[s.cwd] = (count + 1, msgs + s.msg_count, last)
    rows = sorted(by_cwd.items(), key=lambda kv: kv[1][0], reverse=True)
    print(f"\n{'SESSIONS':>8} {'MSGS':>7}  {'LAST':<17}  PROJECT")
    print("-" * 90)
    for cwd, (n, msgs, last) in rows[: args.top]:
        print(f"{n:>8} {msgs:>7}  {fmt_ts(last):<17}  {shorten_path(cwd)}")
    return 0


def find_session(prefix: str) -> SessionMeta | None:
    """Find a session by id prefix, searching both top-level and subagent files."""
    matches: list[Path] = []
    for p in all_session_files():
        if p.stem.startswith(prefix):
            matches.append(p)
    if not matches:
        for p in all_subagent_files():
            if p.stem.startswith(prefix):
                matches.append(p)
    if not matches:
        return None
    if len(matches) > 1:
        print(f"Ambiguous id {prefix!r} — {len(matches)} matches:", file=sys.stderr)
        for m in matches[:10]:
            print(f"  {m.stem}", file=sys.stderr)
        return None
    return load_session_meta(matches[0])


def main() -> int:
    ap = argparse.ArgumentParser(
        description=f"Browse local Claude Code session history (v{__version__})",
    )
    ap.add_argument("-V", "--version", action="version",
                    version=f"claude-sessions v{__version__}")
    sub = ap.add_subparsers(dest="cmd")

    p_pick = sub.add_parser("pick", help="interactive picker (default) — arrow keys + Enter to resume")
    p_pick.add_argument("--cwd", type=str, default=None, help="filter by cwd prefix")
    p_pick.add_argument("--days", type=int, default=None, help="only last N days")
    p_pick.set_defaults(func=cmd_pick)

    p_list = sub.add_parser("list", help="list sessions")
    p_list.add_argument("--limit", type=int, default=30)
    p_list.add_argument("--cwd", type=str, default=None, help="filter by cwd prefix")
    p_list.add_argument("--days", type=int, default=None, help="only last N days")
    p_list.set_defaults(func=cmd_list)

    p_search = sub.add_parser("search", help="keyword search across sessions")
    p_search.add_argument("query")
    p_search.add_argument("--limit", type=int, default=20)
    p_search.add_argument("--cwd", type=str, default=None)
    p_search.add_argument("-i", "--ignore-case", action="store_true")
    p_search.set_defaults(func=cmd_search)

    p_show = sub.add_parser("show", help="print a session transcript")
    p_show.add_argument("session_id")
    p_show.add_argument("--max-chars", type=int, default=500)
    p_show.add_argument("--with-subagents", action="store_true",
                        help="also print transcripts of every subagent dispatched from this session")
    p_show.set_defaults(func=cmd_show)

    p_sub = sub.add_parser("subagents", help="list subagents dispatched from a session")
    p_sub.add_argument("session_id")
    p_sub.set_defaults(func=cmd_subagents)

    p_reloc = sub.add_parser("relocate",
                             help="rewrite a session's recorded cwd to a different folder")
    p_reloc.add_argument("session_id")
    p_reloc.add_argument("new_cwd", help="absolute path of the folder the session should belong to")
    p_reloc.add_argument("--keep-original", action="store_true",
                         help="copy instead of moving (leaves the old file in place)")
    p_reloc.add_argument("--force", action="store_true",
                         help="proceed even if the target folder does not exist")
    p_reloc.add_argument("--dry-run", action="store_true")
    p_reloc.add_argument("-y", "--yes", action="store_true")
    p_reloc.set_defaults(func=cmd_relocate)

    p_resume = sub.add_parser("resume", help="emit a cd+resume command for a session")
    p_resume.add_argument("session_id")
    p_resume.add_argument("--print-only", action="store_true", help="print just the shell command")
    p_resume.set_defaults(func=cmd_resume)

    p_backup = sub.add_parser("backup", help="archive old sessions into a tar.gz")
    p_backup.add_argument("--days", type=int, default=None,
                          help="backup sessions older than N days (default 90)")
    p_backup.add_argument("--before", type=str, default=None,
                          help="backup sessions older than YYYY-MM-DD")
    p_backup.add_argument("--cwd", type=str, default=None,
                          help="only sessions whose cwd starts with this prefix")
    p_backup.add_argument("--out", type=str, default=None,
                          help="output archive path (default ~/.claude/backups/sessions-<ts>.tar.gz)")
    p_backup.add_argument("--delete", action="store_true",
                          help="remove original session files after successful archive")
    p_backup.add_argument("--force", action="store_true",
                          help="delete originals even if some files failed to archive")
    p_backup.add_argument("--dry-run", action="store_true",
                          help="show what would be archived without writing anything")
    p_backup.add_argument("-y", "--yes", action="store_true",
                          help="skip confirmation prompt")
    p_backup.set_defaults(func=cmd_backup)

    p_restore = sub.add_parser("restore", help="restore sessions from a backup tar.gz")
    p_restore.add_argument("archive", help="path to tar.gz created by `backup`")
    p_restore.add_argument("--cwd", type=str, default=None,
                           help="only restore sessions whose original cwd starts with this prefix")
    p_restore.add_argument("--on-conflict", choices=("skip", "overwrite", "rename"),
                           default="skip",
                           help="what to do when a target file already exists (default: skip)")
    p_restore.add_argument("--dry-run", action="store_true",
                           help="show the restore plan without writing files")
    p_restore.add_argument("-y", "--yes", action="store_true",
                           help="skip confirmation prompt")
    p_restore.set_defaults(func=cmd_restore)

    p_stats = sub.add_parser("stats", help="summary stats across all sessions")
    p_stats.add_argument("--top", type=int, default=15)
    p_stats.set_defaults(func=cmd_stats)

    args = ap.parse_args()
    if not getattr(args, "cmd", None):
        # Default: interactive picker
        ns = argparse.Namespace(cwd=None, days=None, func=cmd_pick)
        return cmd_pick(ns)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
