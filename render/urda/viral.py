"""Short social edit (under 2:20): a hook, the 23 minutes from the LZB failure to the impact, open questions.

python viral.py <frames_dir> <stills_dir> <work_dir> <out.mp4>

Built for phones and muted autoplay: one idea per screen, large captions, the control-room audio as subtitles,
a big distance counter between the trains. Writes <out>.cues.json for sound.py, which builds the soundtrack.
"""
from common import *  # noqa: F401,F403

MARK = Image.new("RGBA", (W, H), (0, 0, 0, 0))
ImageDraw.Draw(MARK).text((W - 30, H - 34), "Reconstrucción aproximada · datos públicos a 29/10/2026 · @poco_me_parece",
                          font=font(22), fill=(255, 255, 255, 140), anchor="ra")
GREEN = (80, 200, 120)
CPS_V = 16  # captions are read on a phone, a bit slower than on a desktop
CUES = []   # sound events in seconds from the start of the film
T = [0.0]   # running start time of the next beat


def outlined(d, xy, text, f, fill=WHITE, anchor="la", stroke=3):
    d.text(xy, text, font=f, fill=fill, anchor=anchor, stroke_width=stroke, stroke_fill=(0, 0, 0))


def big_caption(title, sub):
    """Centred lower caption, readable on a phone screen."""
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if not title:
        return im, 0
    d = ImageDraw.Draw(im)
    ft, fs = font(62, True), font(40)
    lt = wrap(d, title, ft, W - 240)
    ls = wrap(d, sub, fs, W - 300) if sub else []
    h = 40 + len(lt) * 76 + len(ls) * 52 + 40
    for y in range(h + 80):
        d.line([(0, H - y), (W, H - y)], fill=(0, 0, 0, int(190 * min(1.0, (h + 80 - y) / 120))))
    y = H - h
    for ln in lt:
        outlined(d, (W / 2, y), ln, ft, anchor="ma")
        y += 76
    y += 8
    for ln in ls:
        outlined(d, (W / 2, y), ln, fs, fill=(225, 225, 225), anchor="ma", stroke=2)
        y += 52
    return im, h


def quote(who, text, width=1500):
    """One line of the published audio, as a big subtitle with the speaker on top."""
    name, col = WHO[who]
    tmp = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    lines = wrap(tmp, text, font(52, True), width - 80)
    h = 30 + 44 + len(lines) * 66 + 26
    im = Image.new("RGBA", (width, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, width - 1, h - 1], 20, fill=(6, 8, 12, 215), outline=col + (255,), width=4)
    d.text((width / 2, 22), name.upper(), font=font(30, True), fill=col, anchor="ma")
    y = 22 + 48
    for ln in lines:
        d.text((width / 2, y), ln, font=font(52, True), fill=WHITE, anchor="ma")
        y += 66
    return im


def versus():
    """What Atocha ordered against what the rules required, side by side."""
    w, h = 1560, 270
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for x0, col, head, big, small in ((0, RED, "LO QUE ORDENÓ ATOCHA", "Marcha normal", "hasta 200 km/h"),
                                      (800, GREEN, "LO QUE EXIGE LA NORMA SIN LZB", "Marcha a la vista",
                                       "máximo 40 km/h")):
        d.rounded_rectangle([x0, 0, x0 + 760, h - 1], 22, fill=(6, 8, 12, 225), outline=col + (255,), width=5)
        d.text((x0 + 380, 26), head, font=font(30, True), fill=col, anchor="ma")
        d.text((x0 + 380, 82), big, font=font(64, True), fill=WHITE, anchor="ma")
        d.text((x0 + 380, 172), small, font=font(56, True), fill=col, anchor="ma")
    return im


