"""Assemble rendered frames into the final MP4 with captions.

python assemble.py <frames_dir> <work_dir> <out.mp4>
"""
import os
import subprocess
import sys

FR, WORK, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
os.makedirs(os.path.join(WORK, "cap"), exist_ok=True)
os.makedirs(os.path.join(WORK, "seg"), exist_ok=True)
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

CAPS = {
    "J1": ["08:30 - Cae el sistema LZB por una avería informática en Urda y se detienen 6 trenes",
           "08:38 - El Iryo 6076 (147 personas) queda parado ante una señal a la entrada de Urda"],
    "J2": ["08:36 - El control de Adif autoriza al AVE 2080 (397 pasajeros) a seguir en marcha normal",
           "Debía circular en marcha a la vista, a 40 km/h, según el Ministerio de Transportes"],
    "J3": ["08:53 - Alcance en el PK 118, junto a la estación de Urda (Toledo)",
           "Velocidad del AVE: unos 200 km/h según el ministro (pendiente de los registradores)"],
    "J4": ["Repetición a cámara lenta x3",
           "La cabeza del AVE se incrusta en la cola del Iryo. Un carril atraviesa un coche del AVE"],
    "J5": ["64 fallecidos (40 en el Iryo y 24 en el AVE) y 58 heridos hospitalizados",
           "Balance provisional del 28/10/2026. 544 personas viajaban en los dos trenes"],
}


def cap(name, text):
    p = os.path.join(WORK, "cap", name + ".txt")
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text)
    return p


def dt(path, font, size, x, y, extra=""):
    return (f"drawtext=fontfile='{font}':textfile='{path}':fontsize={size}:fontcolor=white:"
            f"x={x}:y={y}:line_spacing=14{extra}")


def run(args):
    r = subprocess.run(["ffmpeg", "-loglevel", "error", "-y"] + args)
    if r.returncode:
        sys.exit(f"ffmpeg failed: {args}")


ENC = ["-c:v", "libx264", "-preset", "slow", "-crf", "16", "-pix_fmt", "yuv420p", "-r", "30"]
seg = lambda n: os.path.join(WORK, "seg", n + ".mp4")  # noqa: E731

t1 = cap("title1", "Reconstrucción 3D aproximada")
t2 = cap("title2", "Choque por alcance entre el AVE 2080 (Renfe) y el Iryo 6076\n"
                   "Urda (Toledo) · 28 de octubre de 2026 · 08:53")
e1 = cap("end1", "En memoria de las víctimas")
e2 = cap("end2", "Recreación ilustrativa basada en información preliminar publicada el 28/10/2026\n"
                 "(Ministerio de Transportes, RTVE, El Mundo, elEconomista, AP, Guardia Civil\n"
                 "y análisis de imágenes aéreas del ingeniero ferroviario Gareth Dennis).\n"
                 "Terreno y vegetación: IGN/CNIG (PNOA, MDT05). Posiciones, velocidades y daños son aproximados.\n"
                 "La causa la determinará la investigación oficial.")
for name, (a, b), dur in (("title", (t1, t2), 5), ("end", (e1, e2), 8)):
    vf = ",".join([dt(a, BOLD, 78, "(w-text_w)/2", "h/2-170"), dt(b, FONT, 42, "(w-text_w)/2", "h/2-30"),
                   f"fade=in:0:15,fade=out:{dur * 30 - 20}:20"])
    run(["-f", "lavfi", "-i", f"color=c=0x0b0b0d:s=1920x1080:d={dur}:r=30", "-vf", vf] + ENC + [seg(name)])

brand = cap("brand", "RECONSTRUCCIÓN APROXIMADA")
order = ["title"]
for j in ("J1", "J2", "J3", "J4", "J5"):
    a, b = cap(j + "a", CAPS[j][0]), cap(j + "b", CAPS[j][1])
    d = os.path.join(FR, j)
    n = len([f for f in os.listdir(d) if f.endswith(".png")])
    vf = ",".join([
        "noise=alls=3:allf=t",
        "drawbox=x=0:y=ih-200:w=iw:h=200:color=black@0.45:t=fill",
        dt(a, BOLD, 42, 80, "h-172", ":enable='gte(t,0.4)'"),
        dt(b, FONT, 34, 80, "h-108", ":enable='gte(t,0.4)'"),
        dt(brand, FONT, 24, "w-text_w-36", 30),
        f"fade=in:0:8,fade=out:{max(0, n - 8)}:8",
    ])
    run(["-framerate", "30", "-start_number", "1", "-i", os.path.join(d, "f_%04d.png"), "-vf", vf] + ENC + [seg(j)])
    order.append(j)
order.append("end")
lst = os.path.join(WORK, "seg", "list.txt")
with open(lst, "w") as fh:
    for o in order:
        fh.write(f"file '{o}.mp4'\n")
run(["-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", "-movflags", "+faststart", OUT])
print("OK", OUT)
