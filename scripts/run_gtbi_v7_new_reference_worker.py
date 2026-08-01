"""Run one GTBI V7 logical worker with measured 1/2/4-way symbol work."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from infra.gtbi_v7_new_reference.runner import run_v7_batch, run_v7_worker


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-worker-ids", default="")
    parser.add_argument("--processes-per-runner", type=int, choices=(1, 2, 4), default=1)
    parser.add_argument("--campaign-manifest", type=Path, required=True)
    parser.add_argument("--data-manifest", type=Path, required=True)
    parser.add_argument("--plan-root", type=Path, required=True)
    parser.add_argument("--data-pack-root", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--worker-id", type=int)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--symbol-workers", type=int, choices=(1, 2, 4), default=1)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.batch_worker_ids:
        worker_ids = [int(value) for value in args.batch_worker_ids.split(",") if value.strip()]
        payload = run_v7_batch(
            campaign_manifest_path=args.campaign_manifest,
            data_manifest_path=args.data_manifest,
            plan_root=args.plan_root,
            data_pack_root=args.data_pack_root,
            authorization_path=args.authorization,
            worker_ids=worker_ids,
            output_root=args.output_dir,
            processes_per_runner=args.processes_per_runner,
        )
    else:
        if args.worker_id is None:
            parser.error("--worker-id is required unless --batch-worker-ids is used")
        payload = run_v7_worker(
            campaign_manifest_path=args.campaign_manifest,
            data_manifest_path=args.data_manifest,
            plan_root=args.plan_root,
            data_pack_root=args.data_pack_root,
            authorization_path=args.authorization,
            worker_id=args.worker_id,
            output_dir=args.output_dir,
            symbol_workers=args.symbol_workers,
        )
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
