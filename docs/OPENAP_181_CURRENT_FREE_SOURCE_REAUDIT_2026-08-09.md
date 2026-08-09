# OpenAP 181: reauditoria de fuentes gratuitas para datos actuales

Fecha de comprobacion: 2026-08-09

## Resultado directo

La etiqueta operativa `blocked` no significaba que 150 senales fueran imposibles de obtener gratis. Significaba que no podian incorporarse todavia al score estricto porque faltaba al menos una puerta de formula, pipeline, fecha disponible, identidad, cobertura, fidelidad o evidencia.

Al reevaluar las 181 senales con un objetivo distinto y explicito —calcular el valor actual con la informacion publica mas reciente y solo el historial minimo que exige cada formula— el resultado es:

| Clase actual | Senales | Interpretacion |
|---|---:|---|
| Ruta gratuita automatizable documentada | 149 | Hay una combinacion gratuita de SEC, FINRA, Twelve Data, OpenFIGI, USPTO, BEA, Cboe, Kenneth French u otra fuente publica que permite intentar la reconstruccion actual. |
| Ruta gratuita con cuenta de opciones pendiente | 6 | Tradier documenta cadenas actuales con IV y griegas, pero exige una cuenta de brokerage y su uso es personal; falta comprobar que el titular puede abrirla y usarla en Aurora. |
| Datos de analistas visibles pero sin fuente gratuita autorizada equivalente | 20 | Alpha Vantage y FMP documentan estimaciones o ratings, pero sus terminos gratuitos no permiten usar esos datos como panel de investigacion derivado equivalente a IBES. |
| Falta el IV historico del mes anterior | 3 | La cadena actual no basta para calcular el cambio mensual; no se encontro un archivo gratuito y autorizado de superficies IV expiradas. |
| Solo reconstruccion incompleta o proxy | 3 | Rating crediticio, G-index y PIN carecen de un panel actual, estructurado, completo y gratuito equivalente. |
| **Total** | **181** | Inventario completo reconciliado. |

Por tanto, **155 de las 181 tienen una ruta gratuita actual utilizable o una candidata con cuenta gratuita**. Esto es factibilidad de datos, no aprobacion del score. El inventario estricto sigue en 31 hasta implementar y medir cobertura y fidelidad.

## Cambio de criterio

La auditoria anterior mezclaba dos preguntas:

1. ¿Puede reproducirse toda la historia OpenAP/CRSP/Compustat desde 1926 con identidad PERMNO y sin ninguna diferencia semantica?
2. ¿Puede calcularse hoy una version causal y suficientemente fiel de la senal usando datos gratuitos actuales?

La primera pregunta sigue siendo muy exigente. La segunda es la que corresponde al score actual y abre muchas mas senales. La historia anterior a 2009 no debe bloquear por si sola una formula actual si la ventana necesaria esta cubierta y la senal se etiqueta con honestidad.

## Fuentes verificadas

