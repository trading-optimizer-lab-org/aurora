"""Chronological documentary edit: every minute from 07:54 to 08:53 told over the 3D scene.

python assemble.py <frames_dir> <stills_dir> <work_dir> <out.mp4>

frames_dir holds the rendered sequences J1..J5 (v3) and SIG, ORB, CAB (v4 extra shots).
A heads-up band (clock, both trains on a strip of the line, AVE speed) stays on screen until the impact.
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
RED, WHITE, AMBER, GREY = (214, 40, 40), (245, 245, 245), (255, 196, 64), (170, 176, 186)
IRYO_C, AVE_C = (226, 60, 70), (240, 240, 240)
ENC = ["-c:v", "libx264", "-preset", "slow", "-crf", "16", "-pix_fmt", "yuv420p", "-r", str(FPS)]
LICENCE = ("Vídeo de libre uso con licencia CC BY 4.0: puedes compartirlo, recortarlo y reutilizarlo citando la"
           " fuente. Terreno y mapas © Instituto Geográfico Nacional (CC BY 4.0).")
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


def smooth(u):
    u = min(1.0, max(0.0, u))
    return u * u * (3 - 2 * u)


def with_alpha(im, a):
    if a >= 1:
        return im
    out = im.copy()
    out.putalpha(im.getchannel("A").point(lambda v: int(v * max(0.0, a))))
    return out


class Seg:
    """Pipe RGB frames into one encoded segment."""
    n = 0

    def __init__(self, name):
        Seg.n += 1
        self.name = name
        self.path = os.path.join(WORK, f"{Seg.n:02d}_{name}.mp4")
        self.p = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                                   "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-"] + ENC + [self.path],
                                  stdin=subprocess.PIPE)
        self.k = 0
        SEGS.append(self)

    def put(self, im):
        self.p.stdin.write(im.convert("RGB").tobytes())
        self.k += 1

    def close(self):
        self.p.stdin.close()
        if self.p.wait():
            sys.exit(f"ffmpeg failed on {self.path}")
        print(f"{self.name}: {self.k / FPS:.1f} s", flush=True)


SEGS = []


def fade(im, k, n, fin=10, fout=10):
    a = min(1.0, (k + 1) / fin if fin else 1.0, (n - k) / fout if fout else 1.0)
    if a >= 1.0:
        return im
    return Image.blend(Image.new("RGB", im.size, (0, 0, 0)), im.convert("RGB"), max(0.0, a))


# ------------------------------------------------------------------ 3D backgrounds
class Frames:
    """A rendered PNG sequence played at a given speed, with optional holds on its first and last frames."""

    def __init__(self, name, first=0, last=None, slow=1.0, hold_in=0.0):
        d = os.path.join(FR, name)
        self.files = sorted(os.path.join(d, f) for f in os.listdir(d) if f.endswith(".png")) if os.path.isdir(d) else []
        if not self.files:
            print("missing frames", name, flush=True)
        self.files = self.files[first:last]
        self.slow, self.hold_in = slow, hold_in
        self.cache = {}

    def motion(self):
        return len(self.files) * self.slow / FPS

    def _load(self, i):
        i = min(max(0, i), len(self.files) - 1)
        if i not in self.cache:
            if len(self.cache) > 4:
                self.cache.clear()
            self.cache[i] = Image.open(self.files[i]).convert("RGB").resize((W, H), Image.BILINEAR)
        return self.cache[i]

    def at(self, t):
        if not self.files:
            return Image.new("RGB", (W, H), (20, 22, 26))
        p = max(0.0, t - self.hold_in) * FPS / self.slow
        i = int(p)
        u = p - i
        if self.slow > 1 and u > 0.01 and i + 1 < len(self.files):
            return Image.blend(self._load(i), self._load(i + 1), u)
        return self._load(i)


class Still:
    """A large context still with a slow push-in."""

    def __init__(self, sid, z0=1.0, z1=1.1, cx=0.5, cy=0.5, labels=False):
        p = os.path.join(ST, f"{sid}.png")
        self.ok = os.path.exists(p)
        if not self.ok:
            print("missing still", sid, flush=True)
            return
        self.base = Image.open(p).convert("RGB")
        self.z0, self.z1, self.cx, self.cy = z0, z1, cx, cy
        if labels:
            self.draw_labels(sid)

    def draw_labels(self, sid):
        base = self.base
        sw, sh = base.size
        lab = json.load(open(os.path.join(ST, f"{sid}.json"), encoding="utf-8"))
        d = ImageDraw.Draw(base, "RGBA")
        f = font(int(38 * sw / W), True)
        boxes = []
        mx, my = sw * 0.08, sh * 0.08
        for lb in lab:
            x, y = lb["x"] * sw, lb["y"] * sh
            tw = d.textlength(lb["text"], font=f)
            lx = min(max(mx, x - tw / 2), sw - tw - mx)
            # first leader length whose label box clears the others and the frame
            for off in (-140, 130, -260, 250, -380, 370, -500, 490):
                ly = y + off * sw / W
                box = (lx - 20, ly - f.size, lx + tw + 20, ly + f.size)
                if box[1] > my and box[3] < sh * 0.76 and not any(
                        box[0] < b[2] and b[0] < box[2] and box[1] < b[3] and b[1] < box[3] for b in boxes):
                    break
            boxes.append(box)
            d.line([(x, y), (min(max(x, lx), lx + tw), ly)], fill=(255, 255, 255, 230), width=4)
            d.ellipse([x - 9, y - 9, x + 9, y + 9], fill=(255, 255, 255, 255))
            d.rounded_rectangle([lx - 14, ly - f.size / 2 - 12, lx + tw + 14, ly + f.size / 2 + 14], 10,
                                fill=(0, 0, 0, 190))
            d.text((lx, ly - f.size / 2), lb["text"], font=f, fill=WHITE)
        # +x in the scene is towards Sevilla, image right for the top view
        d.text((mx, my), "Sentido Madrid → Sevilla", font=font(int(32 * sw / W), True), fill=(255, 255, 255, 235))

    def at(self, t, dur):
        if not self.ok:
            return Image.new("RGB", (W, H), (20, 22, 26))
        sw, sh = self.base.size
        z = self.z0 + (self.z1 - self.z0) * smooth(t / max(dur, 0.1))
        cw, ch = sw / z, sh / z
        cx = min(max(cw / 2, self.cx * sw), sw - cw / 2)
        cy = min(max(ch / 2, self.cy * sh), sh - ch / 2)
        return self.base.resize((W, H), Image.BILINEAR, box=(cx - cw / 2, cy - ch / 2, cx + cw / 2, cy + ch / 2))


# ------------------------------------------------------------------ text overlays
MARK = Image.new("RGBA", (W, H), (0, 0, 0, 0))
ImageDraw.Draw(MARK).text((30, 10), "RECONSTRUCCIÓN APROXIMADA · DATOS PÚBLICOS A 29/10/2026",
                          font=font(20), fill=(255, 255, 255, 150), anchor="la")


def caption_layer(title, sub):
    """Lower third that always fits the frame."""
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if not title:
        return im
    d = ImageDraw.Draw(im)
    ft, fs = font(46, True), font(36)
    lines_t = wrap(d, title, ft, W - 160)
    lines_s = wrap(d, sub, fs, W - 160) if sub else []
    h = 34 + len(lines_t) * 57 + len(lines_s) * 46 + 40
    d.rectangle([0, H - h, W, H], fill=(0, 0, 0, 150))
    y = H - h + 24
    for ln in lines_t:
        d.text((80, y), ln, font=ft, fill=WHITE)
        y += 57
    y += 6
    for ln in lines_s:
        d.text((80, y), ln, font=fs, fill=(228, 228, 228))
        y += 46
    return im


def caption_height(title, sub):
    d = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    if not title:
        return 0
    return 34 + len(wrap(d, title, font(46, True), W - 160)) * 57 + (
        len(wrap(d, sub, font(36), W - 160)) * 46 if sub else 0) + 40


WHO = {"AVE": ("Maquinista del AVE", AVE_C), "IRYO": ("Maquinista del Iryo", IRYO_C),
       "ATOCHA": ("Centro de control de Adif (Atocha)", AMBER), "NOTE": ("", GREY)}


def bubble(who, text, width=1000):
    """One line of the published control-room audio, as a speech panel."""
    name, col = WHO[who]
    tmp = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    lines = wrap(tmp, text, font(36, who != "NOTE"), width - 60)
    h = 26 + (40 if name else 0) + len(lines) * 46 + 18
    im = Image.new("RGBA", (width, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, width - 1, h - 1], 16, fill=(8, 10, 14, 205))
    d.rectangle([0, 10, 8, h - 10], fill=col + (255,))
    y = 18
    if name:
        d.text((30, y), name, font=font(28, True), fill=col)
        y += 40
    for ln in lines:
        d.text((30, y), ln, font=font(36, who != "NOTE"), fill=WHITE if who != "NOTE" else (225, 225, 225))
        y += 46
    return im


def explainer(title, text, width=760):
    """Plain-language box for a technical term."""
    tmp = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    lines = wrap(tmp, text, font(32), width - 60)
    h = 30 + 46 + len(lines) * 42 + 26
    im = Image.new("RGBA", (width, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, width - 1, h - 1], 16, fill=(20, 40, 70, 215), outline=(120, 170, 230, 255), width=3)
    d.text((30, 24), title, font=font(34, True), fill=(170, 210, 255))
    y = 24 + 50
    for ln in lines:
        d.text((30, y), ln, font=font(32), fill=WHITE)
        y += 42
    return im


def centre_panel(title, body, width=1400):
    tmp = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    paras = body.split("\n")
    lines = [wrap(tmp, p, font(42), width - 120) for p in paras]
    h = 60 + 90 + sum(len(ls) * 56 + 22 for ls in lines) + 40
    im = Image.new("RGBA", (width, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, width - 1, h - 1], 22, fill=(6, 8, 12, 200))
    d.text((width / 2, 50), title, font=font(64, True), fill=WHITE, anchor="ma")
    y = 150
    layers = []
    for ls in lines:
        lay = Image.new("RGBA", (width, h), (0, 0, 0, 0))
        dl = ImageDraw.Draw(lay)
        for ln in ls:
            dl.text((width / 2, y), ln, font=font(42), fill=(232, 232, 232), anchor="ma")
            y += 56
        y += 22
        layers.append(lay)
    return im, layers


# ------------------------------------------------------------------ the line, the trains and the clock
# minutes are counted from 08:00; km along the line from Madrid-Puerta de Atocha
# AVE speed after the restart: 80 km/h restriction at km 92.95-94.05, then up to the official 200 km/h
SPEED = [(43.0, 0), (44.0, 60), (45.0, 80), (46.3, 145), (47.3, 200), (52.3, 190), (53.0, 200)]
IMPACT = 53.0


def speed_at(m):
    if m <= SPEED[0][0]:
        return 0.0
    for (a, va), (b, vb) in zip(SPEED, SPEED[1:]):
        if m <= b:
            return va + (vb - va) * (m - a) / (b - a)
    return SPEED[-1][1]


def _dist(t):
    s, x, step = 0.0, 43.0, 1 / 60
    while x < t:
        s += speed_at(x) * step / 60
        x += step
    return s


_FULL = _dist(IMPACT)


def ave_km(m):
    if m < 0:
        return 0.0
    if m < 31:
        u = m / 31
        return 93.0 * (1 - (1 - u) ** 1.6)
    if m < 43:
        return 93.0
    return 93.0 + 25.0 * _dist(min(m, IMPACT)) / _FULL


def ave_speed(m):
    if 0 <= m < 29:
        return 200.0 if m > 6 else 200.0 * m / 6
    if 29 <= m < 31:
        return 200.0 * (31 - m) / 2
    return speed_at(m) if m < IMPACT else 0.0


def iryo_km(m):
    # left at 07:54, running in BSL at 40 km/h from the LZB failure until the Urda entry signal at 08:38
    if m < -6:
        return 0.0
    if m < 30:
        return 112.7 * (m + 6) / 36
    if m < 38:
        return 112.7 + 5.3 * (m - 30) / 8
    return 118.0


def clock_text(m):
    hh = 8 + math.floor(m / 60)
    mm = int(m - 60 * (hh - 8))
    ss = int((m - math.floor(m)) * 60)
    return f"{hh % 24:02d}:{mm:02d}:{ss:02d}"


def hud(m):
    """Top band: clock, both trains on a strip of the line, AVE speed."""
    im = Image.new("RGBA", (W, 220), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for y in range(220):
        d.line([(0, y), (W, y)], fill=(0, 0, 0, int(200 * (1 - y / 220) ** 0.7)))
    d.text((W - 60, 26), clock_text(m), font=font(66, True), fill=AMBER, anchor="ra")
    d.text((W - 60, 104), "hora aproximada", font=font(22), fill=GREY, anchor="ra")
    z = smooth((m - 30) / 1.5)
    k0, k1 = 0 + 86 * z, 125 - 4 * z
    x0, x1, ty = 60, 1300, 112
    X = lambda km: x0 + (km - k0) / (k1 - k0) * (x1 - x0)  # noqa: E731
    d.line([(x0, ty), (x1, ty)], fill=(150, 156, 166, 255), width=6)
    step = 25 if z < 0.5 else 5
    km = math.ceil(k0 / step) * step
    while km <= k1:
        d.line([(X(km), ty - 9), (X(km), ty + 9)], fill=(150, 156, 166, 255), width=3)
        d.text((X(km), ty + 16), f"km {km}", font=font(20), fill=GREY, anchor="ma")
        km += step
    places = [(0, "Madrid"), (93, "Mora"), (118, "Urda")]
    for km, name in places:
        if k0 - 0.5 <= km <= k1:
            d.text((X(km), ty + 34), name, font=font(28, True), fill=WHITE, anchor="ma")
    sx = X(118.1)
    d.line([(sx, ty - 46), (sx, ty - 8)], fill=WHITE, width=3)
    d.ellipse([sx - 9, ty - 64, sx + 9, ty - 46], fill=RED)
    close = abs(X(iryo_km(m)) - X(ave_km(m))) < 330
    for km, col, name in ((iryo_km(m), IRYO_C, "Iryo 6076"), (ave_km(m), AVE_C, "AVE 2080")):
        if m < (-6 if name.startswith("Iryo") else 0):
            continue
        x = X(km)
        d.rounded_rectangle([x - 54, ty - 26, x, ty - 8], 7, fill=col + (255,))
        if name.startswith("Iryo"):
            if m >= 37:
                d.text((sx + 18, ty - 44), name + " · parado", font=font(28, True), fill=col, anchor="la")
            else:
                d.text((x - 27, ty - 62), name, font=font(28, True), fill=col, anchor="ma")
        else:
            v = ave_speed(m)
            tag = f"{name} · ≈ {v:.0f} km/h" if v >= 20 else (f"{name} · arrancando" if v > 0 else f"{name} · parado")
            if m >= 37:
                left = x - 66 - d.textlength(tag, font=font(28, True)) > 20
                d.text((x - 66 if left else x + 14, ty - 44), tag, font=font(28, True), fill=col,
                       anchor="ra" if left else "la")
            else:
                d.text((x - 27, ty - (94 if close else 62)), tag, font=font(28, True), fill=col, anchor="ma")
    gap = iryo_km(m) - ave_km(m)
    if m >= 38 and gap > 0.05:
        a, b = X(ave_km(m)), X(118.0) - 54
        txt = f"{gap:.1f} km entre los dos trenes"
        cx = min((a + b) / 2, x1 - d.textlength(txt, font=font(24, True)) / 2)
        d.line([(a + 4, ty + 78), (b - 4, ty + 78)], fill=(255, 255, 255, 200), width=2)
        d.text((cx, ty + 81), txt, font=font(24, True), fill=WHITE, anchor="ma")
    return im


# ------------------------------------------------------------------ chapters
def chapter(name, bg, title="", sub="", clock=None, items=(), explain=None, panel=None, min_dur=0.0,
            show_hud=True, realtime=None, fout=10, extra=None, hold_end=False):
    """One step of the story over a 3D background.

    bg: Frames or Still. items: [(who, text)] shown one after another. explain: (term, text).
    clock: (m0, m1) minutes from 08:00, interpolated over the chapter. realtime: seconds of footage that
    must play at its own speed (holds are added in front of it).
    """
    cap = caption_layer(title, sub)
    capt_h = caption_height(title, sub)
    t = 0.6 + read_time(title, sub, base=0.5)
    shown = []
    for who, text in items:
        shown.append((t, bubble(who, text)))
        t += read_time(text, base=1.2)
    ex = None
    if explain:
        ex = (t, explainer(*explain))
        t += read_time(*explain, base=1.2)
    pan = None
    if panel:
        im, layers = centre_panel(*panel)
        pan = [im, []]
        tt = 0.8 + len(panel[0]) / CPS
        for lay, p in zip(layers, panel[1].split("\n")):
            pan[1].append((tt, lay))
            tt += len(p) / CPS + 0.9
        t = max(t, tt + 1.5)
    dur = max(min_dur, t + 1.0)
    if realtime is not None:
        dur = max(dur, realtime)
    if isinstance(bg, Frames) and realtime is None and bg.files:
        bg.slow = max(1.0, dur * FPS / len(bg.files))
    elif isinstance(bg, Frames) and realtime is not None:
        bg.hold_in = 0.0 if hold_end else max(0.0, dur - bg.motion())
    n = int(dur * FPS)
    seg = Seg(name)
    top = 236 if show_hud else 60
    for k in range(n):
        tk = k / FPS
        im = (bg.at(tk, dur) if isinstance(bg, Still) else bg.at(tk)).convert("RGBA")
        if extra:
            im = extra(im, tk, dur)
        if show_hud and clock:
            m = clock[0] + (clock[1] - clock[0]) * smooth(tk / dur)
            im.alpha_composite(hud(m), (0, 0))
        # the last three lines of dialogue stay on screen, older ones give way
        y = top
        for t0, b in [x for x in shown if x[0] < tk][-3:]:
            im.alpha_composite(with_alpha(b, (tk - t0) / 0.4), (60, y))
            y += b.height + 14
        if ex and tk > ex[0]:
            im.alpha_composite(with_alpha(ex[1], (tk - ex[0]) / 0.4), (W - ex[1].width - 60, H - capt_h - ex[1].height - 30))
        if pan:
            px, py = (W - pan[0].width) // 2, max(top, (H - capt_h - pan[0].height) // 2)
            im.alpha_composite(pan[0], (px, py))
            for t0, lay in pan[1]:
                a = (tk - t0) / 0.5
                if a > 0:
                    im.alpha_composite(with_alpha(lay, a), (px, py))
        im = Image.alpha_composite(im, cap)
        im = Image.alpha_composite(im, MARK)
        seg.put(fade(im, k, n, 10, fout))
    seg.close()


def darken(a):
    def f(im, tk, dur):
        return Image.blend(Image.new("RGBA", im.size, (0, 0, 0, 255)), im, a)
    return f


# ------------------------------------------------------------------ Spain map inset (IGN WMS)
TO_UTM = Transformer.from_crs("EPSG:4326", "EPSG:25830", always_xy=True)


def utm(lat, lon):
    return TO_UTM.transform(lon, lat)


def wms(bbox, size, path):
    q = ("https://www.ign.es/wms-inspire/ign-base?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap&LAYERS=IGNBaseTodo"
         f"&STYLES=&CRS=EPSG:25830&BBOX={bbox[0]:.0f},{bbox[1]:.0f},{bbox[2]:.0f},{bbox[3]:.0f}"
         f"&WIDTH={size[0]}&HEIGHT={size[1]}&FORMAT=image/jpeg")
    for attempt in range(6):
        try:
            req = urllib.request.Request(q, headers={"User-Agent": "urda-reconstruction/1.0"})
            with urllib.request.urlopen(req, timeout=120) as r:
                open(path, "wb").write(r.read())
            return Image.open(path).convert("RGB")
        except Exception as ex:  # noqa: BLE001 - public service, fall back to a plain map
            print("wms retry", ex, flush=True)
            time.sleep(10 * (attempt + 1))
    return Image.new("RGB", size, (228, 224, 214))


def map_inset():
    """Madrid-Sevilla line and Urda, as a small framed map."""
    w, h = 620, 560
    cx, cy, span = 405000, 4240000, 520000
    bb = (cx - span / 2, cy - span * h / w / 2, cx + span / 2, cy + span * h / w / 2)
    m = wms(bb, (w, h), os.path.join(WORK, "inset.jpg")).convert("RGBA")
    d = ImageDraw.Draw(m)
    P = lambda p: ((p[0] - bb[0]) / (bb[2] - bb[0]) * w, (bb[3] - p[1]) / (bb[3] - bb[1]) * h)  # noqa: E731
    route = [(40.4066, -3.6907), (40.235, -3.700), (40.120, -3.800), (39.900, -3.780), (39.6458, -3.8013),
             (39.40, -3.86), (39.200, -3.840), (38.982, -3.926), (38.690, -4.110), (38.650, -4.290),
             (38.400, -4.560), (38.150, -4.700), (37.888, -4.789), (37.700, -5.100), (37.560, -5.450),
             (37.392, -5.975)]
    pts = [P(utm(*p)) for p in route]
    d.line(pts, fill=(160, 40, 120, 255), width=6, joint="curve")
    for p, name, col in ((pts[0], "Madrid", (40, 40, 40)), (pts[-1], "Sevilla", (40, 40, 40)),
                         (P(utm(39.4085, -3.7149)), "Urda", RED)):
        d.ellipse([p[0] - 9, p[1] - 9, p[0] + 9, p[1] + 9], fill=col, outline=(255, 255, 255), width=3)
        tw = d.textlength(name, font=font(26, True))
        d.rounded_rectangle([p[0] + 14, p[1] - 18, p[0] + 34 + tw, p[1] + 18], 8, fill=(0, 0, 0, 180))
        d.text((p[0] + 24, p[1] - 14), name, font=font(26, True), fill=WHITE)
    d.rectangle([0, 0, w - 1, h - 1], outline=(255, 255, 255, 230), width=3)
    d.text((10, h - 26), "Línea de alta velocidad Madrid-Sevilla · Mapa © IGN", font=font(18), fill=(30, 30, 30))
    return m


def with_inset(inset):
    def f(im, tk, dur):
        im.alpha_composite(with_alpha(inset, tk / 0.8), (W - inset.width - 60, 230))
        return im
    return f


def cab_overlay(im, tk, dur, bg):
    # distance left to the Iryo, from the remaining footage at about 200 km/h
    left = max(0.0, (len(bg.files) - max(0.0, tk - bg.hold_in) * FPS / bg.slow) / FPS * 200 / 3.6)
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([W / 2 - 230, 300, W / 2 + 230, 400], 16, fill=(0, 0, 0, 170))
    d.text((W / 2, 314), f"Iryo parado a ≈ {left:.0f} m", font=font(44, True), fill=IRYO_C, anchor="ma")
    return im


# ------------------------------------------------------------------ the edit
wide = Still("S_wide", 1.0, 1.25, 0.55, 0.55)
chapter("title", wide, show_hud=False,
        panel=("Choque de trenes en Urda (Toledo)",
               "Miércoles 28 de octubre de 2026\nReconstrucción en 3D, minuto a minuto, con datos públicos"),
        min_dur=7)
chapter("resumen", Still("S_wide", 1.25, 1.45, 0.55, 0.55), show_hud=False,
        panel=("Qué pasó",
               "Un AVE de Renfe chocó por detrás, a gran velocidad, contra un tren de Iryo que estaba parado en la"
               " misma vía\nAntes, un fallo informático había apagado el sistema que frena los trenes de forma"
               " automática\nAl menos 68 personas murieron"))
inset = map_inset()
chapter("salida", Still("S_wide", 1.0, 1.2, 0.5, 0.45),
        "07:54 y 08:00 · Dos trenes salen de Madrid hacia Sevilla, por la misma vía",
        "Primero el Iryo 6076, con 147 pasajeros. Seis minutos después, el AVE 2080, con 397",
        clock=(-6.0, 29.0), extra=with_inset(inset), min_dur=12)
chapter("lzb", Frames("SIG"),
        "08:30 · Un fallo informático en Urda apaga el sistema de seguridad LZB",
        "Afecta a unos 65 km de vía. Seis trenes se detienen o reducen la marcha, entre ellos el AVE y el Iryo",
        clock=(30.0, 31.0),
        explain=("¿Qué es el LZB?", "Un sistema que vigila cada tren desde la vía y lo frena solo si va demasiado"
                                    " rápido o si tiene otro tren delante. Sin él, el maquinista solo cuenta con"
                                    " las señales luminosas junto a la vía."))
chapter("orden", Still("S_wide", 1.2, 1.4, 0.45, 0.5),
        "08:31-08:36 · El AVE, parado en Mora, pide instrucciones al centro de control",
        "Audios publicados de las conversaciones con el centro de control de Adif en Atocha (Madrid)",
        clock=(31.0, 36.0),
        items=[("AVE", "«Me ha dado fallo por bloqueo parcial»"),
               ("NOTE", "Durante cinco minutos el operador duda y consulta a sus compañeros"),
               ("ATOCHA", "«Desconecte y vuelva a conectar el LZB y reanude marcha al amparo del BSL con marcha"
                          " normal»"),
               ("AVE", "«¿Con marcha normal?»"),
               ("ATOCHA", "«Sí»")],
        explain=("Marcha normal o marcha a la vista", "«Marcha normal» permite ir hasta 200 km/h. Sin el LZB, el"
                                                     " protocolo exigía «marcha a la vista»: un máximo de 40 km/h"
                                                     " para poder frenar ante cualquier obstáculo."))
chapter("iryo_para", Frames("ORB", 0, 180),
        "08:38 · El Iryo se detiene ante la señal de entrada de Urda, en rojo",
        "Queda parado en la misma vía por la que llegará el AVE, 25 km por detrás",
        clock=(36.0, 38.5))
chapter("iryo_llama", Frames("ORB", 180),
        "08:41 · La maquinista del Iryo avisa a Atocha",
        "", clock=(40.5, 41.5),
        items=[("IRYO", "«He tenido una pérdida de transmisión… Estoy detenida en la señal de entrada de Urda»"),
               ("ATOCHA", "«No le autorizamos el rebase»"),
               ("NOTE", "Y acto seguido le da la misma orden que al AVE: reanudar con marcha normal")])
chapter("ave_arranca", Still("S_iryo", 1.0, 1.12),
        "08:43 · El AVE arranca y acelera hacia Urda",
        "Pasa una limitación a 80 km/h en el km 93 y sube hasta unos 200 km/h. Delante, en la misma vía, está"
        " el Iryo",
        clock=(42.5, 47.5), min_dur=12)
chapter("iryo_insiste", Still("S_iryo", 1.12, 1.25, 0.6, 0.5),
        "08:48 · El Iryo vuelve a llamar: sigue parado",
        "Nadie avisa al AVE, que está a unos 17 km y se acerca a unos 200 km/h",
        clock=(48.0, 51.5),
        items=[("IRYO", "«No me está permitiendo el tren reiniciar el sistema LZB, y por eso estoy todavía"
                        " detenida ante la señal de entrada»"),
               ("ATOCHA", "«Vale, conforme. Pues nada, cuando pueda. Y si tiene problemas, nos llama»")])
j1 = Frames("J1")
chapter("aproximacion", j1,
        "08:52 · El AVE llega a la recta de Urda a unos 200 km/h",
        "El Iryo está parado unos cientos de metros más adelante",
        clock=(52.6, 52.8), realtime=j1.motion())
cab = Frames("CAB", 150)
chapter("cabina", cab,
        "Los últimos segundos, desde el frontal del AVE",
        "Recreación. Con el LZB apagado, nada frena el tren de forma automática",
        clock=(52.8, IMPACT), realtime=cab.motion(), fout=4,
        extra=lambda im, tk, dur: cab_overlay(im, tk, dur, cab))
j3 = Frames("J3")
chapter("impacto", j3,
        "08:53 · El AVE choca contra la cola del Iryo en el PK 118",
        "A unos 200 km/h según el Ministerio. La velocidad exacta la darán las cajas negras",
        show_hud=False, realtime=j3.motion())
j4 = Frames("J4", slow=2.0)
chapter("repeticion", j4,
        "Repetición a cámara lenta ×6",
        "La cabeza del AVE destroza el último coche del Iryo, se separa de su tren y cae por el talud contrario",
        show_hud=False, realtime=j4.motion())
j5 = Frames("J5")
chapter("despues", j5,
        "Tres coches del Iryo caen por el terraplén. El resto del AVE descarrila hacia la vía de al lado",
        "Un carril roto atraviesa el coche 3 del AVE",
        show_hud=False, realtime=j5.motion() + 3.0, hold_end=True)
chapter("posicion", Still("S_top", 1.0, 1.04, labels=True), "Así quedaron los dos trenes",
        "Según las imágenes aéreas de la Guardia Civil y lo publicado por RTVE, 20minutos y el ingeniero"
        " Gareth Dennis", show_hud=False, min_dur=8 + 70 / CPS)
chapter("balance", Still("S_close", 1.0, 1.12), show_hud=False, extra=darken(0.45),
        panel=("Balance provisional",
               "Al menos 68 personas murieron: 44 en el Iryo y 24 en el AVE\n"
               "110 heridos hospitalizados en Castilla-La Mancha: 53 siguen ingresados, 15 en estado crítico\n"
               "Más de 80 heridos atendidos además en hospitales de Madrid"),
        title="", sub="")
chapter("investigacion", Still("S_top", 1.05, 1.2), show_hud=False, extra=darken(0.4),
        panel=("La investigación",
               "Juzgado de Instrucción n.º 2 de Orgaz, con secreto de sumario, y una investigación técnica"
               " independiente\nClaves: las cajas negras de los dos trenes y los audios del centro de control\n"
               "La Guardia Civil ya ha tomado declaración al operador de Atocha y a la maquinista del Iryo\n"
               "El Ministerio de Transportes habla de error humano: la orden de «marcha normal» con el LZB apagado"))
chapter("contexto", Still("S_wide", 1.3, 1.5, 0.5, 0.55), show_hud=False, extra=darken(0.4),
        panel=("Contexto",
               "El LZB se instaló en 1992 y solo sigue en servicio en la Madrid-Sevilla, donde se está"
               " sustituyendo por el sistema europeo ERTMS\nEs el segundo accidente mortal en esta línea en 2026,"
               " tras el de Adamuz (Córdoba) en enero, con 46 muertos, y el más grave en España desde Angrois"
               " (2013), con 80\nEl Gobierno ha decretado tres días de luto oficial, del 29 al 31 de octubre"))
chapter("fin", Still("S_wide", 1.5, 1.6, 0.5, 0.55), show_hud=False, extra=darken(0.3),
        panel=("En memoria de las víctimas",
               "Recreación aproximada con datos publicados hasta el 29/10/2026: Ministerio de Transportes, Adif,"
               " RTVE, El País, elDiario.es, Cadena SER, El Mundo, El Español, 20minutos, Guardia Civil y el"
               " análisis de imágenes aéreas de Gareth Dennis\nTerreno: IGN/CNIG (PNOA, MDT05). Las causas las"
               " determinará la investigación oficial\n" + LICENCE), fout=20)
chapter("fin_corto", Still("S_wide", 1.5, 1.6, 0.5, 0.55), show_hud=False, extra=darken(0.3),
        panel=("En memoria de las víctimas",
               "Recreación aproximada con datos públicos a 29/10/2026. Las causas las determinará la investigación"
               " oficial\n" + LICENCE), fout=20)
END_SHORT = SEGS.pop()


def concat(segs, out):
    lst = out + ".txt"
    with open(lst, "w") as fh:
        for s in segs:
            fh.write(f"file '{os.path.abspath(s.path)}'\n")
    r = subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy",
                        "-movflags", "+faststart", out])
    if r.returncode:
        sys.exit("concat failed")
    print("OK", out, f"{sum(s.k for s in segs) / FPS:.1f} s", flush=True)


concat(SEGS, OUT)
# short cut under the 2:20 limit of non-Premium X accounts
keep = ["title", "resumen", "orden", "iryo_insiste", "aproximacion", "cabina", "impacto", "repeticion", "despues",
        "balance"]
short = [s for s in SEGS if s.name in keep] + [END_SHORT]
while sum(s.k for s in short) / FPS > 139 and len(short) > 3:
    for drop in ("iryo_insiste", "resumen", "balance"):
        if any(s.name == drop for s in short):
            short = [s for s in short if s.name != drop]
            break
    else:
        break
concat(short, OUT.replace(".mp4", "_corto.mp4"))
