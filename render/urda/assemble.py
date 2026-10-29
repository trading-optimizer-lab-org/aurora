"""Edit the documentary: map, timeline, context stills, 3D shots and data cards into one MP4.

python assemble.py <frames_dir> <stills_dir> <work_dir> <out.mp4>
"""
import json
import math
import os
import subprocess
import sys
import time
import urllib.request

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from pyproj import Transformer

FR, ST, WORK, OUT = sys.argv[1:5]
os.makedirs(WORK, exist_ok=True)
W, H, FPS = 1920, 1080, 30
DJ = "/usr/share/fonts/truetype/dejavu/"
BG = (11, 13, 16)
RED, WHITE, AMBER, GREY = (214, 40, 40), (245, 245, 245), (255, 196, 64), (170, 176, 186)
ENC = ["-c:v", "libx264", "-preset", "slow", "-crf", "16", "-pix_fmt", "yuv420p", "-r", str(FPS)]
CPS = 17  # comfortable reading speed for on-screen text, characters per second
_fonts = {}


def read_time(*texts, base=2.0):
    return base + sum(len(t) for t in texts if t) / CPS


def font(size, bold=False):
    k = (size, bold)
    if k not in _fonts:
        _fonts[k] = ImageFont.truetype(DJ + ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"), size)
    return _fonts[k]


def wrap(d, text, f, width):
    out = []
    for para in text.split("\n"):
        line = ""
        for w in para.split():
            t = (line + " " + w).strip()
            if d.textlength(t, font=f) <= width:
                line = t
            else:
                out.append(line)
                line = w
        out.append(line)
    return out


def text_block(d, xy, text, f, width, fill=WHITE, gap=10, anchor_center=False):
    x, y = xy
    for ln in wrap(d, text, f, width):
        lx = x - d.textlength(ln, font=f) / 2 if anchor_center else x
        d.text((lx, y), ln, font=f, fill=fill)
        y += f.size + gap
    return y


def caption_layer(title, sub):
    """Lower third that always fits the frame."""
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    ft, fs = font(40, True), font(31)
    lines_t = wrap(d, title, ft, W - 160)
    lines_s = wrap(d, sub, fs, W - 160) if sub else []
    h = 40 + len(lines_t) * 50 + len(lines_s) * 41 + 24
    d.rectangle([0, H - h, W, H], fill=(0, 0, 0, 120))
    y = H - h + 26
    for ln in lines_t:
        d.text((80, y), ln, font=ft, fill=WHITE)
        y += 50
    y += 6
    for ln in lines_s:
        d.text((80, y), ln, font=fs, fill=(225, 225, 225))
        y += 41
    d.text((W - 36, 30), "RECONSTRUCCIÓN APROXIMADA", font=font(22), fill=(255, 255, 255, 170), anchor="ra")
    return im


class Seg:
    """Pipe RGB frames into one encoded segment."""
    n = 0

    def __init__(self, name):
        Seg.n += 1
        self.path = os.path.join(WORK, f"{Seg.n:02d}_{name}.mp4")
        self.p = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                                   "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-"] + ENC + [self.path],
                                  stdin=subprocess.PIPE)
        SEGS.append(self.path)

    def put(self, im):
        self.p.stdin.write(im.convert("RGB").tobytes())

    def close(self):
        self.p.stdin.close()
        if self.p.wait():
            sys.exit(f"ffmpeg failed on {self.path}")


SEGS = []


def fade(im, k, n, fin=10, fout=10):
    a = min(1.0, (k + 1) / fin if fin else 1.0, (n - k) / fout if fout else 1.0)
    if a >= 1.0:
        return im
    return Image.blend(Image.new("RGB", im.size, (0, 0, 0)), im.convert("RGB"), max(0.0, a))


