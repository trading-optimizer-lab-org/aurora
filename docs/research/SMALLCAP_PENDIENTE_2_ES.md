# Small caps: lo que queda por probar (después de v46)

Revisión del 2026-10-29. Parte del inventario de v14-v46 y de tres búsquedas nuevas: setups de cortos, forma de
operar y documentación de TradeZero. La lista anterior, SMALLCAP_PENDIENTE_ES.md, quedó casi entera hecha en v28.
Las cifras de fuentes externas son suyas, no nuestras.

## 0. Lo nuevo y más importante: la API de TradeZero

Verificado en developer.tradezero.com el 2026-10-29:

| hecho | fuente | consecuencia |
|---|---|---|
| "Fully unattended systems that trade without your ongoing control are outside the scope of the current agreement" | about-tradezero | un bot 100% desatendido con el PC apagado queda fuera del acuerdo de la API. Hay que preguntarlo a TZ por escrito o mantener control humano |
| POST /order solo acepta Market, Limit, Stop y StopLimit. MOC y LOC salen en /routes pero no se pueden enviar | trading, api-conventions | no hay orden a la subasta de cierre. Las entradas al cierre de NS y ON1 y todas las salidas al cierre del book suponen esa subasta |
| AtTheOpening sí existe: Market o Limit, envío de 04:00 a 09:25, sin cancelar tras el corte | trading | las entradas a la apertura de DS1 y RU se pueden enviar |
| Market y Stop solo en sesión regular. Fuera de ella solo Limit y StopLimit con Day_Plus o GTC_Plus | trading | no hay stop a mercado de noche ni en premarket |
| La API no da datos de mercado | about-tradezero | el bot necesita otra fuente para decidir al cierre |
| Locates: oferta válida 30 s, 1 cotización por segundo, rechazo bajo $0,50 (R40). Precios de ejemplo $0,01-0,03 por acción | locates, rate-limits | el locate se cobra por acción: en una acción de $1,50 son 2% a $0,03 |
| Cuentas con apalancamiento: 2:1 desde las 15:45 y al cierre; una posición, como mucho 50% del poder de compra | soporte TZI | las entradas al cierre suben la exposición justo cuando el límite aprieta |
| Bajo $2 "solo efectivo" según una página; otra permite cortos bajo $1 con $2,50 por acción | soporte TZI | regla contradictoria: confirmar con TZ |

Inferencia: el book se probó con subastas de apertura y de cierre. La de cierre no existe en la API. Y NS decide con
el precio de cierre que solo se conoce a las 16:00. v46 ya mostró que entrar a mercado a las 15:51 o 15:55 da lo
mismo o algo más. Falta probar todo lo demás del cierre.

## 1. Forma de operar real en TradeZero (lo más urgente)

Todo con datos que ya tenemos (barras de 1 minuto de v43) en el motor de v43/v46.

| # | prueba | qué mide |
|---|---|---|
| O1 | **Decidir NS y ON1 a las 15:50** con el precio de las 15:50, no con el cierre, y entrar a mercado a las 15:55 | quita el uso del cierre para decidir una entrada al cierre |
| O2 | **Salir al cierre sin subasta**: a mercado a las 15:55 o con límite entre 15:50 y 15:59 | todas las salidas al cierre del book; nunca probado |
| O3 | **Stops como StopLimit** con el límite al 2, 5 y 10% del disparo | si no se llena, la posición sigue abierta; mide ese riesgo en los gaps |
| O4 | **Locate por acción**: $0,01 / $0,02 / $0,03 / $0,05, en vez de un % del valor | castiga las acciones baratas; quizá cambia qué tramo de precios conviene |
| O5 | **Precio mínimo**: quitar los trades bajo $0,50, $1, $2 y $2,50 | rechazo R40, regla de solo efectivo y margen de $2,50 por acción |
| O6 | **Límite 2:1 a las 15:45** con las posiciones abiertas a precio de mercado, más el tope de 50% por posición | si el book lo cumple o si las entradas al cierre lo rompen |
| O7 | **Días SSR**: quitar las entradas en días con SSR, o exigir un límite por encima del bid | la regla de precio de la SEC para cortos tras una caída del 10% |
| O8 | **Locates no disponibles**: quitar al azar 10, 25 y 50% de los trades HOT y HTB | sin datos de inventario, mide cuánto aguanta el book si no hay acciones para tomar prestadas |
| O9 | **Días sin aprobación**: perder al azar 5, 10 y 20% de los días de órdenes | por si el bot tiene que esperar a que el dueño confirme cada día por el acuerdo de la API |
| O10 | **Precio de decisión de una fuente gratis**: último precio de IEX (Alpaca, gratis) a las 15:50 frente al SIP | v29 midió IEX para miembros intradía; esto es solo una foto a las 15:50 |
| O11 | **Contadores de liquidación de v43**, sin verificar por el fallo del fork | que la regla del broker de verdad no saltó nunca |

Esto no busca subir la mediana. Busca saber si los $22k aguantan con las reglas reales de TZ. Es un run pequeño:
unas pocas decenas de variantes sobre el mismo book.

## 2. Estrategias nuevas con evidencia y datos gratis

