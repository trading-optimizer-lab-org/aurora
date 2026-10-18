# Kristjan Kullamägi (Qullamaggie): cómo operaba y qué se puede probar

Investigación del 2026-10-18. Fuentes al final. Lo que no está verificado por terceros se marca.

## 1. Quién es y qué está verificado

- Sueco (Estocolmo). Empezó en 2011 con ~5.000 $ ahorrados como vigilante nocturno en el edificio de Nasdaq
  Estocolmo; quemó 3 cuentas antes de que la cuarta (9.100 $ en mayo de 2013) despegara ([Deep Dive][dd],
  [Excess Returns][er]).
- **Lo más fiable son sus declaraciones de impuestos suecas (públicas)**, recopiladas por James Muninn
  ([Deep Dive][dd]): ingreso de trading tributable 2014 353 mil $ · 2015 261 mil · 2016 457 mil · 2017 1,5 M ·
  2018 1,2 M · 2019 1,2 M · **2020 33 M · 2021 42 M · 2022 -26 M**. Pico de cuenta ~105 M$ en noviembre de 2021 y
  caída de ~60 M$ hasta mediados de 2022 (entrevista de *Market Wizards: The Next Generation*).
- Su diario mensual 2013-2019: +783%, +1.536%, +110%, +287%, +1.004%, +96% por año; 18 de 74 meses negativos; peor
  mes -30%; caída máxima de la curva 2014-2019 -32,7% ([Deep Dive][dd]). Él dice CAGR 2013-2019 de 268%, acierto
  del 25% en 2019 y su mayor caída un 50% en 2014 ([FAQ][faq]).
- Conclusión: el historial es real en orden de magnitud (impuestos), aunque no auditado operación a operación.

## 2. Cómo operaba de verdad (1.325 operaciones registradas en sus directos, 2019-2023)

Estadísticas públicas de Muninn ([Deep Dive][dd]); la base de datos completa es de pago (215 $) y **no se compró**.

| Dato | Valor |
|---|---|
| Stop mediano | ruptura 2,5% · EP 3,8% · corto parabólico 3,5% |
| Hora de entrada | 63% en los primeros 15 minutos; mediana el minuto 10 |
| Tamaño mediano de posición | 9,7% de la cuenta (broker 2014-2018) |
| Riesgo real por operación | mediana 0,24% de la cuenta (p75 0,39%) |
| Posiciones cerradas en verde | 31% (broker 2014-2018) |
| Posiciones nuevas por día activo | 3,1 de media, máximo 11 |
| Modelo "salir al cerrar bajo la SMA10" sobre 906 rupturas y EP | 37% se paran el mismo día; las ganadoras duran ~10 días; ninguna perdedora pasa de 12 |

Lo que él dice ([FAQ][faq]): arriesga 0,3-0,5% por operación, rara vez más del 1%; posiciones de 5-25% (la
mayoría 10-15%); no más del 20% en una acción; stops de mercado; sale sin pensar si salta el stop.

Mejores y peores operaciones verificadas por el broker (2014-2018): cortos en APT y LAKE (ébola, oct-2014)
+43 mil y +15 mil $; GBTC +40 mil $ (dic-2017); el peor, corto en CNET (sep-2014) -45 mil $ y TLRY (ago-2018)
-35 mil $. Ejemplo documentado de ruptura: **NVAX, 15-jun-2020**, entrada 47,60 $, stop 45,90 $ (3,6%), bandera
alta tras subir mucho; con salida en la SMA10 habría ganado +214% (+60R) en 40 días ([Deep Dive playbook][ddp]).
Errores famosos: corto accidental en KODK (-1,5 M$), GME (-900 mil $ el 25-ene-2021) y la devolución de ~60 M$ en
2022 por estar apalancado al alza en el techo.

## 3. Sus reglas escritas

### Selección de acciones ("scans")

- Las acciones que más suben: el **1-2% mejor por subida de 1, 3 y 6 meses** ([3 setups][s3]). En TC2000 usa
  `100*(C/C21-1)`, `C/C63`, `C/C126` ([Laws of Swing][laws]).
- **ADR** (rango medio diario, 20 sesiones, `media(H/L)-1`) ≥ 3,5% en las versiones de sus scans ([TickerGuard
  scanner][tgs], [Deepvue][dv]); "ADR > 5% para cuentas pequeñas" ([Laws of Swing][laws]); en 2017 usaba 2,2%
  ([vídeo de scans][scan]).
- **Volumen en dólares** medio ≥ 1,5 M$ ([vídeo de scans][scan], [TickerGuard scanner][tgs]).
- Le gustan las salidas a bolsa recientes ([vídeo de scans][scan]).

### Ruptura (su setup principal) ([3 setups][s3])

1. Gran subida en los últimos 1-3 meses (30-100% o más).
2. Retroceso ordenado y consolidación de 2 semanas a 2 meses, con **mínimos crecientes y rango que se estrecha**,
   "surfeando" las medias de 10 y 20 días (la de 10 por encima de la de 20).
3. Entrada al **romper el máximo del rango de apertura** (vela de 1, 5 o 60 minutos). Stop en el **mínimo del día**,
   nunca más ancho que el ADR.
4. **Vender 1/3 a 1/2 a los 3-5 días**, subir el stop a la entrada y seguir el resto hasta el **primer cierre bajo la
   SMA10** (o la SMA20 si la acción es más lenta).

### Episodic Pivot (EP) ([3 setups][s3], [EP][ep])

