# Where did my Claude Code tokens go?

One offline Python script that reads the Claude Code and Codex sessions already
recorded on your machine and shows what your agent sent to the model, and what it
kept sending again.

```sh
curl -fsSL https://densilo.com/tokens.py | python3 -
# or, from a clone of this repo
python3 tokens.py --days 30
```

Python 3.8 or later, standard library only. It reads `~/.claude/projects` and
`~/.codex/sessions`. Nothing is uploaded, no model is called, no account is needed
and nothing is written to disk. It prints totals and percentages only, never file
names or session contents. It's one short file, so read it first.

## What it shows

For each agent, over the last 7 days by default:

- **Re-sent history**: how much of the input was history the agent had already sent.
  Every request re-sends the whole session so far. Caching makes the repeats
  cheaper, but they still count.
- **Biggest session**: how much of all input came from your single longest session.
- **Old tool output**: how much of what gets re-sent is tool output (command output,
  file reads, browser pages) rather than conversation.
- **Files read twice**: how much of file-read output was a file the agent had already read.
- **What it keeps re-sending**: the input broken down by kind of content.

Example (percentages from one of our machines, a week of Claude Code):

```
  Re-sent history:       98% of input was history it had already sent
  Old tool output:       62% of what gets re-sent is tool output, not conversation
  Files read twice:      48% of file-read output was a file it had already read

  What it keeps re-sending:
    command output                  35%  █████████
    tool calls the agent made       22%  █████
    browser pages and screenshots   15%  ████
    file reads                      10%  ██
    the agent's replies              8%  ██
    your messages                    4%  █
```

## What helps

- `/compact` or a fresh session between tasks, so old turns stop being re-sent.
- Shorter command output: pipe long test and build logs through `tail` or `grep`.
- Don't let the agent re-read files it already has.

There's a longer write-up of what a long session sends, with the breakdown for
Claude Code and Codex, at [densilo.com/teardown](https://densilo.com/teardown).

## About

Made by [Densilo](https://densilo.com), a local proxy that trims re-sent tool output
automatically and keeps it recoverable. This script works on its own and doesn't
need Densilo. `tokens.py` here is the same file served at densilo.com/tokens.py.

Issues and pull requests welcome, especially if your mix looks different from ours.

## License

MIT