| # | idea | regla | evidencia | dato | estado |
|---|---|---|---|---|---|
| S1 | **IPO pequeña que se dispara y se da la vuelta** | corto cuando la subida del día 1 o 2 de una IPO pequeña, sobre todo extranjera, gira a la baja | FINRA 22-25: suben al abrir o en los primeros días y caen al precio de salida o por debajo | EDGAR + barras diarias | la familia IPO de v28 nunca se evaluó por la regla de actividad. Probarla con una regla para eventos raros |
| S2 | **Vuelta a cotizar tras una suspensión de la SEC** | corto el primer día tras levantarse la suspensión, si subió antes | Duke FinReg: unas 3.000 suspensiones de 2012 a 2019; la mayoría pierde casi todo en 20 sesiones | lista gratis de la SEC | no consta probada; pocas se pueden operar luego |
| S3 | **Dimisión del auditor** (8-K, punto 4.01) | corto al día siguiente, 2 a 5 días | Wells 1993: rentabilidad significativamente negativa | EDGAR | no consta probada; v28 probó otros 8-K. Barato |
| S4 | **Promoción pagada** | corto tras el pico de volumen sin noticia; 2 a 5 días | Frieder y Zittrain: -5,5% en 2 días tras el pico | volumen diario como sustituto | parecida a las rachas de subida; poco nuevo |
| S5 | **Atención en StockTwits, Reddit, Robinhood o Google** | corto el tercio de más atención | Cookson et al.: -87 pb en 20 días; Barber et al.: -4,7% en 20 días | registros de la API de StockTwits parados; Reddit no comercial; Google sin API | **descartado ahora**: no hay fuente gratis viable |
| S6 | **Coste del préstamo como señal** | corto las de préstamo más caro | Engelberg et al.: 1,17% al mes | no hay histórico gratis | **más tarde**: con el registro de locates de TZ hacia delante |
| S7 | **Bajas del Russell, MAX, día de la semana, fin de mes** | varias | débil o mixta | gratis | baja prioridad: pocos eventos o ya probado en parte (v14, v28) |

## 3. Tamaño y cartera

| # | prueba | evidencia | estado |
|---|---|---|---|
| P1 | **Tamaño por nombre inverso a su volatilidad**, por ejemplo 1/ATR | Maillard et al. 2010 | v39 recortó por volatilidad; comprobar si era por nombre o del book |
| P2 | **Umbral neto de préstamo**: saltar el trade si su ventaja esperada no cubre el locate por acción | Muravyev, JF 2025: el préstamo se come las anomalías en microcaps | depende de O4 |
| P3 | **Kelly con límite de caída** sobre el bootstrap | Busseti, Ryu y Boyd 2016 | los tamaños ya se barrieron en v32, v38 y v39; poco margen |
| P4 | Ranking con ML cuando los límites aprietan | Gu, Kelly y Xiu 2020 | **descartado**: los límites nunca aprietan (v35) |
| P5 | Coberturas con puts de IWM, VIX o TNA largo | puts del índice: -2,17% al año; TNA solo cubre la beta, no un squeeze | **descartado** para $5k |

## 4. Validación que sigue abierta

- Datos nuevos desde 2026-11: la única muestra limpia.
- Registro diario de cotizaciones de locate con la API de TZ, sin operar: da el coste real del supuesto más sensible
  (con HOT al 5% la mediana baja de $22k a $16k).
- Una muestra de los peores trades contra otro proveedor de datos.
- Corregir los fallos de diseño de v46: ventanas más cortas que el calentamiento del indicador y la dimensión de
  cierre antes de la apertura. Valor bajo.

## 5. Orden propuesto

1. **v47, la operativa real de TradeZero**: O1-O11 en un run. Decide si el book es operable tal como está.
2. **Eventos raros**: S1-S3, con una regla de actividad para eventos poco frecuentes.
3. P1-P2, cuando O4 diga cuánto cuesta de verdad el locate.

## Fuentes

- TradeZero, acuerdo de la API y servicios: https://developer.tradezero.com/docs/documentation/about-tradezero
- TradeZero, tipos de orden, TIF y horarios: https://developer.tradezero.com/docs/documentation/trading
- TradeZero, convenciones y tipos aceptados: https://developer.tradezero.com/docs/documentation/api-conventions
- TradeZero, locates: https://developer.tradezero.com/docs/documentation/locates
- TradeZero, límites de llamadas: https://developer.tradezero.com/docs/documentation/rate-limits
- TradeZero International, margen: https://tradezero.com/support/questions/what-are-your-margin-requirements-tradezero-international
- TradeZero International, restricciones: https://tradezero.com/support/questions/are-there-any-restrictions-or-rules-for-trading-tradezero-international
- SEC, regla de precio para cortos (SSR): https://www.sec.gov/rules-regulations/staff-guidance/trading-markets-frequently-asked-questions-7
- FINRA 22-25, IPO pequeñas: https://www.finra.org/rules-guidance/notices/22-25
- SEC, suspensiones de cotización: https://www.sec.gov/enforcement-litigation/trading-suspensions
- Duke FinReg, suspensiones 2012-2019: https://sites.duke.edu/thefinregblog/2021/02/10/regulatory-enforcement-in-otc-markets/
- Frieder y Zittrain, Spam Works: https://cyber.harvard.edu/publications/2007/Spam_Works
- Cookson, Lu, Mullins y Niessner, The Social Signal: https://www.runi.ac.il/media/ysnjixw4/social-signal.pdf
- Barber, Huang, Odean y Schwarz, Robinhood: https://onlinelibrary.wiley.com/doi/10.1111/jofi.13183
- Engelberg et al., coste del préstamo: https://www.cxoadvisory.com/short-selling/stock-loan-fee-as-return-predictor/
- Muravyev, préstamo y anomalías, JF 2025: https://onlinelibrary.wiley.com/doi/10.1111/jofi.13501
