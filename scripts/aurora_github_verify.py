"""Thin script wrapper for independent GitHub artifact verification."""

from __future__ import annotations

import sys

from aurora.cli.cmd_github import script_main


if __name__ == "__main__":
    raise SystemExit(script_main("verify", sys.argv[1:]))
