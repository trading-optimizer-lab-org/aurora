"""Thin script wrapper for selective GitHub recovery planning."""

from __future__ import annotations

import sys

from aurora.cli.cmd_github import script_main


if __name__ == "__main__":
    raise SystemExit(script_main("recover-plan", sys.argv[1:]))
