# AI Tooling Policy (R24)

## Status

Decision: **gitignore `.claude/` and `AGENTS.md`**. They are
session-scoped operator notes that do not represent project canon.
They stay UNTRACKED so the main branch is clean across operator
setups.

## What is .claude/

`.claude/` is a hidden directory created by the Claude Code CLI when
operators run it inside the repository. It contains:

- worktrees for parallel sessions (`.claude/worktrees/<id>/`),
- session metadata,
- per-session hooks and settings,
- transcripts that some operators choose to keep locally.

The contents are **per-operator**, not **per-project**. Two
operators on the same branch should not have to reconcile each
other's session transcripts.

## What is AGENTS.md

`AGENTS.md` is a working-notes file that some agentic CLIs write
into the repo root to coordinate multi-agent runs. Its content is
session-scoped and changes too fast to be tracked alongside code.

## Why ignore rather than commit

If we committed these files we would:

- pollute commits with whose-laptop-was-this-from churn,
- leak operator-specific paths and timestamps into main,
- merge-conflict on every concurrent session,
- pin operators to a specific tooling version.

If we instead committed an empty `.claude/` placeholder and asked
operators to keep it clean, the placeholder would still drift; this
solution doesn't scale.

## Why not delete on every push

Deleting them locally between sessions defeats the point of session
caches. They are useful where they live -- just not committable.

## What stays in the repo instead

- **`CLAUDE.md`** (project root) -- stays tracked. This is the
  canonical set of project instructions for any AI tool. Versioned
  alongside code.
- **`docs/AI_TOOLING_POLICY.md`** (this file) -- documents the
  decision so future sessions don't suggest committing `.claude/` or
  `AGENTS.md`.
- **`.gitignore`** -- carries the exclusion entries with a comment
  pointing at this file.

## Future-session checklist

When `.claude/` or `AGENTS.md` shows up in `git status` on a fresh
session:

1. They are EXPECTED to be untracked. Don't `git add` them.
2. Don't propose removing them from disk; they are operator-scoped.
3. If an operator wants to keep transcripts for review, they write
   them out to `~/Documents/` or another personal location, not into
   the repo.

## Out of scope

- Per-operator IDE settings (`.vscode/`, `.idea/`) -- already
  handled by the regular gitignore block.
- Pre-commit hooks installed via `pre-commit install` -- those live
  under `.git/hooks/`, not tracked.
- Claude Code MCP / plugin manifests -- they live in
  `~/.claude/`, outside the project tree.
