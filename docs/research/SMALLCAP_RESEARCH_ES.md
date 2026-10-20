# Small caps: qué dicen los estudios, qué hacen los traders y qué vamos a probar (v16)

Investigación del 2026-10-20, después de v14 (B8 gap fade: Sortino 4,85 con costes medios) y mientras corre v15.
Fuentes al final; las cifras son de cada fuente, no nuestras.

## 1. Lo que dicen los estudios

| Tema | Hallazgo | Fuente |
|---|---|---|
| Gaps de +50% en microcaps (2020-2024, 3.133 casos) | Se dan la vuelta durante el día; más cuanto mayor el gap y menor la liquidez; los costes y la dificultad de ponerse corto limitan el beneficio | Syvälahti 2026 (Aalto) |
| Gaps nocturnos en general (2011-2024) | Lo que sube de noche devuelve parte durante el día, más en pequeñas e ilíquidas; tras spreads y comisiones el beneficio neto es negativo | Tesis Turku 2026 |
| Noticia frente a sin noticia | Los movimientos sin noticia se dan la vuelta; los movimientos con noticia continúan (sobre todo las malas noticias y en empresas pequeñas) | Chan 2003 (JFE); Jiang, Li y Wang 2018 |
| Efecto lotería (MAX) | Las acciones con la mayor subida diaria del mes rinden poco el mes siguiente; entre ellas, las perdedoras de la semana rebotan +1,66% la semana siguiente | Bali, Cakici y Whitelaw 2011; Chen y otros 2025 |
| Compras en masa de Robinhood | Las más compradas cada día rinden de media -4,7% en 20 días | Barber, Huang, Odean y Schwarz 2022 (JF) |
| Ampliaciones directas tras subir +50% en 5 días (108 casos, 2021-2026) | Mediana -46% a 20 días y -56% a 60 días | Microcap Ledger 2026 |
| Contrasplits en microcaps (1.183 casos) | Mediana -38% a 60 sesiones y -72% a un año | Microcap Ledger 2026 |
| Avisos de exclusión de bolsa (8-K 3.01) | Mediana -65% frente a IWM en un año | Microcap Ledger 2026 |
| Programas de venta de acciones (ATM) | Mediana -11,6% frente a IWM en 20 sesiones | Microcap Ledger 2026 |
| Mucho corto con pocos prestamistas | -2,15% al mes las restringidas | Asquith, Pathak y Ritter 2005 |
| Días para cubrir el corto | Mejor predictor que el % de corto: +1,2% al mes en largo-corto | Hong y otros (NBER) |
| Cortos de minoristas | Predicen caídas: +9% al año imitándolos, sobre todo en pequeñas | Kelley y Tetlock 2017 (RFS) |

**La lección clave para los cortos:** en estas acciones la mediana cae mucho, pero la media mucho menos, porque unas pocas se multiplican. Una cartera en corto cobra la media, no la mediana. Si además se paga préstamo durante semanas, se come el beneficio. Por eso nuestros cortos de varios días tras ampliaciones (B13) o avisos de exclusión (B14) salieron mal, y el corto **intradía** (B8) bien: dentro del día no se paga préstamo y el stop corta la cola de las que explotan.

## 2. Lo que hacen los traders conocidos (descripciones suyas, no pruebas)

- **Ross Cameron (largos, "gap and go"):** precio entre $2 y $20, float pequeño (menos de 10-20 millones de acciones), volumen relativo de 5 veces o más, noticia del día; entra en rupturas y en "micro pullbacks" (1-3 velas rojas de 1 minuto tras una subida, compra al romper el máximo de la vela de retroceso).
- **Tim Sykes:** su favorita es el *morning panic dip buy*: un valor que lleva 5-10 días subiendo cae un 20-50% por la mañana y se compra el rebote. También vende en corto el *first red day* y el *supernova* (subidas de varios cientos por cien).
- **Steven Dux (cortos):** filtra antes por capitalización, float, volumen pre-market y rotación del float. Cortos en gap-up, en el rebote y en el primer día rojo; evita biotecnológicas y energía.
- **Blogs con backtests:** cortar todos los gaps de más del 50% con más de $200k de volumen pre-market, cerrando al final del día con un stop ancho, "funciona" según un autor, pero no publica las cifras.

## 3. Ideas que probaremos en v16 (pre-registradas, rejillas pequeñas, los mismos placebos y walk-forward)

**Cortos (intradía o con préstamo calibrado de IBKR):**
1. B8 separando **con noticia / sin noticia** (8-K ese día o la víspera): según los estudios, las que suben sin noticia se dan más la vuelta.
2. B8 según si la empresa tiene **capacidad de ampliar** (S-3 o 424B recientes): más riesgo de dilución, más caída.
3. B8 según si es la **primera vez** que se dispara o es repetidora.
4. **Parabólico:** el precio se aleja un 30-50% del VWAP; corto en el primer máximo más bajo y cierre en el VWAP.
5. **Backside:** tras caer un 15-25% desde el máximo del día, corto cuando falla el rebote.
6. **Gap a la baja que sigue cayendo:** corto al romper el mínimo de los primeros 5 minutos, con la regla SSR aplicada.
7. **Día 2 de un gap que se dio la vuelta:** corto en la apertura siguiente.
8. **Pico de minoristas:** volumen fuera de bolsa (FINRA) disparado con subida de +30%; corto de 5-10 días.
9. **Ampliación tras subida de +50%:** corto 20-60 días, posiciones pequeñas y muchas a la vez.
10. **Contrasplit:** corto de 20-60 días.
11. **Aviso de exclusión de bolsa:** corto largo (60-120 días) con posiciones pequeñas.

