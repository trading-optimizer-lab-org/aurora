#!/usr/bin/env python3
"""One gh API call under the admission deadline. Never retries a write."""

from pathlib import Path
import subprocess
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from aurora.infra.sp500_megarun.catalog_gate_budget import gate_timeout


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("CATALOG_GATE_COMMAND_INVALID", file=sys.stderr)
        return 2
    method = "GET"
    for index, arg in enumerate(args):
        if arg in {"--method", "-X"} and index + 1 < len(args):
            method = args[index + 1].upper()
        elif arg.startswith("--method="):
            method = arg.split("=", 1)[1].upper()
    potentially_writes = method not in {"GET", "HEAD"} or any(
        arg.split("=", 1)[0] in {"--input", "--field", "--raw-field", "-f", "-F"} for arg in args)
    try:
        result = subprocess.run(["gh", "api", *args], timeout=gate_timeout(20), check=False)
        return result.returncode
    except subprocess.TimeoutExpired:
        print("CATALOG_GATE_WRITE_UNCONFIRMED" if potentially_writes else "CATALOG_GATE_READ_TIMEOUT", file=sys.stderr)
        return 124
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except OSError:
        print("CATALOG_GATE_COMMAND_UNAVAILABLE", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
