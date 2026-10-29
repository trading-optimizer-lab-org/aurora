"""Chronological documentary edit: every minute from 07:54 to 08:53 told over the 3D scene.

python assemble.py <frames_dir> <stills_dir> <work_dir> <out.mp4>

frames_dir holds the rendered sequences J1..J5 (v3) and SIG, ORB, CAB (v4 extra shots).
A heads-up band (clock, both trains on a strip of the line, AVE speed) stays on screen until the impact.
"""
from common import *  # noqa: F401,F403

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
cab = Frames("CAB", 150)
chapter("aproximacion", j1,
        "08:52 · El AVE llega a la recta de Urda a unos 200 km/h",
        "El Iryo está parado unos cientos de metros más adelante",
        clock=(52.6, IMPACT - cab.motion() / 60), realtime=j1.motion())
chapter("cabina", cab,
        "Los últimos segundos, desde el frontal del AVE",
        "Recreación. Con el LZB apagado, nada frena el tren de forma automática",
        clock=(52.8, IMPACT), realtime=cab.motion(), fout=4,
        extra=cab_overlay)
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
