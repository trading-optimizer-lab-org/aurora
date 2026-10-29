"""Shot list and shard plan shared by the render, cache split and assembly steps (no bpy here)."""
K = 3
I = 330
# name, camera, first real frame, last real frame, slow-motion factor
SHOTS = [("J1", "CamA", 1, 150, 1), ("J2", "CamB", 151, 300, 1), ("J3", "CamC", 301, 450, 1),
         ("J4", "CamD", 318, 375, 3), ("J5", "CamE", 451, 780, 1)]
EARLY = ("J1", "J2")          # before the impact: no dust cache needed
EARLY_SHARDS = 116
LATE_SHARDS = 340
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

# context stills, 2560x1440: (frame, camera location, target or None for straight down, lens, labels)
_LAST = (800 - 1) * K + 1
STILLS = {
    "S_wide": dict(frame=1, loc=(-950, 300, 300), target=(250, -20, 0), lens=32),
    "S_iryo": dict(frame=(200 - 1) * K + 1, loc=(236, -18, 8.45), target=(150, -2.35, 7.5), lens=40),
    "S_top": dict(frame=_LAST, loc=(35, -2, 270), target=None, lens=24, labels=[
        ("Iryo 1-2: sobre la vía", ["IRYO_1", "IRYO_2"]),
        ("Iryo 3-5: descarrilados", ["IRYO_3", "IRYO_4", "IRYO_5"]),
        ("Iryo 6-8: talud abajo (7 y 8 volcados)", ["IRYO_6", "IRYO_7", "IRYO_8"]),
        ("AVE coche 1: talud contrario", ["AVE_1"]),
        ("AVE 2-3: destrozados", ["AVE_2", "AVE_3"]),
        ("AVE 4-8: descarrilados a la vía contigua", ["AVE_4", "AVE_5", "AVE_6", "AVE_7", "AVE_8"]),
    ]),
    "S_close": dict(frame=_LAST, loc=(100, 52, 30), target=(22, 0, 3), lens=30),
}
