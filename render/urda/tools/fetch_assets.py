"""Download the real-world data used by the Urda reconstruction.

PNOA orthophoto and MDT05 elevation from the Spanish IGN/CNIG public services,
plus CC0 HDRI, textures and models from Poly Haven.
"""
import json
import os
import sys
import urllib.request

OUT = sys.argv[1]
UA = {"User-Agent": "urda-reconstruction/1.0"}
CX, CY = 429596, 4364593

HDRI = ("autumn_field_puresky", "4k")
TEXTURES = ["red_laterite_soil_stones", "sparse_grass", "withered_grass", "gravel_floor",
            "dry_ground_rocks", "brushed_concrete", "rusty_metal_02", "bark_brown_02"]
TEX_MAPS = {"Diffuse": "diff", "nor_gl": "nor", "Rough": "rough", "Displacement": "disp"}
MODELS = ["modular_chainlink_fence", "shrub_01", "shrub_02", "shrub_03", "shrub_04", "grass_medium_01"]


def get(url, path):
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=300) as r, open(path + ".part", "wb") as fh:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            fh.write(chunk)
    os.replace(path + ".part", path)
    print("got", os.path.relpath(path, OUT), os.path.getsize(path) // 1024, "KB", flush=True)


def files(asset):
    req = urllib.request.Request(f"https://api.polyhaven.com/files/{asset}", headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def ign():
    wms = ("https://www.ign.es/wms-inspire/pnoa-ma?SERVICE=WMS&REQUEST=GetMap&VERSION=1.3.0"
           "&LAYERS=OI.OrthoimageCoverage&STYLES=&CRS=EPSG:25830&FORMAT=image/jpeg")
    for i in (0, 1, 2):
        for j in (0, 1, 2):
            x0, y0 = CX - 400 + i * 400, CY - 600 + j * 600
            get(f"{wms}&BBOX={x0},{y0},{x0 + 400},{y0 + 600}&WIDTH=1600&HEIGHT=2400",
                os.path.join(OUT, f"near_{i}_{j}.jpg"))
            if i == 2 or j == 2:
                continue
            x0, y0 = CX - 2500 + i * 2500, CY - 2500 + j * 2500
            get(f"{wms}&BBOX={x0},{y0},{x0 + 2500},{y0 + 2500}&WIDTH=2000&HEIGHT=2000",
                os.path.join(OUT, f"far_{i}_{j}.jpg"))
    get("https://servicios.idee.es/wcs-inspire/mdt?SERVICE=WCS&REQUEST=GetCoverage&VERSION=2.0.1"
        f"&CoverageId=Elevacion25830_5&SUBSET=x({CX - 2500},{CX + 2500})&SUBSET=y({CY - 2500},{CY + 2500})"
        "&FORMAT=image/tiff", os.path.join(OUT, "dem.tif"))


def polyhaven():
    ph = os.path.join(OUT, "ph")
    name, res = HDRI
    f = files(name)
    get(f["hdri"][res]["hdr"]["url"], os.path.join(ph, name + ".hdr"))
    for t in TEXTURES:
        f = files(t)
        for key, short in TEX_MAPS.items():
            if key in f and "2k" in f[key]:
                fmt = "jpg" if "jpg" in f[key]["2k"] else "png"
                get(f[key]["2k"][fmt]["url"], os.path.join(ph, t, f"{short}.{fmt}"))
    for m in MODELS:
        g = files(m)["gltf"]["2k"]["gltf"]
        get(g["url"], os.path.join(ph, m, m + ".gltf"))
        for rel, inc in g.get("include", {}).items():
            get(inc["url"], os.path.join(ph, m, rel))


if __name__ == "__main__":
    ign()
    polyhaven()
    print("ASSETS OK")
