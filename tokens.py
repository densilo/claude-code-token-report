#!/usr/bin/env python3
"""Where did my coding agent's tokens go?

Reads the Claude Code and Codex sessions already recorded on this machine
(~/.claude/projects and ~/.codex/sessions) and prints what the agent sent to
the model, and what it kept sending again. Offline: nothing is uploaded, no
model is called, no account is needed, and nothing is written to disk. Only
totals and percentages are printed, never file names or session contents.

    curl -fsSL https://densilo.com/tokens.py | python3 -
    curl -fsSL https://densilo.com/tokens.py | python3 - --days 30

Python 3.8+, standard library only. Made by Densilo (https://densilo.com).
"""
import argparse
import collections
import json
import os
import re
import sys
import time
from pathlib import Path

IMAGE_CHARS = 1600 * 4   # an image costs about 1,600 tokens whatever its file size; ~4 chars a token
TOP = 6


def size(value):
    """Rough size of a piece of content, in characters."""
    if isinstance(value, str):
        return len(value)
    if isinstance(value, list):
        return sum(size(v) for v in value)
    if isinstance(value, dict):
        if value.get("type") in ("image", "input_image"):
            return IMAGE_CHARS
        if "text" in value and len(value) <= 3:
            return size(value["text"])
        if "content" in value and value.get("type") == "tool_result":
            return size(value["content"])
    return len(json.dumps(value)) if value is not None else 0


def claude_kind(name):
    if name in ("Read", "NotebookRead"):
        return "file reads"
    if name == "Bash":
        return "command output"
    if name in ("Grep", "Glob", "LS"):
        return "searches and listings"
    if name in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        return "edit results"
    if name in ("Task", "Agent"):
        return "subagent reports"
    if name.startswith("mcp__") and ("chrome" in name or "browser" in name or "playwright" in name):
        return "browser pages and screenshots"
    if name.startswith("mcp__"):
        return "MCP tool output"
    if name in ("WebFetch", "WebSearch"):
        return "web pages"
    return "other tool output"


class Session:
    def __init__(self):
        self.items = []          # (kind, chars) in order; "#req" marks a model request, "#compact" a compaction
        self.sent = 0            # input tokens the provider counted, all requests
        self.cached = 0          # of which re-sent history served from cache
        self.output = 0
        self.reads = collections.Counter()
        self.read_chars = [0, 0]  # all file-read output, and the part that re-read a file already read

    def read(self, path, chars):
        self.reads[path] += 1
        self.read_chars[0] += chars
        if self.reads[path] > 1:
            self.read_chars[1] += chars


