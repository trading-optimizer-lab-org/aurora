# Ideas comprobables sacadas de X (2026-10-17)

Fuentes: @Muninn, @FelipeGuirao, @SteveDJacobs, @ohiain, @Gaurav_Cx10, @UnTalNixon_exe y @SJosephBurns. Ninguna está auditada. No las descartamos por eso: cada una es una **hipótesis que podemos probar con nuestros datos**. Al lado de cada una va de dónde viene y qué evidencia trae.

## A. Filtros (qué acciones mirar)

| # | Idea | Fuente y evidencia que aporta | Cómo la probamos |
|---|---|---|---|
| A1 | **Solo acciones de los grupos industriales más fuertes.** El 50% mejor de industrias por fuerza relativa (RS) mejora todas las estrategias y el 50% peor las empeora. Cuanto más alto el corte, mejor: RS de industria ≥50 da +4,5 puntos al año, ≥85 da +7,5 y ≥95 da +13,1 (falla un año) | @SteveDJacobs, [tuit 1](https://x.com/SteveDJacobs/status/2068645279163666892) y [tuit 2](https://x.com/SteveDJacobs/status/2068813333851984308): "más de 300 estrategias, 16/16 años 2011-2026, sin parámetros ajustados". Ojo: mide la **subida máxima** de cada operación, no lo que se gana al salir | Tenemos la industria de cada acción. Cada semana, RS de la industria = mediana del RS de sus acciones. Aplicarlo como filtro a todas las candidatas y mirar la diferencia año a año |
| A2 | **Volatilidad diaria (ADR) alta**: ≥4-5%. "Las acciones de ADR bajo son para gente que odia el dinero" | Qullamaggie, vía @Muninn. Volatilidad mediana de lo que compran: Qullamaggie 6,5%, Zanger 4,4%, Minervini 3,2%. @Gaurav_Cx10 dice que le fue mucho mejor con ADR alto | Filtro de ADR de 20 días ≥4% |
| A3 | **Etapa 2**: a menos de un 10-20% del máximo de 52 semanas, +30% en 3 meses, medias subiendo, velas estrechas | @Gaurav_Cx10; Weinstein vía @SJosephBurns (precio sobre una media de 30 semanas que sube, ruptura con +40-50% de volumen) | Ya hecho en parte en el PR #394; probarlo combinado con A1 y A2 |
| A4 | **Fundamentales CAN SLIM / Minervini**: beneficio por acción +25% interanual y acelerando; +25% anual 3 años; ROE ≥17%; ventas +15-25%; RS ≥80-90 | [@SJosephBurns](https://x.com/SJosephBurns/status/2055935852354637891). @Muninn lo probó en 4.048 grandes subidas (2010-2026): un criterio ayudaba de forma constante, dos lo empeoraban y solo 61 de 908 pasaban los siete | Necesita beneficios con fecha de publicación de la SEC (gratis desde 2009). Es un estudio aparte |
| A5 | **Los mejores trades de Qullamaggie** (≥5R) tenían: subida previa constante (no un pico al final), último mes tranquilo (<2 ADR), sin hueco grande esa mañana, y QQQ subiendo menos de un 5% en el mes | @Muninn, 89 trades reales | Filtros extra sobre las rupturas |

## B. Entradas

| # | Idea | Fuente | Cómo |
|---|---|---|---|
| B1 | **Ruptura al cierre** (Felipe Guirao): primera subida de la tendencia; EMAs 8>20>50; ≥7 velas de consolidación sin cerrar bajo la EMA 20; vela de ruptura más grande que la de ayer y cerrando en el 21% superior de su rango; stop en el mínimo del día (≤2,5 ADR); comprar al cierre | [@FelipeGuirao](https://x.com/FelipeGuirao/status/2092277607920447750): dice ~100%/año desde 2020 y 50% CAGR en su backtest desde 1995. Reconoce que en 2025-26 cuesta mucho más | Todo se puede calcular con precios diarios, salvo su indicador "CML". Lo sustituimos por "EMAs apiladas y subiendo" y lo dejamos dicho |
| B2 | **Retroceso con poco volumen a EMAs de 9/21 que suben** | [@ohiain](https://x.com/ohiain/status/2105379087065956743) | Entrada: el precio toca la EMA 9 o 21 que sube, con volumen bajo la media; compra al cierre siguiente si cierra por encima del máximo del día anterior |
| B3 | **Momentum burst**: rango estrecho más volumen agotado sobre la EMA 21; entrar el día 1 de la subida (+4%) | @Gaurav_Cx10, Stockbee | Ruptura del 4% con volumen mayor que ayer |
| B4 | **Huecos de +10% tras resultados** | @Muninn: comprar a ciegas los 2.985 de 2016-2024 da **+0,001R**. Choca con TickerGuard (+3,9%) | Solo con filtros (A1, A2, A5), nunca a ciegas |

## C. Salidas y tamaño

| # | Idea | Fuente y evidencia |
|---|---|---|
| C1 | Seguir con la **media de 20 días** mejor que con la de 10: +1,47R frente a +1,18R por operación | @Muninn, 800+ rupturas de Qullamaggie |
| C2 | Vender la mitad a los 3 días: acierto del 24% al 35% y peor racha de 31R a 20R, a cambio de un 25% menos de beneficio | @Muninn |
| C3 | **Mantener 5 días exactos** ("nada lo supera") | @FelipeGuirao, 13.000 señales |
| C4 | Salir si no avanza en 2-3 días; vender el 50% al subir | @Gaurav_Cx10 |
| C5 | **Arriesgar 0,25-0,5% por operación**, no 1%. Caída máxima del 16% al 0,25%, del 30% al 0,5% y del 51% al 1% | @Muninn sobre las entradas reales de Qullamaggie |

## D. Filtro de mercado

| # | Idea | Fuente |
|---|---|---|
| D1 | **Media de 10 días del índice > media de 20**: la más simple y de las que mejor salió | @Muninn (31 reglas de amplitud probadas; solo 10 superan al ruido) |
| D2 | Amplitud: nº de acciones en tendencia perfecta, alcistas frente a bajistas (<1 = bajista); nuevos máximos menos nuevos mínimos con EMAs 8/20 | @FelipeGuirao: dice que reduce la caída un 63% |

## E. Datos

- @UnTalNixon_exe recomienda **TradingView-API**: una conexión no oficial por websockets a los datos de TradingView. Vale para precios actuales, **no** para empresas desaparecidas. Usarla podría ir contra las condiciones de uso de TradingView. No la usamos.

## Estudio propuesto (pre-registrado antes de mirar resultados)

Un solo estudio de "momentum swing" que combine lo que más se repite en las fuentes. 4 candidatas, todas con D1 + A1 (RS de industria ≥50) + A2 (ADR ≥4%), riesgo de 0,5% por operación y costes de 10 pb:

1. **B1 + C3**: ruptura al cierre y salida a los 5 días (Felipe).
2. **B1 + C1**: ruptura y seguimiento con la media de 20 días (Qullamaggie/Muninn).
3. **B2 + C1**: retroceso a EMAs que suben (ohiain).
4. **B3 + C4**: momentum burst con salida rápida (Gaurav/Stockbee).

Además, cada candidata se mide **con y sin el filtro de industria A1**, para comprobar lo que dice Steve Jacobs. Mismos periodos que el PR #394: entrenamiento 1995-2010, validación 2011-2020, 2021+ cerrado. Mismo ajuste por sesgo de supervivencia.
