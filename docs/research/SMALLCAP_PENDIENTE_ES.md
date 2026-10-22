# Small caps: lo que queda por probar (después de v27)

Revisión del 2026-10-22. Parte de lo ya hecho en v14-v27 (unas 50 familias de estrategias y más de 1 millón de configuraciones)
y de una búsqueda nueva en estudios y fuentes de brokers. Las cifras de fuentes externas son suyas, no nuestras.

## 0. Lo que ya sabemos (no repetir)

- Funciona en diseño y en la mitad de acciones nunca vista: cortos de small caps que suben con gap o en racha, mantenidos
  hasta el 3er cierre (COMBO26 Sortino 5,58; v27 B 2,58 en la mitad no vista; v27 A 4,24 con spreads reales).
- No funciona: ningún largo en small caps (v14-v25), cortos de varias semanas tras ampliaciones, contrasplits o avisos de
  exclusión, rotación y entradas escalonadas (v27 C), filtros de float y de "rally" (v26).
- Problema abierto: la cola. Trades de -89% a -473% y libros que se arruinan con costes altos.

## 1. Realismo del broker: lo más urgente (sin datos nuevos, barato)

| # | Prueba | Por qué | Dato |
|---|---|---|---|
| R1 | **Margen por acción en cortos baratos** | TradeZero International pide $2,50 por acción si el precio es menor de $2,50 (y $5 por acción en after-hours). TradeZero EE. UU. pide $5 por acción bajo $5 desde 2024-08-02. Un corto a $1,50 inmoviliza 167% de su valor, no 100%. Nuestros libros cuentan exposición por valor, no por margen | Páginas de soporte de TradeZero; ya tenemos los precios |
| R2 | **Coste de locate de equilibrio** | No sabemos el precio de los locates ni del pre-borrow. Calcular qué coste por trade (0,5%, 1%, 2%...) deja el libro por debajo de Sortino 2 dice cuánto podemos pagar | Trades de v26/v27 |
| R3 | **Auditoría de los 50 peores trades** | Ver a mano si hubo halts, contrasplits durante la posición, ticks erróneos o fills imposibles | Barras de Alpaca ya guardadas |
| R4 | **Halts LULD con la posición abierta** | Si la acción se para subiendo, el stop no se ejecuta y reabre más arriba. Comprobar que el modelo lo trata así | Minutos que faltan en las barras |
| R5 | **Cambios de reglas** | T+1 desde mayo de 2024; Nasdaq acelera exclusiones desde enero de 2025 (360 días máximo, sin plazo tras contrasplit). Medir si la ventaja cambia antes y después | Ya tenemos los datos |
| R6 | **Capacidad** | Repetir el libro con cuentas de $500k y $1M con los límites de liquidez | Ya tenemos los datos |

## 2. Escudo contra la cola con datos nuevos y gratuitos

| # | Prueba | Por qué | Dato |
|---|---|---|---|
| T1 | **Fallos de entrega (FTD) y lista de umbral de Reg SHO** | Una acción con muchos fallos de entrega tiene el préstamo tenso y más riesgo de squeeze. Nunca lo usamos como filtro | SEC, gratis desde 2004, dos veces al mes; listas diarias de Nasdaq/NYSE |
| T2 | **Interés en corto y días para cubrir** | La utilización alta es el mejor predictor de squeezes según los estudios del préstamo de acciones | FINRA, gratis dos veces al mes (cuánta historia hay que confirmarlo) |
| T3 | **Modelo de riesgo de squeeze** | Un modelo entrenado año a año sobre nuestros ~11.000 cortos que prediga la pérdida extrema y reduzca o salte el trade. Los filtros de reglas sueltas fallaron en v26; un modelo con T1 y T2 no se ha probado | Lo anterior + nuestros trades |
| T4 | **Régimen de "manía"** | Contar cada día cuántas small caps suben más del 50%. En oleadas (enero 2021, 2024, 2025) los squeezes van juntos. El filtro de régimen de v21 usaba el mercado, no esto | Ya tenemos los datos |

## 3. Eventos nuevos para cortos

| # | Prueba | Por qué | Dato |
|---|---|---|---|
| E1 | **Cuando se pueden vender las acciones de un PIPE** | Cuando la SEC da por efectivo el registro de reventa (formulario EFFECT), los inversores del PIPE pueden vender. CryptoQuant describe caídas hasta el precio del PIPE ("PIPE price gravity") | EDGAR: S-1/S-3 de reventa + EFFECT |
| E2 | **Tesorerías cripto (2025-2026)** | Más de 200 empresas anunciaron tesorerías cripto; muchas subieron y luego cayeron un 80-97%. VanEck llama a muchas "pump and dump". Muestra corta: riesgo de sobreajuste | 8-K + texto |
| E3 | **Fin del lock-up de OPVs pequeñas** | Estudios: -1% a -1,6% alrededor de la fecha, demasiado poco con costes en general; en microcaps puede ser más | Fecha de salida a bolsa + 180 días; prospecto |
| E4 | **OPVs pequeñas que se disparan (sobre todo asiáticas)** | FINRA y Nasdaq advirtieron de subidas del 2.000% que se dan la vuelta en días. Nuestros cortos de rachas las cubren solo en parte | Primer día de cotización + float del prospecto |
| E5 | **Post-fusión de SPAC** | Más acciones rescatadas antes de la fusión, peor rentabilidad después (Klausner, Ohlrogge y Ruan) | 8-K + rescates del proxy |
| E6 | **Cortos en pre-market y after-hours** | Todas nuestras entradas son en sesión. Entrar en pre-market, o en after-hours tras un cierre fuerte, no se ha probado. Ojo: TradeZero pide $5 por acción en after-hours | Almacén nocturno de v26 |
| E7 | **Acciones "de simpatía"** | Cuando sube el líder de un tema (IA, cuántica, nuclear, cripto), suben otras sin noticia propia; la atención se contagia y se desvanece rápido | Sector + subida simultánea |
| E8 | **Fecha límite de cumplimiento del precio mínimo** | Con la regla de 2025, sin plazo tras un contrasplit, las empresas cerca del límite tienen que ampliar o contrasplitear | Texto del 8-K 3.01 |