# ------------------------------------------------------------------ cards
def card(name, title, body, dur, bg=None, small=None):
    seg = Seg(name)
    base = (bg.copy() if bg is not None else Image.new("RGB", (W, H), BG)).convert("RGBA")
    d = ImageDraw.Draw(base)
    y = 300 if body else 470
    y = text_block(d, (W / 2, y), title, font(64, True), 1500, gap=18, anchor_center=True) + 30
    if small:
        text_block(d, (W / 2, H - 150), small, font(24), 1600, fill=GREY, gap=8, anchor_center=True)
    # body paragraphs appear one by one, each once the previous one has had time to be read
    layers, t = [], 1.0 + len(title) / CPS
    for para in body.split("\n") if body else []:
        lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        y = text_block(ImageDraw.Draw(lay), (W / 2, y), para, font(36), 1420, fill=(230, 230, 230), gap=14,
                       anchor_center=True) + 16
        layers.append((t, lay))
        t += len(para) / CPS + 0.8
    n = int(max(dur, t + 2.5) * FPS)
    for k in range(n):
        im = base
        for t0, lay in layers:
            a = (k / FPS - t0) / 0.6
            if a >= 1:
                im = Image.alpha_composite(im, lay)
            elif a > 0:
                part = lay.copy()
                part.putalpha(lay.getchannel("A").point(lambda v, a=a: int(v * a)))
                im = Image.alpha_composite(im, part)
        seg.put(fade(im, k, n, 15, 15))
    seg.close()


# ------------------------------------------------------------------ maps (IGN WMS)
TO_UTM = Transformer.from_crs("EPSG:4326", "EPSG:25830", always_xy=True)


def utm(lat, lon):
    return TO_UTM.transform(lon, lat)


def wms(url_base, layer, bbox, size, path):
    q = (f"{url_base}?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap&LAYERS={layer}&STYLES=&CRS=EPSG:25830"
         f"&BBOX={bbox[0]:.0f},{bbox[1]:.0f},{bbox[2]:.0f},{bbox[3]:.0f}&WIDTH={size[0]}&HEIGHT={size[1]}"
         f"&FORMAT=image/jpeg")
    for attempt in range(6):
        try:
            req = urllib.request.Request(q, headers={"User-Agent": "urda-reconstruction/1.0"})
            with urllib.request.urlopen(req, timeout=120) as r:
                open(path, "wb").write(r.read())
            return Image.open(path).convert("RGB")
        except Exception as ex:  # noqa: BLE001 - public service, fall back to a plain map
            print("wms retry", layer, ex, flush=True)
            time.sleep(10 * (attempt + 1))
    return Image.new("RGB", size, (228, 224, 214))


def view(cx, cy, width):
    h = width * H / W
    return (cx - width / 2, cy - h / 2, cx + width / 2, cy + h / 2)


def to_px(bb, x, y, size=(W, H)):
    return ((x - bb[0]) / (bb[2] - bb[0]) * size[0], (bb[3] - y) / (bb[3] - bb[1]) * size[1])


def crop_view(img, img_bb, bb):
    """Render map bbox bb from a larger map image."""
    x0, y0 = to_px(img_bb, bb[0], bb[3], img.size)
    x1, y1 = to_px(img_bb, bb[2], bb[1], img.size)
    x0, y0 = max(0.0, x0), max(0.0, y0)
    x1, y1 = min(float(img.size[0]), x1), min(float(img.size[1]), y1)
    return img.resize((W, H), Image.BILINEAR, box=(x0, y0, x1, y1))


def lerp_bb(a, b, u):
    # geometric zoom: interpolate centre linearly and width logarithmically
    wa, wb = a[2] - a[0], b[2] - b[0]
    w = wa * (wb / wa) ** u
    cx = (a[0] + a[2]) / 2 * (1 - u) + (b[0] + b[2]) / 2 * u
    cy = (a[1] + a[3]) / 2 * (1 - u) + (b[1] + b[3]) / 2 * u
    return view(cx, cy, w)


def marker(d, p, col, r=11, ring=0.0):
    x, y = p
    if ring > 0:
        rr = r + 30 * ring
        d.ellipse([x - rr, y - rr, x + rr, y + rr], outline=col + (int(255 * (1 - ring)),), width=4)
    d.ellipse([x - r, y - r, x + r, y + r], fill=col, outline=(255, 255, 255), width=3)


def label(d, p, text, f, dx=18, dy=-14, fill=WHITE):
    x, y = p[0] + dx, p[1] + dy
    tw = d.textlength(text, font=f)
    if x + tw + 16 > W:
        x = p[0] - dx - tw
    d.rounded_rectangle([x - 10, y - 6, x + tw + 10, y + f.size + 10], 8, fill=(0, 0, 0, 170))
    d.text((x, y), text, font=f, fill=fill)