def questions(lines, width=1500):
    """The open questions, all on screen at once."""
    f = font(50, True)
    h = 40 + len(lines) * 92 + 20
    im = Image.new("RGBA", (width, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, width - 1, h - 1], 22, fill=(6, 8, 12, 215), outline=AMBER + (255,), width=4)
    for i, ln in enumerate(lines):
        d.text((60, 40 + i * 92), ln, font=f, fill=WHITE)
    return im


def hud2(m, show_gap=True):
    """Clock top left; distance between the trains and AVE speed top right; a strip of the line in between."""
    im = Image.new("RGBA", (W, 330), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for y in range(330):
        d.line([(0, y), (W, y)], fill=(0, 0, 0, int(170 * (1 - y / 330) ** 1.4)))
    outlined(d, (60, 36), clock_text(m), font(84, True), fill=AMBER)
    d.text((64, 136), "hora aproximada", font=font(26), fill=GREY)
    if m >= 30.5:
        x0, x1, ty = 600, 1260, 92
        X = lambda km: x0 + (km - 90.0) / (119.0 - 90.0) * (x1 - x0)  # noqa: E731
        d.line([(x0, ty), (x1, ty)], fill=(170, 176, 186, 255), width=6)
        for km, name in ((93, "Mora"), (118, "Urda")):
            outlined(d, (X(km), ty + 22), name, font(32, True), anchor="ma", stroke=2)
        sx = X(118.1)
        d.line([(sx, ty - 48), (sx, ty - 6)], fill=WHITE, width=3)
        d.ellipse([sx - 10, ty - 68, sx + 10, ty - 48], fill=RED)
        for km, col in ((iryo_km(m), IRYO_C), (ave_km(m), AVE_C)):
            x = min(max(X(km), x0 + 60), sx)
            d.rounded_rectangle([x - 60, ty - 30, x, ty - 8], 8, fill=col + (255,))
        outlined(d, (X(iryo_km(m)) - 30, ty - 76), "Iryo", font(30, True), fill=IRYO_C, anchor="ma", stroke=2)
        outlined(d, (min(max(X(ave_km(m)), x0 + 60), sx) - 30, ty + 64), "AVE", font(30, True), fill=AVE_C,
                 anchor="ma", stroke=2)
    gap = iryo_km(m) - ave_km(m)
    if show_gap and m >= 40.5 and gap > 0.005:
        txt = f"{gap:.1f} km" if gap >= 1 else f"{gap * 1000:.0f} m"
        outlined(d, (W - 60, 22), txt, font(96, True), anchor="ra", stroke=4)
        d.text((W - 60, 136), "entre el AVE y el Iryo parado", font=font(28, True), fill=WHITE, anchor="ra")
        v = ave_speed(m)
        if v > 0:
            outlined(d, (W - 60, 180), f"AVE a {v:.0f} km/h", font(44, True), fill=RED if v > 40 else WHITE,
                     anchor="ra")
            d.text((W - 60, 236), "límite sin LZB: 40 km/h", font=font(26), fill=GREY, anchor="ra")
    return im


def beat(name, bg, title="", sub="", clock=None, quotes=(), card=None, min_dur=0.0, realtime=None,
         hold_end=False, extra=None, fin=3, fout=3, show_gap=True, sound=(), boom_at=None):
    """One screen of the story. quotes: [(who, text)] shown one at a time. card: an image shown mid screen."""
    cap, capt_h = big_caption(title, sub)
    t = 0.4 + read_time(title, sub, base=0.3) * CPS / CPS_V
    shown = []
    for who, text in quotes:
        shown.append((t, quote(who, text)))
        t += 0.8 + len(text) / CPS_V
    card_t = None
    if card is not None:
        card_t = t if quotes else 0.6
        t = card_t + 4.0
    dur = max(min_dur, t + 0.6)
    if realtime is not None:
        dur = max(dur, realtime)
    if isinstance(bg, Frames) and realtime is None and bg.files:
        bg.slow = max(1.0, dur * FPS / len(bg.files))
    elif isinstance(bg, Frames) and realtime is not None:
        bg.hold_in = 0.0 if hold_end else max(0.0, dur - bg.motion())
    t0 = T[0]
    CUES.append({"t": t0, "type": "cut"})
    for s in sound:
        CUES.append({"t0": t0, "t1": t0 + dur, "type": s})
    if boom_at is not None:
        CUES.append({"t": t0 + boom_at(bg, dur), "type": "boom"})
    n = int(dur * FPS)
    seg = Seg(name)
    for k in range(n):
        tk = k / FPS
        im = (bg.at(tk, dur) if isinstance(bg, Still) else bg.at(tk)).convert("RGBA")
        if extra:
            im = extra(im, tk, dur)
        if clock:
            m = clock[1] - (dur - tk) / 60 if realtime is not None else clock[0] + (clock[1] - clock[0]) * tk / dur
            im.alpha_composite(hud2(m, show_gap), (0, 0))
        cur = [x for x in shown if x[0] <= tk]
        if cur:
            q0, q = cur[-1]
            im.alpha_composite(with_alpha(q, (tk - q0) / 0.3), ((W - q.width) // 2, H - capt_h - q.height - 60))
        if card_t is not None and tk >= card_t:
            y = (H - card.height) // 2 if not quotes else 360
            im.alpha_composite(with_alpha(card, (tk - card_t) / 0.3), ((W - card.width) // 2, y))
        im = Image.alpha_composite(im, cap)
        im = Image.alpha_composite(im, MARK)
        seg.put(fade(im, k, n, fin, fout))
    seg.close()
    T[0] += n / FPS


def black(name, text, sub="", dur=2.0):
    """Hard cut to black with one line, for the hook."""
    im = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    d = ImageDraw.Draw(im)
    d.text((W / 2, H / 2 - 50), text, font=font(84, True), fill=WHITE, anchor="mm")
    if sub:
        d.text((W / 2, H / 2 + 50), sub, font=font(44), fill=(220, 220, 220), anchor="mm")
    CUES.append({"t": T[0], "type": "hit"})
    seg = Seg(name)
    n = int(dur * FPS)
    for k in range(n):
        seg.put(fade(Image.alpha_composite(im, MARK), k, n, 1, 6))
    seg.close()
    T[0] += n / FPS


def cab_count(im, tk, dur):
    # the same timing model as the counter on top, written large in the middle of the windscreen
    m = IMPACT - (dur - tk) / 60
    left = max(0.0, (iryo_km(m) - ave_km(m)) * 1000)
    d = ImageDraw.Draw(im)
    outlined(d, (W / 2, 380), f"{left:.0f} m", font(150, True), fill=IRYO_C, anchor="ma", stroke=6)
    outlined(d, (W / 2, 550), "hasta el Iryo parado", font(44, True), anchor="ma")
    return im


def boom_in(scene_offset):
    # sound of the impact at the impact frame, after any hold in front of the footage
    return lambda bg, dur: bg.hold_in + scene_offset * bg.slow / FPS


# ------------------------------------------------------------------ the film
# J4 is the impact rendered at 3x frame density (scene frames 318-375, impact at 330)
hook = Frames("J4", slow=2.0)
beat("hook", hook, "Un AVE a unos 200 km/h contra un tren parado en la misma vía",
     "Urda (Toledo), 28 de octubre de 2026", realtime=hook.motion() * 0.55, fin=1, sound=("drone",),
     boom_at=boom_in((330 - 318) * 3))
black("pregunta", "69 muertos", "¿Cómo pudo pasar? Minuto a minuto")
beat("lzb", Frames("SIG"), "Cae el LZB, el sistema que frena automáticamente a los trenes",
     "Se cae su central en Urda. Seis trenes se detienen, entre ellos un AVE y un Iryo",
     clock=(30.0, 31.0), sound=("drone", "tick"))
beat("orden", Still("S_wide", 1.15, 1.35, 0.45, 0.5), "El centro de control de Adif ordena al AVE seguir", "",
     clock=(35.6, 36.2), sound=("drone", "tick"),
     quotes=[("ATOCHA", "«Reanude la marcha al amparo del BSL, con marcha normal»"),
             ("AVE", "«¿Con marcha normal?»"),
             ("ATOCHA", "«Sí»")], card=versus())
beat("iryo", Frames("ORB", 0, 200), "25 km más adelante, el Iryo está parado", "", clock=(40.6, 41.4), sound=("drone", "tick"),
     quotes=[("IRYO", "«Estoy detenida en la señal de entrada de Urda»"),
             ("ATOCHA", "«No le autorizamos el rebase»")])
beat("arranca", Frames("ORB", 200), "El AVE arranca y acelera hacia Urda", "Por la misma vía en la que está el Iryo",
     clock=(43.0, 46.0), min_dur=6, sound=("drone", "tick"))
beat("insiste", Still("S_iryo", 1.0, 1.15), "El Iryo vuelve a llamar: sigue parado",
     "Los audios publicados no recogen ningún aviso al AVE", clock=(48.0, 49.5), sound=("drone", "tick"),
     quotes=[("IRYO", "«No me está permitiendo el tren reiniciar el sistema LZB… estoy todavía detenida»"),
             ("ATOCHA", "«Vale, conforme… Y si tiene problemas, nos llama»")])
j1 = Frames("J1")
cab = Frames("CAB", 150)
beat("recta", j1, "El AVE entra en la recta de Urda a unos 200 km/h",
     "Un tren así necesita más de un kilómetro para frenar", clock=(52.0, IMPACT - cab.motion() / 60),
     realtime=j1.motion(), sound=("drone", "rumble"))
beat("cabina", cab, "", "", clock=(52.8, IMPACT), realtime=cab.motion(), show_gap=False, extra=cab_count,
     fout=1, sound=("rumble",))
j3 = Frames("J3")
beat("impacto", j3, "08:53 · El AVE alcanza al Iryo", "", realtime=j3.motion(), fin=1,
     boom_at=boom_in(330 - 301))
j4 = Frames("J4", slow=2.0)
beat("repeticion", j4, "A cámara lenta", "La cabeza del AVE destroza el último coche del Iryo",
     realtime=j4.motion(), boom_at=boom_in((330 - 318) * 3), sound=("wind",))
j5 = Frames("J5")
beat("despues", j5, "Tres coches del Iryo caen por el terraplén",
     "El resto del AVE descarrila hacia la vía de al lado", realtime=j5.motion() + 1.5, hold_end=True,
     sound=("wind",))
beat("balance", Still("S_close", 1.0, 1.1), "69 muertos",
     "50 heridos siguen ingresados, 15 en estado crítico (29 de octubre)", extra=darken(0.6), min_dur=5,
     sound=("wind",))
beat("preguntas", Still("S_top", 1.0, 1.08), "Lo que tendrá que aclarar la investigación",
     "Juzgado de Instrucción n.º 2 de Orgaz, con secreto de sumario", extra=darken(0.35), sound=("wind",),
     card=questions(["¿Por qué se ordenó «marcha normal» con el LZB caído?",
                     "¿Por qué no se detuvo al AVE tras los avisos del Iryo?",
                     "¿Por qué no lo frenó el ASFA, el sistema de respaldo?"]), min_dur=9)
beat("fin", Still("S_wide", 1.5, 1.6, 0.5, 0.55), "En memoria de las 69 víctimas",
     "Fuentes: Transportes, audios de Adif (RTVE, El País, SER) · Terreno © IGN · CC BY 4.0",
     extra=darken(0.3), min_dur=5, fout=24, sound=("wind",))

concat(SEGS, OUT)
json.dump({"duration": T[0], "cues": CUES}, open(OUT + ".cues.json", "w"), indent=1)
