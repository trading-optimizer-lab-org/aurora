"""Thin script wrapper for a bounded GitHub merge plan."""

from __future__ import annotations

import sys

from aurora.cli.cmd_github import script_main


if __name__ == "__main__":
    raise SystemExit(script_main("merge-plan", sys.argv[1:]))