# LAV Madrid-Sevilla centreline around Urda from OpenStreetMap (ETRS89 UTM 30N, north to south), and the point
# 25 km up the line from the crash where the AVE stood after the LZB failure (between Mora and Manzaneque)
LAV_LOCAL = [(431105, 4394000), (431252, 4393000), (431411, 4391750), (431418, 4390750), (431208, 4388000),
             (431384, 4387000), (431664, 4386000), (431729, 4385000), (431525, 4384000), (429941, 4380750),
             (429676, 4379750), (429378, 4377500), (429088, 4375250), (428622, 4371500), (428511, 4370500),
             (428602, 4369500), (428917, 4368500), (429512, 4367500), (429779, 4366500), (429809, 4365500),
             (429606, 4364500), (429120, 4363250), (428704, 4362000), (428170, 4360750), (427414, 4359500),
             (426672, 4358250), (424932, 4355000)]
AVE_STOP = (431249, 4388750)


def map_sequence(crash_utm):
    P0 = crash_utm
    stop = AVE_STOP
    north = [(40.4066, -3.6907), (40.235, -3.700), (40.120, -3.800), (39.900, -3.780)]
    south = [(39.200, -3.840), (38.982, -3.926), (38.690, -4.110), (38.650, -4.290), (38.400, -4.560),
             (38.150, -4.700), (37.888, -4.789), (37.700, -5.100), (37.560, -5.450), (37.392, -5.975)]
    route = [utm(*p) for p in north] + LAV_LOCAL + [utm(*p) for p in south]
    v1 = view(380000, 4280000, 900000)
    v1z = view(380000, 4280000, 840000)
    # keep both markers above the lower third
    c2 = ((stop[0] + P0[0]) / 2 + 3000, 4372300)
    v2 = view(*c2, 68000)
    v2b = view(*c2, 204000)
    big1 = wms("https://www.ign.es/wms-inspire/ign-base", "IGNBaseTodo", v1, (3200, 1800), os.path.join(WORK, "m1.jpg"))
    big2 = wms("https://www.ign.es/wms-inspire/ign-base", "IGNBaseTodo", v2b, (4000, 2250), os.path.join(WORK, "m2.jpg"))
    madrid, sevilla = route[0], route[-1]
    seg = Seg("map")
    n1, nz, n2 = 12 * FPS, 4 * FPS, 18 * FPS
    total = n1 + nz + n2
    for k in range(total):
        if k < n1:
            bb = lerp_bb(v1, v1z, k / n1)
            im = crop_view(big1, v1, bb)
        elif k < n1 + nz:
            u = (k - n1) / nz
            u = u * u * (3 - 2 * u)
            bb = lerp_bb(v1z, v2, u)
            im = crop_view(big1, v1, bb)
            if bb[2] - bb[0] <= v2b[2] - v2b[0]:
                im = Image.blend(im, crop_view(big2, v2b, bb), min(1.0, (u - 0.57) / 0.23))
        else:
            bb = v2
            im = crop_view(big2, v2b, v2)
        ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(ov)
        if k < n1 + nz:
            u = min(1.0, max(0.0, (k - 15) / (6 * FPS)))
            pts = [to_px(bb, *p) for p in route]
            m = max(2, int(len(pts) * u) + 1)
            seg_pts = pts[:m]
            if u > 0 and len(seg_pts) > 1:
                d.line(seg_pts, fill=(160, 40, 120, 230), width=7, joint="curve")
            marker(d, to_px(bb, *madrid), (60, 60, 60))
            label(d, to_px(bb, *madrid), "Madrid-Puerta de Atocha", font(28, True))
            if u >= 1:
                marker(d, to_px(bb, *sevilla), (60, 60, 60))
                label(d, to_px(bb, *sevilla), "Sevilla-Santa Justa", font(28, True))
            ring = ((k / FPS) % 1.2) / 1.2
            marker(d, to_px(bb, *P0), RED, ring=ring)
            label(d, to_px(bb, *P0), "Urda (Toledo) · PK 118", font(30, True))
            cap = caption_layer("Línea de alta velocidad Madrid-Sevilla (1992)",
                                "El AVE 2080 sale de Madrid-Puerta de Atocha a las 08:00. El Iryo 6076 había salido"
                                " pocos minutos antes con el mismo destino. Trazado aproximado")
        else:
            ps, pc = to_px(bb, *stop), to_px(bb, *P0)
            d.line([to_px(bb, *p) for p in LAV_LOCAL], fill=(160, 40, 120, 200), width=6, joint="curve")
            i0 = LAV_LOCAL.index((431208, 4388000))
            d.line([ps] + [to_px(bb, *p) for p in LAV_LOCAL[i0:20]] + [pc], fill=AMBER + (255,), width=8,
                   joint="curve")
            mid = to_px(bb, *LAV_LOCAL[12])
            label(d, mid, "≈ 25 km de vía", font(30, True), dx=24, dy=-20, fill=AMBER)
            marker(d, ps, (230, 230, 230))
            label(d, ps, "08:31 · AVE 2080 detenido por la caída del LZB", font(28, True))
            ring = ((k / FPS) % 1.2) / 1.2
            marker(d, pc, RED, ring=ring)
            label(d, pc, "Iryo 6076 detenido ante la señal de entrada de Urda", font(28, True))
            cap = caption_layer("Entre Mora y Urda (Toledo)",
                                "Hacia las 08:30 un fallo informático en Urda tumba el sistema de seguridad LZB en"
                                " unos 63-69 km de línea. Seis trenes se detienen automáticamente")
        im = Image.alpha_composite(im.convert("RGBA"), ov)
        im = Image.alpha_composite(im, cap)
        seg.put(fade(im, k, total, 15, 12))
    seg.close()


