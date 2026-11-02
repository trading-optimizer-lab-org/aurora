"""Writes .github/workflows/v54s2.yml (run from the repo root) from v54s.yml: V54S_PREREGISTRATION.md section 5,
the strict rules with the filling bar's open kept as a better price."""
import re
from pathlib import Path

s = Path(".github/workflows/v54s.yml").read_text(encoding="utf-8")
s = re.sub(r"shard: \[[^\]]*\]", "shard: [asis, through1o, vol3k1o, vol3k5o]", s)
s = s.replace('"v54s: CRASH-long under strict fills"', '"v54s2: CRASH-long under strict fills, price improvement kept"')
s = s.replace("gen_v54s_wf.py writes this file (V54S_PREREGISTRATION.md)",
              "gen_v54s2_wf.py writes this file (V54S_PREREGISTRATION.md section 5)")
s = s.replace(".github/workflows/v54s.yml", ".github/workflows/v54s2.yml").replace("group: v54s\n", "group: v54s2\n")
s = s.replace("outputs/v54sw", "outputs/v54s2w").replace("v54s-minute-", "v54s2-minute-")
s = s.replace("name: v54s-report", "name: v54s2-report")
Path(".github/workflows/v54s2.yml").write_text(s, encoding="utf-8", newline="\n")
print("wrote .github/workflows/v54s2.yml")
