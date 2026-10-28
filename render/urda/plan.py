"""Shot list and shard plan shared by the render, cache split and assembly steps (no bpy here)."""
K = 3
I = 330
# name, camera, first real frame, last real frame, slow-motion factor
SHOTS = [("J1", "CamA", 1, 150, 1), ("J2", "CamB", 151, 300, 1), ("J3", "CamC", 301, 450, 1),
         ("J4", "CamD", 318, 375, 3), ("J5", "CamE", 451, 780, 1)]
EARLY = ("J1", "J2")          # before the impact: no dust cache needed
EARLY_SHARDS = 120
LATE_SHARDS = 240
CHUNK = 10                    # late shards per dust-cache artifact


def tasks(which):
    out = []
    for j, cam, a, b, slow in SHOTS:
        if (j in EARLY) != (which == "early"):
            continue
        if slow == 1:
            frames = [(r - 1) * K + 1 for r in range(a, b + 1)]
        else:
            frames = list(range((a - 1) * K + 1, (b - 1) * K + 2))
        for i, f in enumerate(frames):
            out.append((j, cam, f, i + 1, slow))
    return out


def shard(which, n):
    t = tasks(which)
    total = EARLY_SHARDS if which == "early" else LATE_SHARDS
    return t[n * len(t) // total:(n + 1) * len(t) // total]


def chunk_frames(c):
    fr = set()
    for n in range(c * CHUNK, min(LATE_SHARDS, (c + 1) * CHUNK)):
        fr.update(t[2] for t in shard("late", n))
    return fr


N_CHUNKS = (LATE_SHARDS + CHUNK - 1) // CHUNK


def chunk_of(scene_frame):
    for n in range(LATE_SHARDS):
        if any(t[2] == scene_frame for t in shard("late", n)):
            return n // CHUNK
    return None


PREVIEW = [("CamA", 418), ("CamB", 838), ("CamC", 1258), ("CamD", 1011), ("CamE", 2098)]
DUST_RUN = "40722463580"
