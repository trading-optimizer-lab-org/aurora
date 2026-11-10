"""Copy the encrypted borrow logs and locate meter artifacts to the owner's PC and decrypt them there.

GitHub keeps each artifact 90 days; this keeps them for good. Run on the owner's PC (it needs gh and the private
key in ~/.gnupg-aurora-tzloc). Already copied runs are skipped.

  python scripts/private_data_sync.py [--dest ~/aurora-private-data]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess  # nosec B404: runs gh and gpg with fixed arguments
import sys
import tarfile
from pathlib import Path

REPO = "trading-optimizer-lab-org/aurora"
NAMES = ("borrowlog-snap", "borrowlog-daily", "tzloc-encrypted")


def artifacts() -> list[dict]:
    out = ""
    for name in NAMES:  # filtered by name: the full artifact list of this repository is too long to page through
        out += subprocess.run(["gh", "api", "--paginate",  # nosec B603 B607
                               f"repos/{REPO}/actions/artifacts?per_page=100&name={name}",
                               "--jq", ".artifacts[] | {id, name, expired, run: .workflow_run.id, created_at}"],
                              check=True, capture_output=True, text=True).stdout
    return [a for a in map(json.loads, out.splitlines()) if not a["expired"]]


def gpg_path(p: Path) -> str:
    """Git for Windows ships an MSYS gpg that only reads /c/... paths."""
    gpg = shutil.which("gpg") or ""
    if os.name == "nt" and "git" in gpg.lower() and p.drive:
        return "/" + p.drive[0].lower() + p.as_posix()[2:]
    return str(p)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dest", type=Path, default=Path.home() / "aurora-private-data")
    args = ap.parse_args()
    env = {**os.environ, "GNUPGHOME": gpg_path(Path.home() / ".gnupg-aurora-tzloc")}
    new = 0
    for a in artifacts():
        d = args.dest / a["name"].split("-")[0] / f"{a['created_at'][:10]}_{a['run']}_{a['name']}"
        if (d / ".done").exists():
            continue
        shutil.rmtree(d, ignore_errors=True)  # a copy cut short earlier: start that run again
        d.mkdir(parents=True)
        subprocess.run(["gh", "run", "download", str(a["run"]), "-R", REPO, "-n", a["name"], "-D", str(d)],  # nosec B603 B607
                       check=True, capture_output=True)
        for enc in d.glob("*.gpg"):
            tgz = enc.with_suffix("")
            subprocess.run(["gpg", "--batch", "--quiet", "--yes", "-o", gpg_path(tgz), "--decrypt", gpg_path(enc)],  # nosec
                           check=True, env=env, capture_output=True)
            with tarfile.open(tgz) as t:
                t.extractall(d, filter="data")
            tgz.unlink()
        (d / ".done").write_text(a["created_at"])
        new += 1
    print(f"{new} new runs copied to {args.dest}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