# ------------------------------------------------------------------ timeline diagram
EVENTS = [
    (30.0, "08:30", "Un fallo informático en Urda tumba el sistema LZB. Seis trenes se detienen."),
    (31.0, "08:31", "El maquinista del AVE avisa a Atocha: \"fallo de transmisión por bloqueo parcial\"."),
    (36.0, "08:36", "Atocha ordena al AVE reanudar \"al amparo del BSL con marcha normal\". "
                    "El protocolo exigía marcha a la vista: máximo 40 km/h."),
    (38.0, "08:38", "El Iryo 6076 queda detenido ante la señal de entrada de Urda (según Iryo)."),
    (41.0, "08:41", "La maquinista del Iryo avisa: \"estoy detenida en señal de entrada de Urda\"."),
    (43.0, "08:43", "El AVE arranca y acelera hacia Urda."),
    (48.0, "08:48", "El Iryo insiste: \"estoy todavía detenida ante la señal de entrada\". "
                    "Respuesta: \"en cuanto pueda, y si tiene problemas nos llama\"."),
    (53.0, "08:53", "Alcance en el PK 118. No consta en los audios publicados ninguna orden al AVE para"
                    " detenerse."),
]
# AVE speed profile (minute, km/h): stopped until 08:43, then the per-minute averages published from
# Renfe position data (El Español: 145, 214, 236, 181) and about 200 km/h at impact (Ministerio)
SPEED = [(43.0, 0), (44.5, 90), (46.3, 145), (47.3, 214), (51.3, 236), (52.3, 190), (53.0, 200)]


def speed_at(m):
    if m <= SPEED[0][0]:
        return 0.0
    for (a, va), (b, vb) in zip(SPEED, SPEED[1:]):
        if m <= b:
            return va + (vb - va) * (m - a) / (b - a)
    return SPEED[-1][1]


def ave_km(m):
    # integrate the profile and scale it so the AVE covers the reported 25 km by 08:53
    def dist(t):
        s, x, step = 0.0, 43.0, 1 / 60
        while x < t:
            s += speed_at(x) * step / 60
            x += step
        return s
    full = dist(53.0)
    return 93.0 + 25.0 * dist(min(m, 53.0)) / full


def clock_keys():
    # the clock runs between events and stops on each one long enough to read it
    keys, t, m = [(0.0, 30.0)], 1.0, 30.0
    for ev in EVENTS:
        if ev[0] > m:
            keys.append((t, m))
            t += 1.0 + 0.6 * (ev[0] - m)
            m = ev[0]
        t += read_time(ev[2], base=1.5)
        keys.append((t, m))
    return keys


def clock_at(keys, t):
    for (ta, ma), (tb, mb) in zip(keys, keys[1:]):
        if t <= tb:
            u = (t - ta) / (tb - ta) if tb > ta else 1.0
            return ma + (mb - ma) * u * u * (3 - 2 * u)
    return keys[-1][1]


