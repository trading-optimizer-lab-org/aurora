# Ranking de traders de acciones (de mejor a peor)

*2026-10-17 · solo traders de acciones · 30+ fuentes*

## Cómo se ordena

Cada trader recibe una nota según tres cosas, por este orden:

1. **Verificación**: A = auditoría, declaración de impuestos o documentos del fondo revisados por terceros. B = concurso con cuenta real o prensa que vio los extractos. C = solo lo dice él.
2. **Duración**: cuántos años seguidos. Un año brillante pesa poco.
3. **Rentabilidad y tamaño**: ganar 30% al año con miles de millones vale más que 300% con 20.000 $.

Fuera del ranking quedan los que no operan acciones como trader: macro (Druckenmiller, Soros, Tudor Jones), inversores a largo plazo (Buffett, Lynch, Greenblatt) y Simons, cuyo fondo es multiactivo y secreto.

## Ranking

| # | Trader | Historial | Años | Verif. | Estilo | ¿Se puede automatizar con precios diarios? |
|---|---|---|---|---|---|---|
| 1 | **Steve Cohen** (SAC Capital) | ~29-30% al año **neto** con comisiones de 3% + 50%; un solo año negativo (2008, -19%) | 1992-2013 (22) | A: documentos del fondo ([PBS Frontline](https://www.pbs.org/wgbh/frontline/article/chart-of-the-day-the-sac-advantage/), [Reuters](https://www.reuters.com/article/business/cohens-sac-ends-life-as-hedge-fund-with-double-digit-returns-idUSBRE9BU0FN/)) | Trading de corto plazo (2-30 días) alrededor de noticias y resultados, apalancado ~4x ([Ritholtz](https://ritholtz.com/2010/03/sac-30-gains-annually-for-18-years/)) | **No.** Parte del rendimiento venía de información privilegiada: la firma se declaró culpable ([Bloomberg](https://www.bloomberg.com/news/articles/2018-02-01/steve-cohen-needs-to-prove-himself-to-wall-street-all-over-again)) |
| 2 | **BNF** (Takashi Kotegawa, Japón) | 1,6 M¥ a ~18.000 M¥ (≈13.600 $ a 153 M$) | 2000-2008 (8) | A/B: mostró su certificado de impuestos a una revista y lo entrevistó TV Tokyo ([KING 2007](https://kabushiki-blog.com/article/55172229.html), [Elite Trader](https://www.elitetrader.com/et/threads/bnf-from-1-6-million-yen-13-600-to-18-billion-yen-153-million-in-8-yrs.128299/)). El error de J-Com le dio unos 2.000 M¥, una parte pequeña | En mercado bajista compraba acciones muy por debajo de su media de 25 días y vendía con +2-3% en 1-7 días. En mercado alcista, comprar lo fuerte ([reglas](https://kabushiki-blog.com/article/18401857.html)) | **Sí, en parte.** Un test de 36 años en Japón, con empresas desaparecidas incluidas, saca 14% al año, Sharpe 1,25 y caída máxima -25% en la versión adaptativa ([toushi-strategy](https://toushi-strategy.com/backtest/bnl_ma_kairi1/)) |
| 3 | **Richard Driehaus** | ~30% al año en sus primeros 12 años; fondo de small caps +196,6% en 1999 | 1980s-1990s | A/B: fondos regulados; elegido en el "All-Century Team" de Barron's ([AAII](https://www.aaii.com/journal/article/momentum-investing-the-richard-driehaus-way), [Wikipedia](https://en.wikipedia.org/wiki/Richard_Driehaus)) | Momentum más sorpresas de beneficio en small caps | Parcial: necesita sorpresas de beneficio. El filtro de AAII que lo imita hizo 1.324% en 1999-2018 frente a 372% del S&P 500, con -42,7% en 2008 |
| 4 | **Mark Minervini** | 220% al año durante 5,5 años (33.500% en total) con un solo trimestre negativo; campeón USIC en 1997 (+155%) y 2021 (+334,8%) | 1994-2000 y 2021 | A/B: Schwager publica el periodo 1994-2000. 2021 auditado por Warren Averett CPA ([minervini.com](https://www.minervini.com/68543/), [Business Wire](https://www.businesswire.com/news/home/20220124005241/en/2021-United-States-Investing-Championship-Winners-Minervini-Smashes-Record)) | SEPA: tendencia, bases que se estrechan (VCP), stops del 7-8% | Mal: nuestra versión mecánica (PR #394) rinde menos que el SPY |
| 5 | **Chris Kacher** y **Gil Morales** | Kacher +18.000% (1996-2002, verificado por KPMG). Morales +10.904% (1998-2005, auditado por Rothstein Kass) | 6-7 | A, según su bio y su libro en Wiley ([Townhall bio](https://townhall.com/author/gilmoralesandchriskacher)) | CAN SLIM de O'Neil, operando la cuenta de la propia firma | Mal: misma familia que Minervini |
| 6 | **Sean Ryan** | 7 de 7 años en positivo en el USIC; +6.232% acumulado frente a 205% del S&P 500 | 2019-2025 (7) | B: concurso con cuenta real ([USIC](https://completetradersedge.com/us-investing-championship/)) | Escuela O'Neil, como su padre David Ryan | Mal (misma familia) |
| 7 | **David Ryan** | Campeón USIC 3 veces: +161%, ~+160%, +100% o más. 43.000 $ a 295.000 $ en 2 años | 1985-1987 | B: [LA Times 1987](https://www.latimes.com/archives/la-xpm-1987-03-01-fi-6876-story.html) | CAN SLIM | Mal (misma familia) |
| 8 | **Ross Cameron** | 583 $ a 18,8 M$ de ganancias | 2017-2025 (9) | A: extractos de broker auditados ([Warrior Trading](https://www.warriortrading.com/ross-camerons-verified-day-trading-earnings/)). Conflicto: vende cursos | Day trading intradía de small caps que suben con noticias | **No:** necesita datos minuto a minuto |
| 9 | **Kristjan Kullamägi** (Qullamaggie) | ~5.000 $ (2011) a más de 100 M$ (dice); +352% en 2013 | 2013-2021 | C: solo sus capturas y directos, sin auditoría ([TickerGuard](https://tickerguard.com/articles/qullamaggie-backtest-study), [Vinny Stone](https://vinnystone.com/qullamaggie-on-the-early-days-of-his-trading-journey/)) | Breakouts, Episodic Pivots y cortos en subidas parabólicas | **El Episodic Pivot, sí:** +3,9% por operación en un test sin sesgo 1975-2026. El breakout, apenas |
| 10 | **Dan Zanger** | 10.775 $ a 18 M$ en 18 meses | 1998-1999 | A/B: Fortune vio su declaración de impuestos de 1999 (14,2 M$ de plusvalías) ([Fortune 2000](https://money.cnn.com/magazines/fortune/fortune_archive/2000/12/18/293117/index.htm)) | Patrones gráficos y ruptura con volumen, en la burbuja puntocom | Mal: un solo periodo excepcional |
| 11 | **CIS** (Japón) | ~3 M¥ a 16.000-25.000 M¥ (dice); 6.000 M¥ netos en 2013 | 2001-2015 | B/C: Bloomberg vio extractos con 4.400-4.800 M¥ líquidos, mucho menos de lo que afirma ([Complete Trader's Edge](https://completetradersedge.com/cis-japanese-day-trader-nikkei-futures/), [WaPo](https://www.washingtonpost.com/business/meet-cis-japans-market-moving-enigma-who-can-make-millions-of-yen-in-his-pajamas/2014/10/21/e11b3c88-588c-11e4-bd61-346aee66ba29_story.html)) | Momentum intradía, mucho en futuros del Nikkei | No: intradía y apalancado |
| 12 | **J Law** (Law Wai-Sum) | USIC, cuentas de más de 1 M$: +353,9% (2024) y +252,3% (2025, récord) | 2 | B: [USIC 2024](https://www.tmcnet.com/usubmit/2025/01/27/10136701.htm) | Alumno de Minervini | Mal (misma familia) |
| 13 | **Martin Luk** | USIC: +283% (2024) y +969,8% (2025, récord); acierto del 22-25% | 2 | B ([Substack](https://tradingresourcehub.substack.com/p/martin-luk-283-usic-2024-key-lessons)). Él mismo dice que todavía no es constante | Qullamaggie con stops muy ajustados | Parcial (como Kullamägi) |
| 14 | **Oliver Kell** | USIC 2020: +941,1% | 1 | B | CAN SLIM, "ciclo de precio" | Mal |
| 15 | **Nicolas Darvas** | Decía 2 M$ en los años 50 | 1957-1959 | **Investigado**: Nueva York solo pudo verificar unos 216.000 $ ([Investopedia](https://www.investopedia.com/articles/trading/07/darvas-box.asp)) | "Cajas" y ruptura | Test: rara vez bate a mantener ([bethepuck](https://bethepuck.com/guides/darvas-box/)) |
| 16 | **Jesse Livermore** | Ganó y perdió fortunas; quebró varias veces | 1900-1940 | C: anécdotas | Tendencia y especulación | No hay datos fiables |

## Lo que enseña el ranking

1. **Los dos primeros con más historial verificado no son de momentum de rupturas.** Cohen operaba noticias y resultados con información que no se puede comprar (y en parte ilegal). BNF compraba caídas exageradas en mercado bajista y momentum en alcista.
2. **La escuela O'Neil / Minervini domina los concursos**, pero los concursos solo enseñan a los ganadores. En 2022 solo el 8% de los participantes iba en positivo.
3. **Dos métodos de la lista tienen tests independientes sin sesgo de supervivencia y salen bien:**
   - **Rebote corto de BNF** (comprar lo que está muy por debajo de su media, vender en 1-5 días): Sharpe 1,25 durante 36 años en Japón. Es la única cifra encontrada que se acerca a lo que buscamos.
   - **Episodic Pivot de Kullamägi**: +3,9% por operación, pero depende de pocas operaciones enormes.

## Siguiente estudio propuesto

Versión EEUU del rebote corto de BNF, con reglas escritas antes de mirar los datos:
- Caída anormal respecto a la media de 10-25 días, medida contra la propia historia de cada acción.
- Umbral más exigente cuando el mercado está bajista.
- Salida en 1-5 días.

Como solo dura días, el sesgo de empresas desaparecidas pesa menos que en estrategias de meses. Aun así está ahí, porque se compran acciones que se han hundido: el test lo medirá limitándose a las acciones más grandes y líquidas.

## Solo los que superan el 100% anual compuesto

La rentabilidad anual compuesta se calcula a partir del capital inicial y final publicados (`(final/inicial)^(1/años) - 1`).

| # | Trader | Anual compuesto | Multiplicó por | Años | Verif. |
|---|---|---|---|---|---|
| 1 | BNF | 221% | x11.250 | 8 | A/B |
| 2 | Mark Minervini (1994-2000; además +334,8% auditado en 2021) | 188% | x336 | 5,5 | A/B |
| 3 | Chris Kacher | 123% | x181 | 6,5 | A |
| 4 | Ross Cameron (empezó con 583 $, lo que infla el %; day trading) | ~217% | 583 $ a 18,8 M$ | 9 | A |
| 5 | David Ryan | 139% | x14 | 3 | B |
| 6 | J Law | 300% | x16 | 2 | B |
| 7 | Martin Luk | 540% | x41 | 2 | B |
| 8 | Dan Zanger | ~14.000% | x1.671 | 1,5 | A/B |
| 9 | Oliver Kell | 941% | x10,4 | 1 | B |
| 10 | Kristjan Kullamägi | 221% | x20.000 (dice) | 8,5 | C |

Quedan fuera por no llegar al 100%: Steve Cohen (~30%), Richard Driehaus (~30%), Gil Morales (87%), Sean Ryan (81%), CIS (69-88%), Darvas (91% con lo verificado; 297% con lo que él decía) y Livermore (sin datos).
