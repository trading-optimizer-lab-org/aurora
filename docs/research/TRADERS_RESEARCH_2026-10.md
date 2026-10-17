# Traders e inversores con mejor historial: qué se puede automatizar

*2026-10-17 · 20+ fuentes · Confianza: media (muchos historiales no están auditados)*

## Resumen

Los mejores historiales verificados son de personas cuyo método **no se puede copiar con reglas fijas y precios diarios**: Simons (modelos cuantitativos secretos, intradía), Druckenmiller y Soros (macro discrecional), Lynch y Greenblatt (análisis de empresas). Entre los traders de acciones que sí publican reglas (Minervini, O'Neil, Kullamägi, Stockbee, Clenow, Darvas), los tests independientes sin sesgo de supervivencia muestran que **solo una pieza conserva ventaja clara: el "Episodic Pivot"** (comprar una acción que abre con un hueco de +10% o más con volumen enorme, sobre todo tras resultados). El resto se queda en el nivel del índice o por debajo tras costes.

## 1. Quién tiene el mejor historial

| Persona | Resultado | Periodo | Verificación | ¿Reglas fijas? |
|---|---|---|---|---|
| Jim Simons, Medallion | 66% bruto / 39% neto al año | 1988-2018 | Libro de Zuckerman, cifras del fondo ([Visual Capitalist](https://www.visualcapitalist.com/growth-of-100-invested-in-jim-simons-medallion-fund/)) | No: secreto, alta frecuencia |
| Joel Greenblatt, Gotham | 50% al año | 1985-1994 | Auditado según su libro ([Brooklyn Investor](http://brklninvestor.com/gothPerf.php)) | Parcial: "fórmula mágica" |
| Stanley Druckenmiller | ~30% al año, ningún año negativo | 1981-2010 | Cifras de fondo ([granitefirm](https://www.granitefirm.com/blog/us/2023/01/11/irr-of-investment-masters/)) | No: macro discrecional |
| George Soros, Quantum | ~29-32% al año | 1969-2000 | Cifras de fondo ([The Daily Economy](https://thedailyeconomy.org/article/jim-simons-and-his-quants/)) | No |
| Peter Lynch, Magellan | 29,2% al año | 1977-1990 | Datos CRSP del fondo ([Wikipedia](https://en.wikipedia.org/wiki/Peter_Lynch)) | No: análisis de empresas |
| Warren Buffett | ~20% al año | 1965-2024 | Público | No |
| Campeones del U.S. Investing Championship (cuentas reales verificadas por el organizador) | Minervini +155% (1997) y +334,8% (2021); J Law +353,9% (2024) y +252,3% (2025); Martin Luk +969,8% (2025); Oliver Kell +941,1% (2020); David Ryan, 3 títulos en los 80 | 1983-2025 | Extractos de broker, un año cada vez ([USIC por año](https://completetradersedge.com/us-investing-championship/), [Business Wire 2021](https://www.businesswire.com/news/home/20220124005241/en/2021-United-States-Investing-Championship-Winners-Minervini-Smashes-Record)) | Sí en parte: todos son de la escuela de momentum (O'Neil, Minervini, Kullamägi) |
| Kristjan Kullamägi (Qullamaggie) | Dice que >100 M$ | 2013-2021 | Solo capturas propias, sin auditar ([TickerGuard](https://tickerguard.com/articles/qullamaggie-backtest-study)) | Sí: 3 setups publicados |

Ojo con el sesgo de supervivencia también aquí: el campeonato publica a los ganadores. En los 10 primeros meses de 2022 solo el 8% de los participantes estaba en positivo ([Business Wire](https://www.businesswire.com/news/home/20221128005230/en/United-States-Investing-Championship-Ten-Month-Results)).

## 2. Lo que dicen los tests independientes de cada método

| Método | Test independiente | Resultado |
|---|---|---|
| **Episodic Pivot** (Kullamägi / Stockbee): hueco ≥10% al abrir, volumen ≥3x, acción "aburrida" antes | TickerGuard, 9.262 acciones de EEUU 1975-2026 **incluyendo las desaparecidas** | **+3,89% por operación** (2.843 operaciones), acierto 48%. Con resultados trimestrales: +4,8% y 55% de acierto. Cartera desde 1993: 15,6%/año frente a 10,8% del S&P 500 ([estudio](https://tickerguard.com/articles/qullamaggie-backtest-study), [reglas](https://tickerguard.com/stocks/scanner/qullamaggie-ep-original)) |
| Breakout de Kullamägi | Mismo estudio | +0,79% por operación tras costes, mediana -1,37%: casi nada |
| EP "9 millones de acciones" de Stockbee | Ney Torres, 2018-2026, sin sesgo de supervivencia, pre-registrado | A ciegas pierde; con filtro de resultados nunca supera al S&P 500 ([artículo](https://whatworksintrading.substack.com/p/the-9-million-share-episodic-pivot)) |
| Momentum burst 4% (Stockbee) | Datos de India | ~0,9% de media a 5 días, acierto 47% ([Substack](https://tikamalma.substack.com/p/4-momentum-burst-detailed-research)) |
| Clenow "Stocks on the Move" | S&P 500 punto a punto 2006-2025 | 9,2%/año frente a 10,4% del SPY; ventaja solo en 2008 ([Quanterlab](https://quanterlab.com/research/clenow-s-stocks-on-the-move-tested-apart-ten-years-after-the-book), [Edge Lab](https://www.lifelongedge.com/lab/pub/clenow-momentum/index.html)) |
| Darvas Box | 375 acciones | Reduce caídas, pero solo bate a mantener en el 12% de los casos ([bethepuck](https://bethepuck.com/guides/darvas-box/)) |
| Fórmula mágica de Greenblatt | Tesis de Erasmus 1987-2021 | Alfa hasta 2009; ninguna desde 2010 ([tesis](https://thesis.eur.nl/pub/65582/MasterThesis_MartijnKreft_474788.pdf)) |
| Máximo de 52 semanas (George y Hwang 2004) | Réplica fuera de muestra 2002-2024 | 0,1%/mes, no significativo ([réplica](https://dmurav.com/replications/releases/v2026-09-06/reports/paper-4ce600986423.pdf)) |
| Minervini / O'Neil mecánico | Nuestro estudio (PR #394) | Sortino 0,25-1,06 frente a 1,59 del SPY en 2011-2020 |

## 3. Evidencia académica de fondo

- **Deriva tras resultados (PEAD)**: es la anomalía más antigua, pero se ha debilitado mucho desde los 2000. Lo que sí ha aumentado es la reacción de los primeros días tras el anuncio ([Columbia](https://business.columbia.edu/sites/default/files-efs/imce-uploads/CEASA/Events%20Page/PEAD_Declined_over_time.pdf), [revisión de Fink](https://static.uni-graz.at/fileadmin/sowi/Working_Paper/2020-04_Fink.pdf)). Encaja con que el Episodic Pivot funcione mejor tras resultados.
- **Saltos de precio**: hasta el 40% del efecto PEAD viene de saltos puntuales ([Chen y Jiang, SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2156621)).
- **Momentum y 52 semanas**: existen, pero tras costes son débiles en la mayoría de mercados ([Liu et al. 2011](https://ideas.repec.org/a/eee/jimfin/v30y2011i1p180-204.html)).

## 4. Conclusión práctica

1. Lo que hacen los campeones es **momentum concentrado más mucho criterio humano** (qué base es buena, cuándo apretar). Las reglas mecánicas captan la parte de momentum, que ya está bastante arbitrada.
2. El único candidato con ventaja demostrada sin sesgo de supervivencia es el **Episodic Pivot tras resultados**. Aun así, su cartera hace 15,6%/año, y de ahí no sale un Sortino de 2: depende de pocas operaciones gigantes (el 5% de las mejores da el 80% del beneficio).
3. Para probarlo bien necesitamos **fechas de resultados de todas las empresas, incluidas las desaparecidas**. Gratis existe: los índices de EDGAR de la SEC listan cada 8-K (punto 2.02, "resultados") con su fecha desde 2004. Lo que falta son los precios de las empresas desaparecidas, que siguen sin estar disponibles gratis. Los EP se dan sobre todo en empresas pequeñas, que es justo donde más falta en nuestros datos.

## Metodología

Búsquedas en Exa y la web sobre: historiales verificados (USIC, fondos), reglas publicadas (Kullamägi, Stockbee, Clenow, Darvas, Greenblatt) y tests independientes y académicos (PEAD, 52 semanas, fórmula mágica). Lectura completa de las páginas de resultados del USIC, del estudio de TickerGuard y del de Clenow. Lo que no está auditado se marca como tal.