def timeline():
    seg = Seg("timeline")
    keys = clock_keys()
    n = int((keys[-1][0] + 1.5) * FPS)
    x0, x1, km0, km1 = 140, 1780, 88.0, 121.0
    X = lambda km: x0 + (km - km0) / (km1 - km0) * (x1 - x0)  # noqa: E731
    for k in range(n):
        m = clock_at(keys, k / FPS)
        im = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(im)
        d.text((80, 60), "Cronología · miércoles 28 de octubre de 2026", font=font(44, True), fill=WHITE)
        hh, mm = 8, int(m)
        ss = int((m - mm) * 60)
        d.text((W - 80, 52), f"{hh:02d}:{mm:02d}:{ss:02d}", font=font(64, True), fill=AMBER, anchor="ra")
        # track
        ty = 330
        d.line([(x0, ty), (x1, ty)], fill=(120, 126, 136), width=6)
        for km in range(90, 121, 5):
            d.line([(X(km), ty - 12), (X(km), ty + 12)], fill=(120, 126, 136), width=3)
            d.text((X(km), ty + 22), f"km {km}", font=font(22), fill=GREY, anchor="ma")
        d.text((x0, ty - 150), "← Madrid", font=font(26, True), fill=GREY)
        d.text((x1, ty - 150), "Sevilla →", font=font(26, True), fill=GREY, anchor="ra")
        # Urda entry signal
        sx = X(118.1)
        d.line([(sx, ty - 60), (sx, ty - 14)], fill=WHITE, width=4)
        d.ellipse([sx - 11, ty - 82, sx + 11, ty - 60], fill=RED)
        d.text((sx, ty + 56), "Señal de entrada de Urda · PK 118", font=font(24, True), fill=WHITE, anchor="ma")
        # Iryo, shown from 08:38
        if m >= 38.0:
            d.rounded_rectangle([X(118.0) - 0, ty - 34, X(118.0) + 64, ty - 12], 8, fill=(190, 20, 30))
            d.text((X(118.0) + 64, ty - 96), "Iryo 6076", font=font(26, True), fill=(255, 120, 120), anchor="la")
        # AVE
        a = ave_km(m)
        ax = X(a)
        d.rounded_rectangle([ax - 64, ty - 34, ax, ty - 12], 8, fill=(240, 240, 240))
        d.text((ax, ty - 96), "AVE 2080", font=font(26, True), fill=WHITE, anchor="ra")
        v = speed_at(m)
        d.text((ax - 32, ty + 100), f"≈ {v:.0f} km/h" if v > 0 else "detenido", font=font(30, True),
               fill=AMBER, anchor="ma")
        gap = 118.0 - a
        if gap > 0.05 and m >= 38.0:
            d.line([(ax + 6, ty + 160), (X(118.0) - 6, ty + 160)], fill=(255, 255, 255), width=2)
            d.text(((ax + X(118.0)) / 2, ty + 170), f"{gap:.1f} km", font=font(26), fill=WHITE, anchor="ma")
        # events
        shown = [e for e in EVENTS if e[0] <= m + 1e-6]
        y = 600
        for ev in shown[-4:]:
            last = ev is shown[-1]
            col = WHITE if last else (150, 156, 166)
            d.text((80, y), ev[1], font=font(34, True), fill=AMBER if last else col)
            y = text_block(d, (230, y + 2), ev[2], font(30, last), 1600, fill=col, gap=8) + 18
        d.text((W - 80, H - 46), "Velocidades: medias por minuto de datos públicos de posición (El Español) y "
                                 "cifra del Ministerio. Posiciones aproximadas.", font=font(20), fill=GREY, anchor="ra")
        if 36.0 <= m < 43.0:
            text_block(d, (980, 128), "A 200 km/h un tren de alta velocidad necesita unos 4 km para detenerse",
                       font(26, True), 620, fill=AMBER)
        seg.put(fade(im, k, n, 15, 12))
    seg.close()