def lines(path):
    try:
        with open(path, encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                try:
                    yield json.loads(line)
                except ValueError:
                    continue
    except OSError:
        return


def parse_claude(path):
    s, names, seen = Session(), {}, set()
    for e in lines(path):
        if not isinstance(e, dict):
            continue
        if e.get("isCompactSummary") or (e.get("type") == "system" and e.get("subtype") == "compact_boundary"):
            s.items.append(("#compact", 0))
            continue
        m = e.get("message") if isinstance(e.get("message"), dict) else {}
        if e.get("type") == "assistant":
            rid = m.get("id")
            if rid and rid not in seen:
                seen.add(rid)
                s.items.append(("#req", 0))
                u = m.get("usage") or {}
                cached = u.get("cache_read_input_tokens") or 0
                s.cached += cached
                s.sent += cached + (u.get("cache_creation_input_tokens") or 0) + (u.get("input_tokens") or 0)
                s.output += u.get("output_tokens") or 0
            for b in m.get("content") or []:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_use":
                    name = b.get("name") or ""
                    names[b.get("id")] = (name, (b.get("input") or {}).get("file_path") if name == "Read" else None)
                    kind = "code the agent wrote" if name in ("Edit", "Write", "MultiEdit", "NotebookEdit") \
                        else "tool calls the agent made"
                    s.items.append((kind, size(b.get("input"))))
                elif b.get("type") == "text":
                    s.items.append(("the agent's replies", size(b.get("text"))))
        elif e.get("type") == "user":
            c = m.get("content")
            if isinstance(c, str):
                s.items.append(("your messages", len(c)))
                continue
            for b in c or []:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_result":
                    name, file_path = names.get(b.get("tool_use_id"), ("", None))
                    chars = size(b.get("content"))
                    s.items.append((claude_kind(name), chars))
                    if file_path:
                        s.read(file_path, chars)
                elif b.get("type") == "text":
                    s.items.append(("your messages", size(b.get("text"))))
                elif b.get("type") == "image":
                    s.items.append(("your messages", IMAGE_CHARS))
    return s


READ_CMD = re.compile(r"(?:sed -n|cat|nl -ba|head|tail|less)\b[^\"\\|;&]*?\s([\w./-]+\.\w+)")


def parse_codex(path):
    s, calls, last = Session(), {}, None
    for e in lines(path):
        if not isinstance(e, dict):
            continue
        t, p = e.get("type"), e.get("payload") if isinstance(e.get("payload"), dict) else {}
        if t == "compacted":
            s.items.append(("#compact", 0))
            continue
        if t == "event_msg" and p.get("type") == "token_count" and isinstance(p.get("info"), dict):
            u = p["info"].get("last_token_usage") or {}
            if u and u != last:
                last = u
                s.items.append(("#req", 0))
                s.sent += u.get("input_tokens") or 0
                s.cached += u.get("cached_input_tokens") or 0
                s.output += u.get("output_tokens") or 0
            continue
        if t != "response_item":
            continue
        kind = p.get("type")
        if kind == "message":
            text = json.dumps(p.get("content"))[:400]
            if p.get("role") == "user":
                setup = re.search(r"<user_instructions>|<environment_context>|AGENTS\.md|<permissions instructions>", text)
                s.items.append(("agent instructions" if setup else "your messages", size(p.get("content"))))
            elif p.get("role") == "assistant":
                s.items.append(("the agent's replies", size(p.get("content"))))
            else:
                s.items.append(("agent instructions", size(p.get("content"))))
        elif kind in ("function_call", "custom_tool_call", "local_shell_call"):
            args = p.get("arguments") or p.get("input") or p.get("action") or ""
            text = args if isinstance(args, str) else json.dumps(args)
            patch = p.get("name") == "apply_patch" or "apply_patch" in text[:200]
            m = None if patch else READ_CMD.search(text)
            calls[p.get("call_id")] = ("patch" if patch else None, m.group(1) if m else None)
            s.items.append(("code the agent wrote" if patch else "tool calls the agent made", size(args)))
        elif kind in ("function_call_output", "custom_tool_call_output"):
            what, file_path = calls.get(p.get("call_id"), (None, None))
            chars = size(p.get("output"))
            if what == "patch":
                s.items.append(("edit results", chars))
            elif file_path:
                s.items.append(("file reads", chars))
                s.read(file_path, chars)
            else:
                s.items.append(("command output", chars))
    return s


def resent(sessions):
    """Characters of each kind, times the number of later requests that carried
    them again (until a compaction cleared them)."""
    weight = collections.Counter()
    for s in sessions:
        pending = []
        for kind, chars in s.items:
            if kind == "#req":
                for k, c in pending:
                    weight[k] += c
            elif kind == "#compact":
                pending = []
            else:
                pending.append((kind, chars))
    return weight


def recent(root, pattern, since):
    if not root.is_dir():
        return []
    out = []
    for p in root.glob(pattern):
        try:
            if p.stat().st_mtime >= since:
                out.append(p)
        except OSError:
            continue
    return out


def pct(part, whole):
    return f"{100 * part / whole:.0f}%" if whole else "0%"


def tokens(n):
    for unit, size_ in (("B", 1e9), ("M", 1e6), ("k", 1e3)):
        if n >= size_:
            return f"{n / size_:.1f}{unit}".replace(".0", "")
    return str(int(n))


def report(name, sessions, days):
    sessions = [s for s in sessions if s.sent]
    if not sessions:
        return None, []
    sent = sum(s.sent for s in sessions)
    cached = sum(s.cached for s in sessions)
    output = sum(s.output for s in sessions)
    weight = resent(sessions)
    total = sum(weight.values())
    tool = sum(v for k, v in weight.items() if k in (
        "command output", "file reads", "searches and listings", "edit results", "subagent reports",
        "browser pages and screenshots", "MCP tool output", "web pages", "other tool output"))
    reads = [sum(s.read_chars[0] for s in sessions), sum(s.read_chars[1] for s in sessions)]
    biggest = max(sessions, key=lambda s: s.sent)
    out = [f"{name}  ·  {len(sessions)} session{'s' * (len(sessions) != 1)} active in the last {days} day{'s' * (days != 1)}",
           f"  Sent to the model:     {tokens(sent)} tokens of input, {tokens(output)} written back",
           f"  Re-sent history:       {pct(cached, sent)} of input was history it had already sent"]
    if biggest.sent and len(sessions) > 1:
        out.append(f"  Biggest session:       {pct(biggest.sent, sent)} of all input, on its own")
    if total:
        out.append(f"  Old tool output:       {pct(tool, total)} of what gets re-sent is tool output, not conversation")
    if reads[1]:
        out.append(f"  Files read twice:      {pct(reads[1], reads[0])} of file-read output was a file it had already read")
    if total:
        out += ["", "  What it keeps re-sending:"]
        for kind, v in weight.most_common(TOP):
            share = 100 * v / total
            if share >= 0.5:
                out.append(f"    {kind:30} {share:3.0f}%  {'█' * max(1, round(share / 4))}")
    facts = {"cached": cached / sent if sent else 0, "tool": tool / total if total else 0}
    return "\n".join(out), facts


def main(argv=None):
    ap = argparse.ArgumentParser(description="Where your Claude Code and Codex tokens went (offline).")
    ap.add_argument("--days", type=int, default=7, help="how far back to look (default 7)")
    args = ap.parse_args(argv)
    since = time.time() - args.days * 86400
    claude_root = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "projects"
    codex_root = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "sessions"
    found = [("Claude Code", [parse_claude(p) for p in recent(claude_root, "**/*.jsonl", since)]),
             ("Codex", [parse_codex(p) for p in recent(codex_root, "**/*.jsonl", since)])]

    print(f"\nWhere your coding agent's tokens went  (offline; nothing left this machine)\n")
    shown = []
    for name, sessions in found:
        text, facts = report(name, sessions, args.days)
        if text:
            print(text + "\n")
            shown.append((name, facts))
    if not shown:
        print(f"No Claude Code or Codex sessions from the last {args.days} day{'s' * (args.days != 1)} were found under\n"
              f"  {claude_root}\n  {codex_root}\nTry --days 30.")
        return 1
    print("Why it adds up: every request re-sends the whole session so far. Caching makes the\n"
          "repeats cheaper, but they still count, and on long sessions they are most of the input.\n"
          "What helps: /compact or a fresh session between tasks, shorter command output, and\n"
          "not re-reading files the agent already has.")
    share = "; ".join(f"{n}: {f['cached'] * 100:.0f}% of input was re-sent history, "
                      f"{f['tool'] * 100:.0f}% of what it re-sends is old tool output" for n, f in shown)
    print(f"\nTo share: \"{share}\" (densilo.com/tokens)")
    print("\nDensilo trims re-sent tool output automatically and keeps it recoverable: https://densilo.com")
    return 0


if __name__ == "__main__":
    sys.exit(main())
