"""Thin script wrapper for one GitHub shard."""

from __future__ import annotations

import sys

from aurora.cli.cmd_github import script_main


if __name__ == "__main__":
    raise SystemExit(script_main("run-shard", sys.argv[1:]))