# ------------------------------------------------------------------ stills with a slow push-in
def still(sid, title, sub, dur, z0=1.0, z1=1.12, labels=False):
    p = os.path.join(ST, f"{sid}.png")
    if not os.path.exists(p):
        print("missing still", sid, flush=True)
        return
    base = Image.open(p).convert("RGB")
    sw, sh = base.size
    if labels:
        lab = json.load(open(os.path.join(ST, f"{sid}.json"), encoding="utf-8"))
        d = ImageDraw.Draw(base, "RGBA")
        f = font(int(36 * sw / W), True)
        for i, l in enumerate(lab):
            x, y = l["x"] * sw, l["y"] * sh
            ly = y + (-140 if i % 2 == 0 else 120) * sw / W
            d.line([(x, y), (x, ly)], fill=(255, 255, 255, 230), width=4)
            d.ellipse([x - 9, y - 9, x + 9, y + 9], fill=(255, 255, 255, 255))
            tw = d.textlength(l["text"], font=f)
            lx = min(max(20, x - tw / 2), sw - tw - 20)
            d.rounded_rectangle([lx - 14, ly - f.size / 2 - 12, lx + tw + 14, ly + f.size / 2 + 14], 10,
                                fill=(0, 0, 0, 185))
            d.text((lx, ly - f.size / 2), l["text"], font=f, fill=WHITE)
        # direction of travel: +x in the scene is towards Sevilla, image right for the top view
        d.text((sw - 60, 60), "Sentido Madrid → Sevilla", font=font(int(30 * sw / W), True),
               fill=(255, 255, 255, 230), anchor="ra")
    cap = caption_layer(title, sub)
    seg = Seg(sid)
    extra = sum(len(l["text"]) for l in lab) / CPS if labels else 0.0
    n = int(max(dur, read_time(title, sub) + extra) * FPS)
    for k in range(n):
        u = k / max(1, n - 1)
        z = z0 + (z1 - z0) * (u * u * (3 - 2 * u))
        cw, ch = sw / z, sh / z
        cx, cy = sw / 2, sh / 2
        im = base.resize((W, H), Image.BILINEAR, box=(cx - cw / 2, cy - ch / 2, cx + cw / 2, cy + ch / 2))
        im = Image.alpha_composite(im.convert("RGBA"), cap)
        seg.put(fade(im, k, n, 12, 12))
    seg.close()


# ------------------------------------------------------------------ rendered 3D shots
CAPS = {
    "J1": ("08:52 · El AVE 2080 se aproxima a Urda a unos 200 km/h",
           "Circula por la misma vía en la que el Iryo lleva 15 minutos detenido"),
    "J2": ("08:53 · El Iryo 6076 sigue parado ante la señal de entrada",
           "Viajan 147 personas, entre ellas un bebé. El AVE lleva 397 pasajeros"),
    "J3": ("08:53 · Alcance en el PK 118 de la línea Madrid-Sevilla",
           "Unos 200 km/h según el Ministerio. La velocidad exacta la darán las cajas negras"),
    "J4": ("Repetición a cámara lenta ×6",
           "La cabeza del AVE destroza la cola del Iryo, se separa del tren y cae por el talud contrario"),
    "J5": ("Tres coches del Iryo caen por el terraplén. El resto del AVE descarrila hacia la vía contigua",
           "Un carril roto atraviesa el coche 3 del AVE"),
}


def shot(j, slow=1, hold_out=0.0):
    """Play a rendered shot; hold its first frame until the caption can be read, slow it by frame doubling."""
    d = os.path.join(FR, j)
    files = sorted(f for f in os.listdir(d) if f.endswith(".png")) if os.path.isdir(d) else []
    if not files:
        print("missing shot", j, flush=True)
        return
    capp = os.path.join(WORK, f"cap_{j}.png")
    caption_layer(*CAPS[j]).save(capp)
    motion = len(files) * slow / FPS
    hold_in = max(1.0, read_time(*CAPS[j]) - motion - hold_out)
    paths = [os.path.abspath(os.path.join(d, f)) for f in files]
    entries = [(paths[0], hold_in)] + [(p, slow / FPS) for p in paths] + [(paths[-1], max(hold_out, 1 / FPS))]
    lst = os.path.join(WORK, f"{j}.txt")
    with open(lst, "w") as fh:
        for p, du in entries:
            fh.write(f"file '{p}'\nduration {du:.6f}\n")
        fh.write(f"file '{paths[-1]}'\n")  # concat demuxer ignores the duration of the last entry
    n = int(round((hold_in + motion + hold_out) * FPS))
    Seg.n += 1
    out = os.path.join(WORK, f"{Seg.n:02d}_{j}.mp4")
    blend = ",tmix=frames=2" if slow > 1 else ""
    fc = (f"[0:v]fps={FPS}{blend},noise=alls=3:allf=t[v];[v][1:v]overlay=0:0,"
          f"fade=in:0:8,fade=out:{max(0, n - 8)}:8[o]")
    r = subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst,
                        "-i", capp, "-filter_complex", fc, "-map", "[o]", "-frames:v", str(n)] + ENC + [out])
    if r.returncode:
        sys.exit(f"ffmpeg failed on {j}")
    SEGS.append(out)
    print(j, n, "frames", flush=True)


