"""Fail unless two or more GTBI V7 outputs are scientifically identical."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from infra.gtbi_v7_new_reference.runner import assert_batch_outputs_equal, assert_scientific_outputs_equal


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("outputs", type=Path, nargs="+")
    parser.add_argument("--batch", action="store_true")
    args = parser.parse_args(argv)
    if args.batch:
        payload = assert_batch_outputs_equal(args.outputs)
    else:
        digest = assert_scientific_outputs_equal(args.outputs)
        payload = {"equivalent": True, "scientific_output_digest": digest}
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