## 4. Largos de otro tipo (todos los largos intradía y de días fallaron)

| # | Prueba | Por qué | Dato |
|---|---|---|---|
| L1 | **Subida antes de la decisión de la FDA (PDUFA)** | Comprar 30-60 días antes de la fecha y vender la víspera, sin arriesgar el resultado. Muy citado por traders; la evidencia académica es poca | Búsqueda de texto de EDGAR ("PDUFA target action date") |
| L2 | **Factores mensuales de small caps** | Calidad, rentabilidad, empresas que no se diluyen (emisión neta, Fama-French 2008). Sortino esperado bajo pero poca correlación con los cortos: sirven para diversificar | XBRL de la SEC + acciones en circulación |
| L3 | **Rebote de enero de las perdedoras de diciembre** | Venta para perder impuestos; efecto debilitado y solo unos 10 eventos 2016-2026: poca potencia estadística | Ya tenemos los datos |

## 5. Validación que falta

| # | Prueba | Por qué |
|---|---|---|
| V1 | **Contraste con otro proveedor de datos** | Todo sale de Alpaca. Comparar los peores trades y los stops con Polygon o Databento (de pago) descarta ticks erróneos |
| V2 | **Datos nuevos** | Cada mes desde 2026-11 es la única muestra limpia que queda para estas familias |
| V3 | **Recuento total de pruebas** | DSR 0 en todo. Con millones de configuraciones acumuladas, cualquier resultado nuevo tiene que medirse contra ese número |

## 6. Descartado o imposible ahora

- Opciones como seguro de la cola: casi ninguna small cap de menos de $5 tiene opciones, y Alpaca solo tiene datos de opciones desde 2024.
- Subastas de cierre y desequilibrios: no hay datos gratuitos.
- Small caps de otros mercados (Canadá, Europa): no hay datos ni broker en el plan.
- Préstamo histórico real día a día: iBorrowDesk bloquea GitHub; solo el registrador de locates de TradeZero lo daría hacia delante.

## Fuentes

- TradeZero International, margen bajo $2,50: https://tradezero.com/support/questions/what-is-the-margin-requirement-for-shorting-stocks-under-2-50-tradezero-international
- TradeZero EE. UU., margen bajo $5: https://tradezero.com/en-us/support/questions/what-is-the-margin-requirement-when-shorting-a-stock-under-usd5-00-are-these-stocks-marginable
- SEC, datos de fallos de entrega: https://www.sec.gov/data/foiadocsfailsdatahtm
- FINRA, interés en corto: https://www.finra.org/finra-data/browse-catalog/equity-short-interest/data
- Evidence Investor, consecuencias de los short squeezes: https://www.evidenceinvestor.com/post/the-consequences-of-short-squeezes
- Nasdaq, exclusión acelerada (2025): https://www.gunder.com/en/news-insights/blogs/public-ventures/nasdaq-accelerates-delisting-of-sub-dollar-stocks-including-after-reverse-stock-splits ; https://securities-law-blog.com/2025/02/11/nasdaq-finalizes-amendments-to-accelerate-delisting-process/
- Tesorerías cripto: https://www.mexc.com/news/110610 ; https://www.theblock.co/post/358123/micro-caps-planning-xrp-or-sol-treasuries-probably-scams-vaneck-says ; https://architectpartners.com/wp-content/uploads/2025/06/06-06-25-Crypto-Public-Companies-Snapshot.pdf
- Lock-ups: https://thesis.eur.nl/pub/60187/Bachelor-Thesis-Final-Version-498076ll.pdf ; https://research.cbs.dk/en/studentProjects/abnormalities-surrounding-nordic-ipo-lock-up-expiration-an-event-/
- OPVs con subidas extremas: https://www.businesstoday.in/amp/markets/ipo-corner/story/us-regulator-warns-of-pump-and-dump-ipos-many-from-china-353267-2022-11-18
- SPAC: https://openaccess.nhh.no/nhh-xmlui/handle/11250/3018402
- Contagio de atención: https://aisel.aisnet.org/amcis2020/data_science_analytics_for_decision_support/data_science_analytics_for_decision_support/24/
- PDUFA: https://digitalcommons.colby.edu/honorstheses/672 ; https://store.traders.com/stcov29455pr.html
- Emisión neta: https://www.johnhcochrane.com/s/fama_french_dissecting_anomalies_JF.pdf
- Efecto enero: https://ojs.aut.ac.nz/applied-finance-letters/article/download/615/164