1. **Hueco al alza ≥ 10%** con volumen enorme (idealmente su volumen medio diario en los primeros 15-20 minutos).
2. Mejor si hay sorpresa en beneficios y si la acción **no ha subido en los 3-6 meses previos**.
3. Entrada en el máximo del rango de apertura, stop en el mínimo del día (máximo 1-1,5 ADR); seguir con la SMA10/20
   (o 20/50).

### Corto parabólico ([3 setups][s3])

1. Subida de 50-100% en días o semanas (grandes) o 300-1.000% (pequeñas), **3-5 días seguidos al alza**.
2. Corto al perder el mínimo del rango de apertura o al fallar en el VWAP; stop en el máximo del día.
3. Objetivo: las medias de 10 y 20 días.

### Filtro de mercado

- "No compres rupturas cuando las medias de 10 y 20 días bajan" ([entrevista][tvm]). En sus directos: semáforo
  con el **QQQ/Nasdaq: SMA10 por encima de la SMA20 y las dos subiendo** ([notas de directo][sn]).

## 4. Lo que ya se ha probado de forma independiente

[TickerGuard][tg] (sin sesgo de supervivencia, 9.262 acciones, 1975-2026, entrada al romper, stop en el mínimo
del día, mitad a 3 días, resto con la SMA20, 0,2% de coste por lado):

- **EP: +3,89% por operación** (2.843 operaciones), mediana -0,31%.
- **Ruptura: +0,79%** (1.557), mediana -1,37%; con subida previa ≥ 70% y máximo de 120 días, +1,34%.
- Cartera (0,5% de riesgo, máximo 5 posiciones) desde 1993: **15,6%/año frente a 10,8% del S&P 500**. El 5% de
  mejores operaciones aporta el 80% de la ganancia.

Muninn, con sus entradas reales (2019-2022): +1,2 a 1,5R por operación; seguir con la SMA20 da +1,47R frente a
+1,18R con la SMA10; con 1% de riesgo por operación la caída llega al 51% (ver X_PROFILES_REVIEW_2026-10.md).

En nuestros grids v1-v7 ya había versiones aproximadas: `S2` (ruptura "Qulla") y `S5` (EP), siempre con entrada
al cierre y stops/salidas genéricos. Lo nuevo aquí es probar **sus reglas literales**: su selección de acciones,
la entrada al romper, el stop en el mínimo del día limitado al ADR, su forma de vender y su filtro de mercado.

## 5. Lo que no se puede reproducir con datos diarios

- La entrada intradía (rango de apertura de 1-5 minutos) y el volumen de la apertura: se aproxima con la ruptura
  del nivel en el día (precio = máximo entre la apertura y el nivel) o con la entrada al cierre.
- Si el mínimo del día ocurrió antes o después de entrar: con datos diarios el stop en el mínimo del día nunca salta
  el primer día. Él se paraba el mismo día en ~37% de los casos, así que la aproximación es optimista.
- Fechas de resultados y sorpresas de beneficios (no tenemos esos datos), préstamo de acciones para cortos, y su
  criterio discrecional.
- Nuestros datos solo tienen acciones que sobreviven hoy: favorecen a las compras y perjudican a los cortos.

## Fuentes

1. [3 TIMELESS setups that have made me TENS OF MILLIONS][s3]: sus reglas de ruptura, EP y corto parabólico.
2. [FAQ de qullamaggie.com][faq]: riesgo, tamaño, acierto, cuentas, fórmula del ADR.
3. [How to master a setup: Episodic Pivots][ep]: definición de EP y stop máximo de 1-1,5 ADR.
4. [Qullamaggie Deep Dive (Muninn), estadísticas][dd] y [playbook][ddp]: impuestos, diario, 1.325 operaciones.
5. [TickerGuard: Qullamaggie Backtest][tg] y [scanner][tgs]: test independiente y scans formalizados.
6. [Vídeo "My scanning process and scans" (2017)][scan]: filtros de precio, volumen en dólares y ADR.
7. [Qullamaggie's Laws of Swing][laws]: recopilación de reglas de sus directos.
8. [Notas de directo, 1-dic-2023][sn]: filtro de mercado con medias de 10 y 20 días.
9. [Entrevista en Trading vs Myself][tvm]: "no compres rupturas con las medias bajando".
10. [Deepvue: hilo de scans][dv]: AS > 97, ADR > 3,5%, 1,5 M$.
11. [Excess Returns: lecciones de Market Wizards][er]: su historia en el libro de Schwager.

[s3]: https://qullamaggie.com/my-3-timeless-setups-that-have-made-me-tens-of-millions/
[faq]: https://qullamaggie.com/faq/
[ep]: https://qullamaggie.com/how-to-master-a-setup-episodic-pivots
[dd]: https://app.qullamaggiedeepdive.com/stats
[ddp]: https://app.qullamaggiedeepdive.com/playbook
[tg]: https://tickerguard.com/articles/qullamaggie-backtest-study
[tgs]: https://tickerguard.com/stocks/scanner/qullamaggie-top-gainers-1m
[scan]: https://www.youtube.com/watch?v=nm8iNDjHRoE
[laws]: https://studylib.net/doc/27055345/qullamaggie%E2%80%99s-laws-of-swing
[sn]: https://tradingresourcehub.substack.com/p/qullamaggie-stream-notes-1-december
[tvm]: https://tradingvsmyself.com/kristjan-kullamagi-interview-breakouts-and-returns/
[dv]: https://en.rattibha.com/thread/1857785838647627893
[er]: https://excessreturnspod.substack.com/p/walk-on-water-five-lessons-from-jack