# ------------------------------------------------------------------ edit
card("title", "Choque de trenes en Urda (Toledo)",
     "Reconstrucción 3D del alcance entre el AVE 2080 de Renfe y el Iryo 6076\n"
     "Miércoles 28 de octubre de 2026 · 08:53", 5,
     small="Recreación aproximada basada en información pública. No es una grabación real.")
map_sequence((429599.0, 4364593.0))
still("S_wide", "La recta de Urda, a los pies de los Montes de Toledo",
      "Terreno, olivares y vegetación a partir de la ortofoto PNOA y el modelo de elevaciones MDT05 del IGN", 6)
timeline()
still("S_iryo", "08:38-08:53 · El Iryo 6076 espera ante la señal de entrada de Urda",
      "Su maquinista avisa al centro de control de Adif a las 08:41 y a las 08:48", 6, 1.0, 1.08)
shot("J1")
shot("J2")
shot("J3")
shot("J4", slow=2)
shot("J5", hold_out=4.0)
still("S_top", "Posición final aproximada de los coches",
      "Según las imágenes aéreas de la Guardia Civil y lo publicado por RTVE, 20minutos y el ingeniero Gareth Dennis",
      10, 1.0, 1.04, labels=True)
still("S_close", "Zona del impacto",
      "La cabina trasera del Iryo queda desintegrada. La cabeza del AVE acaba fuera de la vía, en el talud contrario", 7)
bgp = os.path.join(ST, "S_wide.png")
bg = None
if os.path.exists(bgp):
    bg = Image.open(bgp).convert("RGB").resize((W, H)).filter(ImageFilter.GaussianBlur(18))
    bg = Image.blend(Image.new("RGB", (W, H), (0, 0, 0)), bg, 0.35)
card("balance", "Balance provisional",
     "Al menos 68 fallecidos: 44 en el Iryo y 24 en el AVE\n"
     "107 heridos. 53 siguen hospitalizados, 15 de ellos graves\n"
     "544 personas viajaban en los dos trenes (397 en el AVE y 147 en el Iryo)", 8, bg,
     small="Junta de Castilla-La Mancha y Gobierno, 28-29 de octubre de 2026. Las cifras pueden cambiar.")
card("investigacion", "La investigación",
     "Juzgado de Instrucción n.º 2 de Orgaz y Guardia Civil, con una investigación técnica independiente en paralelo\n"
     "Claves: las cajas negras de los dos trenes y los audios entre el centro de control de Adif en Atocha y los"
     " maquinistas\n"
     "El Ministerio de Transportes habla de un error humano: tras la caída del LZB el protocolo obligaba a ir a"
     " 40 km/h como máximo", 9, bg,
     small="Fuentes: Ministerio de Transportes, El País, elDiario.es, El Confidencial, Cadena SER, EFE.")
card("contexto", "Contexto",
     "El LZB se instaló en 1992 y solo sigue en servicio en la Madrid-Sevilla, en sustitución por el ERTMS europeo\n"
     "Es el segundo accidente mortal en esta línea en 2026, tras el de Adamuz (Córdoba) en enero, con 46 muertos\n"
     "El Gobierno ha decretado tres días de luto oficial, del 29 al 31 de octubre", 9, bg)
card("end", "En memoria de las víctimas",
     "Recreación ilustrativa con datos publicados hasta el 29/10/2026 (Ministerio de Transportes, Adif, RTVE, "
     "El País, elDiario.es, El Confidencial, El Español, La Vanguardia, 20minutos, Guardia Civil) y el análisis de "
     "imágenes aéreas de Gareth Dennis.\nTerreno: IGN/CNIG (PNOA, MDT05). Mapas: IGN Base. Posiciones, velocidades y "
     "daños son aproximados. Las causas las determinará la investigación oficial.", 9)

lst = os.path.join(WORK, "list.txt")
with open(lst, "w") as fh:
    for s in SEGS:
        fh.write(f"file '{os.path.abspath(s)}'\n")
r = subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy",
                    "-movflags", "+faststart", OUT])
if r.returncode:
    sys.exit("concat failed")
print("OK", OUT, len(SEGS), "segments", flush=True)
