"""Split the baked dust cache into one artifact folder per group of late render shards.

python split_cache.py <cache_dir> <out_root>
"""
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plan  # noqa: E402

src, dst = sys.argv[1], sys.argv[2]
files = []
for root, _, names in os.walk(src):
    for nm in names:
        files.append(os.path.relpath(os.path.join(root, nm), src))
for c in range(plan.N_CHUNKS):
    need = plan.chunk_frames(c)
    base = os.path.join(dst, f"c{c}", "dust_cache")
    os.makedirs(base, exist_ok=True)
    n = 0
    for rel in files:
        m = re.findall(r"(\d{4})", os.path.basename(rel))
        if m and int(m[-1]) not in need:
            continue
        os.makedirs(os.path.dirname(os.path.join(base, rel)), exist_ok=True)
        shutil.copy2(os.path.join(src, rel), os.path.join(base, rel))
        n += 1
    open(os.path.join(dst, f"c{c}", "chunk.txt"), "w").write(f"{c} {n}\n")
    print("chunk", c, "files", n, "frames", min(need), max(need))