- [SEC EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces): APIs JSON sin clave, `companyfacts`, historial de submissions, actualizacion en tiempo real y archivos bulk nocturnos.
- [SEC Financial Statement Data Sets](https://www.sec.gov/data-research/sec-markets-data/financial-statement-data-sets): estados numericos XBRL `as filed` desde 2009, con accesion y enmiendas.
- [SEC Financial Statement and Notes Data Sets](https://www.sec.gov/data-research/sec-markets-data/financial-statement-notes-data-sets): notas y tablas XBRL, incluidas etiquetas estandar y propias necesarias para segmentos, clientes y desgloses menos comunes.
- [SEC Form 13F Data Sets](https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets): posiciones institucionales trimestrales estructuradas desde 2013.
- [Twelve Data Basic](https://twelvedata.com/pricing): plan gratuito de 800 creditos diarios; su [API de series](https://twelvedata.com/docs/introduction/overview) entrega OHLCV y sus [terminos](https://twelvedata.com/terms) permiten uso interno y datos derivados no reversibles, sin redistribuir el dato bruto.
- [FINRA Equity Short Interest](https://www.finra.org/finra-data/browse-catalog/equity-short-interest): posiciones cortas dos veces al mes, archivos historicos y hasta cinco anos por API; FINRA tambien documenta la [automatizacion de descargas](https://www.finra.org/sites/default/files/Equity_Short_Interest_Data_File_Download_API.pdf).
- [Tradier Options Chains](https://docs.tradier.com/reference/brokerage-api-markets-get-options-chains): cadenas actuales con IV y griegas; [API sin coste para titulares de cuenta](https://production.tradier.com/individuals/pricing), limitada a uso personal segun su [FAQ](https://docs.tradier.com/docs/faq).
- [OpenFIGI](https://www.openfigi.com/api/documentation): mapeo gratuito de CUSIP, ISIN, ticker y FIGI, con y sin clave.
- [USPTO PatentsView](https://www.uspto.gov/ip-policy/economic-research/patentsview): patentes, citas, solicitantes y cesionarios en API y descargas estructuradas.
- [BEA Input-Output Accounts](https://www.bea.gov/data/industries/input-output-accounts-data): relaciones entre industrias, actualizadas anualmente, con archivo de vintages.
- [Cboe VIX historical data](https://www.cboe.com/tradable_products/vix/vix_historical_data): VIX diario desde 1990; es proxy, no sustituto exacto de VXO despues de 2021.
- [Kenneth French Data Library](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html): factores y carteras de investigacion actuales y descargables.
- [Jay Ritter IPO data](https://site.warrington.ufl.edu/ritter/published-articles/): fechas de fundacion e inventarios IPO actualizados hasta 2025 como comprobacion secundaria; la ruta primaria actual debe salir de SEC.
- [Alpha Vantage documentation](https://www.alphavantage.co/documentation/): documenta estimaciones EPS/ventas, numero de analistas y revisiones, pero sus [terminos](https://www.alphavantage.co/terms_of_service/) clasifican investigacion y testing mas alla del uso personal como uso comercial.
- [FMP documentation](https://site.financialmodelingprep.com/developer/docs): documenta estimaciones, grades y consensos; el plan [Basic](https://site.financialmodelingprep.com/developer/docs/pricing) es gratuito, pero sus [terminos](https://site.financialmodelingprep.com/terms-of-service) impiden crear derivados sin autorizacion escrita.

## Las 149 con ruta gratuita automatizable documentada

### Contabilidad y fundamentales: 87

Ruta principal: SEC EDGAR `companyfacts` + FSD/Notes + fecha de aceptacion; Twelve Data para precio, volumen o capitalizacion; OpenFIGI/SEC para identidad actual.

AbnormalAccruals, Accruals, AccrualsBM, AdExp, AM, BM, BMdec, BookLeverage, BPEBM, BrandInvest, Cash, CashProd, CBOperProf, CF, cfp, ChAssetTurnover, ChInvIA, ChNNCOA, ChTax, CompEquIss, CompositeDebtIssuance, ConvDebt, DebtIssuance, DelCOA, DelCOL, DelDRC, DelEqu, DelFINL, DelLTI, DelNetFin, DivYieldST, dNoa, EarningsConsistency, EarningsSurprise, EarnSupBig, EBM, EntMult, EP, EquityDuration, FR, Frontier, GP, GrLTNOA, GrSaleToGrInv, GrSaleToGrOverhead, IntanBM, IntanCFP, IntanEP, IntanSP, Investment, InvGrowth, Leverage, MeanRankRevGrowth, MS, NetDebtFinance, NetDebtPrice, NetEquityFinance, NetPayoutYield, NOA, NumEarnIncrease, OperProf, OperProfRD, OPLeverage, OrderBacklog, OrderBacklogChg, OrgCap, OScore, PayoutYield, PctTotAcc, PS, RD, RDAbility, RDcap, RDS, realestate, RevenueSurprise, roaq, ShareIss1Y, ShareIss5Y, ShareRepurchase, SP, SurpriseRD, tang, Tax, TotalAccruals, VarCF, XFIN.

`Cash` pertenece a este grupo. SEC proporciona caja, activos y fecha de filing; el trabajo es fijar alias XBRL, enmiendas, caja restringida e identidad, no encontrar una fuente de pago obligatoria.

### Institucionales y 13F: 7

Ruta principal: SEC 13F + SEC/Twelve Data para acciones y capitalizacion + OpenFIGI para CUSIP/FIGI/ticker.

Activism1, Activism2, DelBreadth, IO_ShortInterest, RIO_MB, RIO_Turnover, RIO_Volatility.

### Eventos: 8

Ruta principal: submissions y filings SEC, prospectos, 8-K, 10-12B y hechos XBRL; Twelve Data para retornos alrededor del evento.

AgeIPO, DivInit, DivOmit, DivSeason, ExchSwitch, IndIPO, RDIPO, Spinoff.

### Precio: 27

Ruta principal: Twelve Data OHLCV + factores Kenneth French + Cboe/FRED cuando corresponda + SEC para eventos o clasificacion.

AnnouncementReturn, Beta, BetaFP, BetaLiquidityPS, BetaTailRisk, betaVIX, CoskewACX, Coskewness, FirmAgeMom, High52, IdioVol3F, IdioVolAHT, IndMom, IndRetBig, Mom6mJunk, MomOffSeason11YrPlus, MomRev, MomVol, PriceDelayRsq, PriceDelaySlope, PriceDelayTstat, RealizedVol, ResidualMomentum, retConglomerate, ReturnSkew3F, Size, TrendFactor.

`betaVIX` solo puede ser proxy desde que VXO dejo de publicarse en 2021. `retConglomerate` exige reconstruir segmentos SEC y no debe llamarse equivalente exacto a Compustat sin validacion.

### Trading: 9

Ruta principal: Twelve Data OHLCV, FINRA short interest, SEC shares outstanding y calendario bursatil.

BidAskSpread, ShortInterest, std_turn, VolMkt, VolSD, VolumeTrend, zerotrade12M, zerotrade1M, zerotrade6M.

FINRA short interest es la posicion corta real y no debe sustituirse por volumen corto diario.

### Otras: 11

Ruta principal segun senal: USPTO para patentes; BEA/Census para redes industriales; SEC Notes/filings para empleados, segmentos y clientes; Twelve Data para retornos.

CitationsRD, CustomerMomentum, FirmAge, Herf, HerfAsset, HerfBE, hire, iomom_cust, iomom_supp, PatentsRD, sinAlgo.

`CustomerMomentum`, `FirmAge` y `sinAlgo` son reconstrucciones actuales: los campos publicos existen, pero la semantica Compustat/CRSP y la cobertura deben medirse.

## Las 6 opciones con cuenta gratuita pendiente

CPVolSpread, OptionVolume1, OptionVolume2, RIVolSpread, skew1, SmileSlope.

Tradier entrega cadenas actuales, precios, volumen, open interest, IV y griegas. Falta comprobar elegibilidad de cuenta, permiso para la ejecucion personal de Aurora, cobertura del universo y equivalencia frente a OptionMetrics. No son “imposibles”; tampoco estan aprobadas.

## Las 20 dependientes de analistas

AnalystRevision, AnalystValue, AOP, ChangeInRecommendation, ChForecastAccrual, ChNAnalyst, ConsRecomm, DownRecomm, EarningsForecastDisparity, EarningsStreak, ExclExp, FEPS, fgr5yrLag, ForecastDispersion, PredictedFE, Recomm_ShortInterest, REV6, RIO_Disp, sfe, UpRecomm.

Hay datos actuales visibles o consultables en Alpha Vantage y FMP para parte de estas variables, pero no forman un panel IBES equivalente y los terminos gratuitos no autorizan el uso derivado requerido por Aurora. Estado correcto: `free_candidate_but_not_authorized_or_equivalent`, no `impossible`.

## Las 3 que necesitan IV anterior

dCPVolSpread, dVolCall, dVolPut.

Una cadena de hoy no contiene la superficie de hace un mes. Se pueden hacer calculables en el futuro empezando una coleccion causal propia, pero no se debe inventar el mes anterior ni usar un archivo con licencia incompatible.

## Las 3 con solo proxy incompleto

- `CredRatDG`: OpenAP usa S&P/Capital IQ. Las notas, 8-K y comunicados publicos permiten detectar algunos downgrades, pero no un panel completo y estructurado.
- `Governance`: OpenAP usa el G-index. Los proxy statements, estatutos y bylaws SEC contienen parte de las provisiones, pero reconstruir las 24 reglas es otro indicador y requiere una validacion juridico-documental.
- `ProbInformedTrading`: el PIN exacto necesita transacciones intradia clasificadas. FINRA short volume o datos de un solo mercado son proxies, no el panel consolidado requerido.

## Consecuencia operativa

- El termino `blocked` se conserva solo para la puerta de promocion estricta.
- Para investigacion de fuentes debe mostrarse una segunda columna independiente: `current_free_data_feasibility`.
- Ninguna de las 155 candidatas se incorpora automaticamente al score. Cada una necesita formula ejecutada, fecha disponible causal, identidad, cobertura y fidelidad.
- Prioridad recomendada: las 87 contables SEC, comenzando por Cash, GP e Investment; despues las 36 de precio/trading y las 7 de 13F.

## Limites de esta reauditoria

- No se inicio ni reejecuto ningun workflow de GitHub.
- No se ejecuto ningun script, prueba, backtest o descarga masiva de datos del proyecto.
- Se inspecciono el artefacto ya existente del run `31329387995`, el codigo OpenAP fijado en el commit `8db892442c2c3a3779b0f1eac4370d3655be15a1` y documentacion primaria de las fuentes.
- No se probaron credenciales ni endpoints que requieren cuenta. Por eso las seis senales de opciones siguen marcadas como candidatas de cuenta y no como ruta ya operativa.
- El score estricto confirmado no cambia en este documento: 31.
