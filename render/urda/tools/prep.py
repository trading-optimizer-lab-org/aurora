"""Pre-process IGN data: orthophoto mosaics, DEM as numpy, real tree positions."""
import json
import os
import sys

import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None
D = sys.argv[1]
CX, CY = 429596, 4364593
P0 = np.array([429599.0, 4364593.0])          # track centre at the crash point
U = np.array([-0.3198, -0.9474])              # southbound track direction (local +X)
V = np.array([0.9474, -0.3198])               # left of travel = east (local +Y)


def mosaic(prefix, tw, th, nx, ny, out):
    big = Image.new("RGB", (tw * nx, th * ny))
    for i in range(nx):
        for j in range(ny):
            big.paste(Image.open(os.path.join(D, f"{prefix}_{i}_{j}.jpg")), (i * tw, (ny - 1 - j) * th))
    big.save(os.path.join(D, out), quality=94)
    return big


near = mosaic("near", 1600, 2400, 3, 3, "near.jpg")       # 0.25 m/px, E 429196..430396, N 4363993..4365793
far = mosaic("far", 2000, 2000, 2, 2, "far.jpg")           # 1.25 m/px, E 427096..432096, N 4362093..4367093

dem_im = Image.open(os.path.join(D, "dem.tif"))
dem = np.array(dem_im, dtype=np.float32)
tp = dem_im.tag_v2.get(33922)
sc = dem_im.tag_v2.get(33550)
np.save(os.path.join(D, "dem.npy"), dem)
meta = {"dem_origin": [tp[3], tp[4]], "dem_px": [sc[0], sc[1]], "P0": P0.tolist(), "U": U.tolist(), "V": V.tolist(),
        "near_bbox": [CX - 400, CY - 600, CX + 800, CY + 1200], "far_bbox": [CX - 2500, CY - 2500, CX + 2500, CY + 2500]}


def box_blur(a, r):
    k = 2 * r + 1
    p = np.pad(a, r + 1, mode="edge").astype(np.float64)
    c = p.cumsum(0).cumsum(1)
    s = c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]
    return (s / (k * k))[: a.shape[0], : a.shape[1]].astype(np.float32)


def local_max(a, r):
    m = a.copy()
    h, w = a.shape
    p = np.pad(a, r, mode="constant", constant_values=-1e9)
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if dx * dx + dy * dy <= r * r:
                m = np.maximum(m, p[r + dy: r + dy + h, r + dx: r + dx + w])
    return a >= m


def detect(img, px, bbox, blur_bg, peak_r, thr, size_r):
    a = np.asarray(img, dtype=np.float32)
    lum = 0.3 * a[..., 0] + 0.59 * a[..., 1] + 0.11 * a[..., 2]
    dark = box_blur(lum, blur_bg) - lum
    sm = box_blur(dark, 1)
    peaks = local_max(sm, peak_r) & (sm > thr)
    rows, cols = np.nonzero(peaks)
    mask = dark > thr * 0.6
    area = box_blur(mask.astype(np.float32), size_r) * (2 * size_r + 1) ** 2
    out = []
    for r, c in zip(rows, cols):
        E = bbox[0] + (c + 0.5) * px
        N = bbox[3] - (r + 0.5) * px
        rad = float(max(0.8, min(4.5, np.sqrt(area[r, c] / np.pi) * px)))
        out.append((E, N, rad, round(float(sm[r, c]), 1)))
    return out


def to_local(E, N):
    d = np.array([E, N]) - P0
    return float(d @ U), float(d @ V)


near_half = near.resize((near.width // 2, near.height // 2), Image.LANCZOS)   # 0.5 m/px
trees = []
for E, N, rad, s in detect(near_half, 0.5, meta["near_bbox"], 20, 4, 18.0, 5):
    x, y = to_local(E, N)
    if abs(y) < 9.5 or (21 < y < 31):          # track bed and the gravel service road
        continue
    trees.append((round(x, 2), round(y, 2), round(rad, 2), "shrub" if abs(y) < 40 else "olive", s))
nb = meta["near_bbox"]
for E, N, rad, s in detect(far, 1.25, meta["far_bbox"], 8, 2, 20.0, 2):
    if nb[0] + 5 < E < nb[2] - 5 and nb[1] + 5 < N < nb[3] - 5:
        continue
    x, y = to_local(E, N)
    if abs(x) > 1700 or abs(y) > 1700 or abs(y) < 10:
        continue
    trees.append((round(x, 2), round(y, 2), round(rad, 2), "olive", s))
json.dump({"meta": meta, "trees": trees}, open(os.path.join(D, "scene_data.json"), "w"))
print("trees", len(trees), "shrubs", sum(1 for t in trees if t[3] == "shrub"))