**Largos:**
12. Gap and go **solo con noticia**.
13. **Morning panic dip** (Sykes): el día después de un gran corredor, caída del 20-35% por la mañana; compra del rebote.
14. **Red to green:** el día 2 abre por debajo del cierre anterior y lo recupera.
15. **Micro pullback** en los primeros 30 minutos (Cameron).
16. **Ruptura de máximos por la tarde** en un corredor que sigue en verde a las 14:00.
17. **Rebote semanal de lotería** (MAX): comprar las perdedoras de la semana entre las de mayor subida diaria del mes.
18. **Volumen en corto bajo frente a alto** (FINRA): carteras semanales.
19. **Deriva tras noticia:** comprar al día siguiente de una subida de +10-20% con 8-K y mantener 5 días; y corto con malas noticias.

## Fuentes

- Syvälahti (2026), *Intraday price reversals after extreme run-ups in U.S. microcap stocks*, Aalto University: https://aaltodoc.aalto.fi/items/5b3e64f3-8b86-4808-b9ea-1e47fd21aa24/full
- *Overnight Returns and Intraday Reversals: Evidence from U.S. Equities* (2026), University of Turku: https://www.utupub.fi/items/094ffc24-ca98-482d-bd18-a469ca028791
- Chan (2003), *Stock price reaction to news and no-news*, JFE: https://www.sciencedirect.com/science/article/abs/pii/S0304405X03001466
- Jiang, Li y Wang (2018), *News Momentum*: https://www.villanova.edu/content/dam/villanova/VSB/faculty-and-research/academic-departments/finance-and-real-estate/mid-atlantic-research-conference-in-finance/past-conference-papers/marc/marc2018/SSRN-id2667658.pdf
- Lou, Polk y Skouras, *A Tug of War: Overnight Versus Intraday*: https://conference.nber.org/confer/2015/APf15/Lou_Polk_Skouras.pdf
- Barber, Huang, Odean y Schwarz (2022), *Attention-Induced Trading and Returns: Evidence from Robinhood Users*, JF: https://onlinelibrary.wiley.com/doi/10.1111/jofi.13183
- Chen, Cohen, Liang y Sun, *Maxing Out Short-term Reversals in Weekly Stock Returns*: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4622831
- Baars y Mohrschladt (2021), *An alternative behavioral explanation for the MAX effect*: https://ideas.repec.org/a/eee/jeborg/v191y2021icp868-886.html
- Bali, Hirshleifer, Peng, Tang y Wang, *Social Interactions and Lottery Stock Mania*, NBER: https://www.nber.org/papers/w29543
- Microcap Ledger (2026), ampliaciones directas: https://microcapledger.com/research/registered-direct-offerings-discount-returns/ ; contrasplits: https://microcapledger.com/research/what-happens-after-reverse-split/ ; ATM: https://microcapledger.com/research/atm-offering-announcement-stock-returns/ ; índice: https://microcapledger.com/research/
- DilutionTracker, *Offerings, Investment Bank Tiers and Why It Matters for Small Cap Stocks*: https://knowledge.dilutiontracker.com/en/articles/5722415-offerings-investment-bank-tiers-and-why-it-matters-for-small-cap-stocks
- Asquith, Pathak y Ritter (2005), *Short interest, institutional ownership, and stock returns*: https://economics.mit.edu/sites/default/files/publications/Short%20Interest,%20Institutional%20Ownership.pdf
- Hong, Li, Ni, Scheinkman y Yan, *Days to Cover and Stock Returns*, NBER: https://www.nber.org/system/files/working_papers/w21166/w21166.pdf
- Kelley y Tetlock (2017), *Retail Short Selling and Stock Prices*, RFS: https://academic.oup.com/rfs/article-abstract/30/3/801/2682978
- Jiang, Liu, Schrowang y Xu (2023), *Short Squeezes*, FAJ: https://www.tandfonline.com/doi/full/10.1080/0015198X.2023.2284625
- FINRA, ficheros diarios de volumen en corto: https://www.finra.org/finra-data/browse-catalog/short-sale-volume-data/daily-short-sale-volume-files
- Engelberg, Sasseville y Williams (2011), *Market Madness? The Case of Mad Money*: https://doi.org/10.1287/mnsc.1100.1290
- Suomela (2024), *Momentum gap and go*: http://theseus.fi/handle/10024/875321
- Stonks Capital, *The Science of Shorting*: https://stonkscapital.substack.com/p/the-science-of-shorting-using-backtesting
- Tradezella, estrategias de corto en small caps: https://www.tradezella.com/strategies/small-cap-short-strategy ; first red day: https://www.tradezella.com/strategies/first-red-day ; parabolic: https://www.tradezella.com/strategies/parabolic-short-strategy
- Day Trading Toolkit, *The First Red Day Strategy*: https://daytradingtoolkit.com/strategies/first-red-day-short-strategy
- Quantamental Trader, *High Float Turnover Trading Manual* (Cameron y Dux): https://quantamentaltrader.substack.com/p/high-float-turnover-trading-manual
- Benzinga, entrevista a Steven Dux: https://benzinga.com/z/14300909
- Tim Sykes, *When to dip buy vs not*: https://timothysykes.com/blog/when-to-dip-buy-vs-not-dip-buy/ ; Business Insider: https://www.businessinsider.nl/stock-trader-high-returns-millionaire-students-shares-top-trading-patterns-2023-6/
- TradingView, *Micro Pullback Entry System*: https://in.tradingview.com/script/K0f6aI3t-Micro-Pullback-Entry-System
