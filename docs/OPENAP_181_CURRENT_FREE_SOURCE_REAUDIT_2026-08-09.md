# OpenAP 181: reauditoria de fuentes gratuitas para datos actuales

Fecha de comprobacion: 2026-08-09

## Resultado directo

La etiqueta operativa `blocked` no significaba que 150 senales fueran imposibles de obtener gratis. Significaba que no podian incorporarse todavia al score estricto porque faltaba al menos una puerta de formula, pipeline, fecha disponible, identidad, cobertura, fidelidad o evidencia.

Al reevaluar las 181 senales con un objetivo distinto y explicito —calcular el valor actual con la informacion publica mas reciente y solo el historial minimo que exige cada formula— el resultado es:

| Clase actual | Senales | Interpretacion |
|---|---:|---|
| Ruta gratuita automatizable documentada | 149 | Hay una combinacion gratuita de SEC, FINRA, artefactos de mercado ya adquiridos, Twelve Data como respaldo, OpenFIGI, USPTO, BEA, Cboe, Kenneth French u otra fuente publica que permite intentar la reconstruccion actual. |
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
- [Form 8-K oficial](https://www.sec.gov/files/form8-k.pdf): Item 2.02 cubre
  anuncios o releases de resultados de periodos trimestrales o anuales
  completados y exige declarar la fecha del anuncio, identificarlo e incluir
  su texto como exhibit. Esto permite reconstruir `AnnouncementReturn` sin
  confundir el evento con la fecha posterior de un 10-Q/10-K.
- [SEC EDGAR XBRL Guide 2026](https://www.sec.gov/file/xbrl-guide-2026-01-16): los filings Inline XBRL pueden declarar `dei:TradingSymbol`, `dei:SecurityExchangeName` y `dei:Security12bTitle` por contexto. Sirven para corroborar observaciones historicas CIK-clase-ticker-bolsa, pero no autorizan a convertir la asociacion actual de `company_tickers_exchange.json` en un intervalo historico ni en identidad PERMNO.
- [SEC Financial Statement Data Sets](https://www.sec.gov/data-research/sec-markets-data/financial-statement-data-sets): estados numericos XBRL `as filed` desde 2009, con accesion y enmiendas.
- [SEC Financial Statement and Notes Data Sets](https://www.sec.gov/data-research/sec-markets-data/financial-statement-notes-data-sets): notas y tablas XBRL, incluidas etiquetas estandar y propias necesarias para segmentos, clientes y desgloses menos comunes.
- [Taxonomia US-GAAP 2026 de FASB](https://xbrl.fasb.org/us-gaap/2026/elts/): esquema y definiciones oficiales de las etiquetas XBRL. Confirma que `CommonStockCapitalSharesReservedForFutureIssuance` es un agregado para cualquier emision futura, mientras que `ConvertibleDebt` y sus porciones describen saldos de deuda convertible; no son por si solos equivalencias de los campos Compustat `dc/cshrc`.
- [FAQ de taxonomia GAAP de FASB](https://www.fasb.org/taxonomyfaq): documenta
  la separacion dimensional de tesoreria comun y preferente y el concepto
  `TreasuryStockPreferredValue`. Los filings EDGAR tambien exponen el concepto
  estandar
  [`PreferredStockAmountOfPreferredDividendsInArrears`](https://www.sec.gov/Archives/edgar/data/1232582/000123258226000118/R61.htm).
- [Ejemplos primarios de pensiones y AOCI en EDGAR](https://www.sec.gov/Archives/edgar/data/1311370/000162828025007441/R103.htm): los filings muestran `DefinedBenefitPlanFairValueOfPlanAssets`, `DefinedBenefitPlanBenefitObligation` y ejes para separar pensiones. Un [10-K con planes en superavit y deficit](https://www.sec.gov/Archives/edgar/data/16875/000001687525000008/cp-20241231.htm) demuestra el desglose necesario para `FR`; un [roll-forward AOCI por componente](https://www.sec.gov/Archives/edgar/data/81362/000162828026028949/R23.htm) demuestra los saldos de traduccion y valores disponibles para la venta requeridos por `RDS`.
- [Dividendos comunes y preferentes en EDGAR](https://www.sec.gov/Archives/edgar/data/93751/000009375126000124/R110.htm): la taxonomia publica `DividendsPreferredStockCash`; tambien publica [`DividendsCommonStockCash`](https://www.sec.gov/Archives/edgar/data/1012100/000101210026000016/R145.htm). Son entradas gratuitas para la reconstruccion de `RDS`, sujetas al mismo periodo anual y fecha de aceptacion.
- [SEC Form 13F Data Sets](https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets): posiciones institucionales trimestrales estructuradas desde 2013.
- [Twelve Data Basic](https://twelvedata.com/pricing): plan gratuito de 800 creditos diarios; su [inicio rapido oficial](https://twelvedata.com/docs/introduction/quickstart) documenta la clave en cabecera, el [historico diario](https://support.twelvedata.com/en/articles/5656039-how-to-get-historical-prices) cubre normalmente desde la primera cotizacion y el [ajuste de precios](https://support.twelvedata.com/en/articles/5179064-are-the-prices-adjusted) puede controlarse. Sus [terminos](https://twelvedata.com/terms) permiten uso interno y datos derivados no reversibles, sin redistribuir el dato bruto.
- [Twelve Data Dividends](https://twelvedata.com/docs/advanced): el endpoint
  `/dividends` cuesta 20 creditos por simbolo y la documentacion vigente lo
  limita a Grow para particulares o Venture para empresas y niveles superiores.
  No forma parte de la ruta Basic gratuita descrita para OHLCV.
- [Pastor-Stambaugh Liquidity Data](https://faculty.chicagobooth.edu/lubos-pastor/data):
  la pagina oficial de Chicago Booth publica gratuitamente nivel, innovacion
  no negociada y factor negociado hasta diciembre de 2025. La innovacion es la
  entrada correcta de `BetaLiquidityPS`; para una formacion de julio de 2026
  queda desfasada y no se declara actual.
- [FINRA Equity Short Interest](https://www.finra.org/finra-data/browse-catalog/equity-short-interest): posiciones cortas dos veces al mes, archivos historicos y hasta cinco anos por API; FINRA tambien documenta la [automatizacion de descargas](https://www.finra.org/sites/default/files/Equity_Short_Interest_Data_File_Download_API.pdf).
- [Tradier Options Chains](https://docs.tradier.com/reference/brokerage-api-markets-get-options-chains): cadenas actuales con IV y griegas; [API sin coste para titulares de cuenta](https://production.tradier.com/individuals/pricing), limitada a uso personal segun su [FAQ](https://docs.tradier.com/docs/faq).
- [OpenFIGI](https://www.openfigi.com/api/documentation): mapeo gratuito de CUSIP, ISIN, ticker y FIGI, con y sin clave.
- [USPTO PatentsView](https://www.uspto.gov/ip-policy/economic-research/patentsview): descargas estructuradas de patentes, citas y cesionarios, actualizadas hasta diciembre de 2025 en el Open Data Portal. La [API PatentSearch](https://search.patentsview.org/docs/docs/Search%20API/SearchAPIReference/) exige clave, limita a 45 peticiones por minuto y tiene suspendida temporalmente la concesion de claves nuevas; la ruta de estas senales debe usar los bulk downloads, no depender de esa API.
- [BEA Input-Output Accounts](https://www.bea.gov/data/industries/input-output-accounts-data): relaciones entre industrias, actualizadas anualmente, con archivo de vintages.
- [Cboe VIX historical data](https://www.cboe.com/tradable_products/vix/vix_historical_data): VIX diario desde 1990; es proxy, no sustituto exacto de VXO despues de 2021.
- [FRED GNPDEF](https://fred.stlouisfed.org/series/GNPDEF): deflactor implicito del GNP con origen BEA, frecuencia trimestral, acceso CSV sin clave y etiqueta `Public Domain: Citation Requested`; se autoriza como entrada reconstruida de OScore con atribucion a BEA/FRED.
- [Kenneth French Data Library](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html): factores y carteras de investigacion actuales y descargables.
- [Jay Ritter IPO data](https://site.warrington.ufl.edu/ritter/published-articles/): fechas de fundacion e inventarios IPO actualizados hasta 2025 como comprobacion secundaria; la ruta primaria actual debe salir de SEC.
- [Alpha Vantage documentation](https://www.alphavantage.co/documentation/): documenta estimaciones EPS/ventas, numero de analistas y revisiones, pero sus [terminos](https://www.alphavantage.co/terms_of_service/) clasifican investigacion y testing mas alla del uso personal como uso comercial.
- [FMP documentation](https://site.financialmodelingprep.com/developer/docs): documenta estimaciones, grades y consensos; el plan [Basic](https://site.financialmodelingprep.com/developer/docs/pricing) es gratuito, pero sus [terminos](https://site.financialmodelingprep.com/terms-of-service) impiden crear derivados sin autorizacion escrita.

## Las 149 con ruta gratuita automatizable documentada

### Contabilidad y fundamentales: 87

Ruta principal: SEC EDGAR `companyfacts` + FSD/Notes + fecha de aceptacion;
artefactos de mercado ya adquiridos para precio, volumen o capitalizacion;
OpenFIGI/SEC para identidad actual. Twelve Data queda como respaldo.

AbnormalAccruals, Accruals, AccrualsBM, AdExp, AM, BM, BMdec, BookLeverage, BPEBM, BrandInvest, Cash, CashProd, CBOperProf, CF, cfp, ChAssetTurnover, ChInvIA, ChNNCOA, ChTax, CompEquIss, CompositeDebtIssuance, ConvDebt, DebtIssuance, DelCOA, DelCOL, DelDRC, DelEqu, DelFINL, DelLTI, DelNetFin, DivYieldST, dNoa, EarningsConsistency, EarningsSurprise, EarnSupBig, EBM, EntMult, EP, EquityDuration, FR, Frontier, GP, GrLTNOA, GrSaleToGrInv, GrSaleToGrOverhead, IntanBM, IntanCFP, IntanEP, IntanSP, Investment, InvGrowth, Leverage, MeanRankRevGrowth, MS, NetDebtFinance, NetDebtPrice, NetEquityFinance, NetPayoutYield, NOA, NumEarnIncrease, OperProf, OperProfRD, OPLeverage, OrderBacklog, OrderBacklogChg, OrgCap, OScore, PayoutYield, PctTotAcc, PS, RD, RDAbility, RDcap, RDS, realestate, RevenueSurprise, roaq, ShareIss1Y, ShareIss5Y, ShareRepurchase, SP, SurpriseRD, tang, Tax, TotalAccruals, VarCF, XFIN.

`Cash` pertenece a este grupo. SEC proporciona caja, activos y fecha de filing; el trabajo es fijar alias XBRL, enmiendas, caja restringida e identidad, no encontrar una fuente de pago obligatoria.

#### Recuperacion estrecha de diecisiete senales OpenAP93

El artefacto recuperado `31341580689` conserva 2.157 filas actuales de
`CompEquIss`, de las que 1.585 son utilizables. La reconstruccion aplica la
formula oficial de 60 meses, pero usa precio de la accion primaria por acciones
del emisor SEC en lugar de la capitalizacion CRSP de empresa y no demuestra la
identidad PERMNO historica. Por tanto, es una ruta gratuita reconstruida y no
una equivalencia CRSP exacta.

La ruta aprobada se limita al alias `recovered_openap93_compequiss`. El cargador
preparado exige el artefacto inmutable del run `31341580689`, la cadena de
hashes hasta el run fuente `31333714423`, la formula exacta, fechas causales,
identidad CIK-ticker, cobertura reconciliada y ausencia de duplicados. No
autoriza `yahoo_public` para ninguna otra senal. La ejecucion de consolidacion
sigue pendiente y el resultado no puede entrar en el score estricto.

`EquityDuration` usa el mismo artefacto inmutable con un alias independiente,
`recovered_openap93_equityduration`. Hay 37 valores actuales (1,7153 % del
universo). El calculo conserva las constantes oficiales 0,57/0,12/0,24/0,06 y
la proyeccion a diez anos, pero reemplaza `ceq`, `ib`, `sale`, `csho` y
`prcc_f` de Compustat/CRSP por contabilidad SEC y precio Yahoo del cierre
fiscal. La cobertura, la identidad historica y la fidelidad estricta siguen
pendientes; por ello solo puede clasificarse como reconstruida no estricta.

`betaVIX` dispone de 2.157 valores y reproduce la regresion oficial de 20 dias
con minimo 15 observaciones usando retornos Yahoo, factores Kenneth French y
VIX Cboe. La ruta `recovered_openap93_betavix` conserva los hashes y fechas,
pero no convierte Yahoo en CRSP ni demuestra identidad historica.

Las rutas `RIO_MB`, `RIO_Turnover` y `RIO_Volatility` recuperan respectivamente
305, 231 y 158 quintiles actuales mediante `recovered_openap93_rio`. Usan SEC
13F y OpenFIGI, retardo de seis meses y filtros/quintiles oficiales, con SEC y
Yahoo como sustitutos reconstruidos de Thomson/CRSP/Compustat. El contrato
valida los recuentos de aplicables y no aplicables y solo admite enteros 1-5.
`RIO_Disp` queda excluida porque su aproximacion Yahoo no equivale a IBES y el
artefacto la declara no utilizable.

`OScore` aporta 1.100 valores actuales mediante SEC y el deflactor `GNPDEF`
gratuito de FRED. La ruta estrecha `recovered_openap93_oscore` liga el CSV y la
cobertura al artefacto recuperado, exige cuatro entradas, valores binarios,
fechas causales y la formula `openap_ohlson_oscore_decile_sec_gnpdefl`. Sigue
siendo reconstruida no estricta porque no demuestra equivalencia
Compustat/CRSP.

Cuatro salidas de mercado del mismo artefacto quedan tambien ligadas por una
ruta estrecha individual: `PriceDelayRsq` (2.157), `CoskewACX` (2.157),
`Coskewness` (2.157) y `ResidualMomentum` (2.144). El contrato exige los hashes
del artefacto, la fuente original `yahoo_public|kenneth_french`, el script y la
formula OpenAP exactos, frecuencia, observaciones minimas, cobertura y fechas
sin lookahead. Son valores actuales reconstruidos, no equivalentes a CRSP ni
aptos para score estricto; tambien queda pendiente cerrar la revision de los
terminos del endpoint Yahoo.

La misma ruta hash-bound admite cuatro salidas Yahoo adicionales:
`BetaTailRisk` (1.989), `DivYieldST` (1.191), `MomVol` (719) y `MomRev` (232).
Ademas de fuente, formula, script, identidad, fechas y cobertura, el contrato
exige los minimos de historia y los dominios discretos de las tres senales por
categorias. `DivYieldST` queda documentada como reconstruccion porque infiere
la frecuencia de distribuciones desde ex-dates Yahoo en vez del codigo CRSP.
Ninguna de las cuatro es estricta y la revision de terminos Yahoo sigue
pendiente.

`DivInit` y `DivOmit` anaden 2.157 clasificaciones binarias actuales cada una.
El artefacto conserva al menos 37 meses por empresa y el contrato exige un
minimo de 24, las ventanas oficiales, valores 0/1 y caveats exactos. Estas filas
reemplazan en la salida final la evidencia SEC positiva incompleta: cero
iniciaciones y 14 omisiones sin clases negativas. La sustitucion Yahoo sigue
siendo reconstruida porque no demuestra codigos de distribucion ni PERMNO
historico CRSP, y sus terminos permanecen pendientes de cierre.

`OrgCap` no esta en la misma situacion: el artefacto contiene 689 numeros, pero
todos estan marcados `stale_reference_only` y ninguno tiene
`current_usable=True`. Ademas usa SIC SEC a dos digitos, que no equivale al SIC
historico CRSP ni a la clasificacion FF17 oficial. Por tanto no se admite en
una reconsolidacion hasta obtener historia SG&A causal y contigua.

`Frontier` conserva ocho numeros distintos. El calculador del SHA fuente usa el
mes de mercado mas reciente en la regresion de 60 meses, pero al construir la
fila copia `available_at` y `period_end` del filing anual y omite
`price_date`. El propio bucle calcula correctamente `current_available` como
el maximo de contabilidad y precio, pero no lo usa para `Frontier`. De ahi los
160 a 261 dias de antiguedad registrados. No se recuperan aun: hace falta una
prueba que demuestre la dependencia causal de mercado y una nueva salida con
fechas corregidas. La formula seguira siendo una reconstruccion SEC/Yahoo, no
Compustat/CRSP exacta.

`EBM` y `BPEBM` tampoco carecen de una fuente gratuita para sus componentes
raros. SEC ya cubre caja, deuda corriente y no corriente, deferred charges,
patrimonio y preferred stock en la retencion actual o preparada. La taxonomia
publica identifica `PreferredStockAmountOfPreferredDividendsInArrears` para
`dvpa` y `TreasuryStockPreferredValue` para `tstkp`. El artefacto OpenAP93
contiene 2.157 filas vacias por senal porque no retuvo esas dos etiquetas; ese
cero de valores no demuestra ausencia en EDGAR. La ruta debe incorporarlas,
exigir los siete componentes del mismo periodo causal, usar capitalizacion de
emisor y nunca convertir una etiqueta ausente en cero. Sera una reconstruccion
no estricta y su cobertura puede ser pequena, pero queda pendiente de medir.

Las cuatro `Intan*` tienen otro bloqueo de construccion, no de fuente. El
artefacto OpenAP93 conserva 2.157 filas por cada una, todas sin valor por
`missing_causal_multiyear_inputs`. El calculador dispone de 84 meses de precio
y aplica el lag de 60 meses, pero `_prepare_annual_facts` pivota
`EntityCommonStockSharesOutstanding` con la contabilidad por el mismo
`period_end`. En muchos filings la fecha de contexto de acciones es la fecha
de portada y no el cierre fiscal, de modo que `shares` desaparece y no puede
formarse la capitalizacion. Hay que resolver acciones por disponibilidad de
forma independiente, agregar las clases del CIK por mes y ejecutar despues las
cuatro regresiones transversales. `IntanCFP` seguira siendo proxy no validado
porque `NetIncomeLoss+depreciation` no demuestra `ib+dp`; las otras tres seran
reconstrucciones SEC/mercado, nunca equivalencias Compustat/CRSP.

`FR` puede obtenerse gratuitamente, pero no desde los totales pensionarios de
Company Facts sin mas. La formula oficial para el ano actual usa
`(pplao-pbpro)/mve_permco`: activos y obligacion proyectada de los planes de
pensiones en superavit. EDGAR publica los conceptos estandar
`DefinedBenefitPlanFairValueOfPlanAssets` y
`DefinedBenefitPlanBenefitObligation`, dimensiones de tipo de plan y tablas
que separan explicitamente planes en superavit y deficit. El desglose puede
venir en etiquetas propias del emisor, de modo que la ruta debe leer Financial
Statement and Notes o el filing individual, exigir la semantica explicita de
pension y superavit, y conservar accesion, `accepted`, fecha, unidad y todas
las dimensiones. Si solo hay totales o el texto no permite demostrar el
subconjunto, debe fallar cerrada. El colector actual no retiene ninguna
etiqueta `DefinedBenefitPlan*`; por tanto su valor vacio prueba una carencia de
implementacion, no una carencia de datos gratuitos. La capitalizacion sera de
emisor reconstruida y la salida no sera CRSP/Compustat exacta.

`RDS` tambien tiene una ruta SEC/mercado concreta. OpenAP calcula el cambio de
patrimonio menos dirty surplus, beneficio neto de dividendo preferente,
dividendo comun y precio por cambio de acciones. Su dirty surplus suma los
cambios de `msa`, `recta` y el 65 % del termino pensionario. EDGAR publica los
roll-forwards de AOCI por componente, incluidos traduccion de moneda y valores
disponibles para la venta, ademas de `DividendsCommonStockCash` y
`DividendsPreferredStockCash`; patrimonio, beneficio y acciones ya tienen
rutas SEC, y el precio fiscal tiene ruta de mercado preparada. La reparacion
debe resolver los saldos finales actual/anterior por ejes y miembros, nunca
usar AOCI total como sustituto, y dejar la fila vacia cuando no identifica ni
traduccion ni valores disponibles para la venta en ambos cortes. El propio
codigo oficial trata el termino de pensiones como cero cuando falta `pcupsu` o
`paddml`, regla que debe conservarse. La salida sera reconstruida/no estricta:
la taxonomia y la base antes/despues de impuestos no demuestran equivalencia
exacta con `msa/recta`, pero no se necesita una fuente de pago.

`DelDRC`, `ConvDebt`, `OrderBacklog` y `OrderBacklogChg` no necesitan Twelve
Data para sus entradas contables. La API `companyfacts` solo agrega hechos de
taxonomias no personalizadas aplicables a toda la entidad; por eso no cubre
todos los desgloses necesarios. El dataset SEC Financial Statement and Notes
si incluye etiquetas estandar y personalizadas, valores numericos tal como se
presentan y la fecha/hora `accepted` de cada accesion. El run historico
`31343497010` intento un unico archivo Notes y obtuvo HTTP 403 tras cinco
intentos, de modo que demostro el bloqueo de transporte del runner, no la
ausencia ni el caracter de pago de los datos.

La formula y el calculador causal de `DelDRC` ya existen. Ademas, el artefacto
de filing `31347614238` conserva en el 10-K de Apple los importes de deferred
revenue de 2025 y 2024, con aceptacion SEC de 2025-10-31. Esa muestra prueba
que los datos aparecen gratuitamente en filings individuales, pero se obtuvo
mediante un readthrough de terceros despues de que la URL oficial devolviera
403; por ello aun no se declara una ruta de produccion autorizada ni un valor
actual calculado.

En `ConvDebt` se corrigio una conclusion demasiado fuerte. El diagnostico del
run `31342908279` registro cero etiquetas relacionadas, pero los 48 shards de
entrada del run fuente `31270341796` no conservaban todos los hechos de
CompanyFacts: el parser de la revision fuente `b82d16417` filtraba cada payload
con la lista cerrada `SEC_CONCEPT_ALIASES`, que no incluia ninguna etiqueta de
`dc`, `cshrc` o deuda convertible. Ese cero solo describe el subconjunto
retenido; no demuestra cobertura cero en todo EDGAR.

La formula fijada sigue siendo exactamente `1` cuando `dc` o `cshrc` son
distintos de cero y `0` en otro caso. La taxonomia oficial FASB 2026 contiene
`ConvertibleDebt`, sus porciones corriente/no corriente y
`DebtInstrumentConvertibleNumberOfEquityInstruments`. Tambien contiene
`CommonStockCapitalSharesReservedForFutureIssuance`, pero su definicion es el
total agregado de acciones reservadas para cualquier emision futura; por eso
no se usa como sustituto de `cshrc`. Tampoco se transforma un saldo de
`ConvertibleDebt` en equivalencia Compustat exacta: solo sirve como evidencia
positiva para una reconstruccion.

El codigo preparado ahora retiene una lista acotada de estas etiquetas y
calcula una reconstruccion positiva y fail-closed: emite `ConvDebt=1` solo si
la evidencia no nula pertenece al ultimo periodo anual que tambien tiene
`Assets`; la ausencia de etiqueta, una etiqueta amplia, un cero aislado o un
saldo de un periodo anterior no generan `0`. Esta ruta sigue sin ejecutar y
sin cobertura medida, de modo que no cambia ningun recuento ni el score. La
ruta exacta aun exige demostrar el mapeo semantico de `dc/cshrc`, probablemente
con SEC Notes o XBRL personalizado cuando CompanyFacts no lo agregue.

`DelNetFin` tampoco necesita Twelve Data. La formula fijada usa dos cortes
anuales, separados doce meses y disponibles con el retraso OpenAP de seis
meses: cambio de `ivst + ivao - dltt - dlc - pstk`, con `pstk` faltante igual a
cero, dividido por activos medios. La ruta preparada exige cierres alineados y
etiquetas SEC agregadas para activos, inversiones cortas y largas y deuda
corriente y no corriente. Rechaza los agregados de deuda que puedan duplicar
la pata corriente, no mezcla alias dentro de un componente y falla cerrado ante
huecos o conflictos. No se ha ejecutado ni medido cobertura.

La salida seguira siendo no estricta: los conceptos SEC no prueban equivalencia
con los seis campos Compustat, la vintage corriente puede incluir restatements
y falta el intervalo historico GVKEY/PERMNO. Esta preparacion no rehabilita las
filas antiguas en cuarentena ni cambia los recuentos.

`EarningsConsistency` tampoco necesita Twelve Data. La preparacion oficial de
OpenAP usa `epspx` anual de Compustat, lo hace disponible seis meses despues del
cierre fiscal y replica cada observacion durante doce meses. La formula calcula
el crecimiento interanual escalado con los dos EPS anteriores, promedia el valor
corriente y sus retardos de 12, 24, 36 y 48 meses con la misma semantica de
faltantes, y aplica los filtros oficiales de magnitud y cambio de signo.

La ruta preparada retiene ocho contextos anuales de
`EarningsPerShareBasic`, acepta solo `10-K/10-K/A` de duracion anual y unidad
`USD/shares`, exige disponibilidad antes de la formacion, reproduce el retraso
fijo de seis meses y conecta el calculo al batch CompanyFacts protegido. La
vintage SEC corriente puede incorporar restatements posteriores al mes
historico representado. Rechaza conflictos y resultados no finitos. Sigue
siendo reconstruccion no estricta:
`EarningsPerShareBasic` SEC no demuestra equivalencia con `epspx` Compustat y
CIK/ticker actual no sustituye el puente historico GVKEY/PERMNO. No se ha
ejecutado, la cobertura real sigue sin medir y la fila antigua con 13 proxies
continua en cuarentena; por tanto, no cambia ningun recuento.

`ChInvIA` tampoco necesita precio. La formula fijada calcula el crecimiento de
CAPEX frente a la media de sus retardos de 12 y 24 meses, usa como respaldo el
cambio de PP&E cuando falta CAPEX, recurre al crecimiento interanual cuando la
media no es utilizable y resta la media transversal del SIC a dos digitos. La
ruta preparada aplica esos pasos sobre hechos anuales SEC causales y el ultimo
SIC SEC no ambiguo disponible antes de la formacion. Rechaza periodos anuales
no contiguos, conflictos, denominadores cero y hechos futuros. Sigue siendo
reconstruccion no estricta porque el SIC SEC actual no equivale al SIC CRSP
historico y CIK/ticker no sustituye PERMNO. No se ha ejecutado ni medido su
cobertura, por lo que no cambia ningun recuento.

Los 48 shards del run `31270341796` son anteriores a la nueva retencion. Para
impedir un falso exito, cada manifiesto SEC nuevo debe declarar un contrato
versionado que incluya ocho anuales, 48 contextos trimestrales, EPS basico y
las etiquetas acotadas de deuda convertible, `DelNetFin` y dividendos por
accion; el batch de calculo rechaza todo shard que no lo declare. No se ha
iniciado esa nueva adquisicion.

`EarningsSurprise` y `RevenueSurprise` tampoco necesitan Twelve Data. Las
formulas fijadas requieren el valor actual, ocho cambios interanuales para la
deriva y ocho sorpresas anteriores para la desviacion tipica; una reconstruccion
completa necesita 21 trimestres contiguos. Los shards SEC conservaban hasta 24
observaciones recientes por etiqueta, pero el recolector no retenia las acciones
medias basicas y el calculador descartaba los hechos acumulados de seis, nueve y
doce meses. Por eso el cero ejecutado demostraba historia normalizada
insuficiente, no ausencia de datos gratuitos.

La ruta preparada retiene ingresos, ventas y
`WeightedAverageNumberOfSharesOutstandingBasic`, eleva a 48 el limite acotado
de contextos para esas etiquetas y transforma acumulados SEC en
trimestres discretos por diferencias y reconstruye las acciones medias del
trimestre ponderando los dias de cada periodo. Exige 21 cierres trimestrales
contiguos, unidades correctas, una sola taxonomia/etiqueta comparable, facts
disponibles antes de la formacion y ausencia de conflictos. La derivacion usa
las fechas economicas de inicio y cierre, no el campo SEC `fy`, que describe la
presentacion y puede cambiar entre contextos comparativos. Un hueco o una escala
degenerada no produce valor. Sigue siendo reconstruccion no estricta:
ingreso SEC dividido por acciones medias no es `epspxq`, ventas SEC/acciones no
demuestran equivalencia `revtq/cshprq` y CIK/ticker actual no es un puente
GVKEY/PERMNO historico. No se ha ejecutado y no cambia los recuentos.

El artefacto exitoso del run `31270341796` ofrece otra ruta gratuita para
recuperar salidas ya producidas, distinta de volver a descargar SEC o Yahoo. Su
`output_manifest.csv` liga por tamano y SHA-256 la cuadricula de 185 senales,
la cobertura y los conceptos SEC seleccionados. La recuperacion selectiva
preparada extrae esos tres derivados junto al `security_master` ya auditado y
admite solo 17 ratios que el propio pipeline etiqueto como proxies contables:
`AM`, `BM`, `CashProd`, `CF`, `cfp`, `EP`, `Leverage`, `NetDebtPrice`,
`NetPayoutYield`, `PayoutYield`, `RD`, `SP`, `AdExp`, `AccrualsBM`, `BMdec`,
`EntMult` y `PS`.

El contrato exige la cuadricula completa de 185 senales por titulo, cobertura
reconciliada, identidad SEC unica, filtros oficiales y todos los conceptos
declarados para cada formula. En `AccrualsBM` y `PS` exige tambien los retardos
anuales, un solo cierre por lag y una separacion causal de 330 a 400 dias.
Recalcula la disponibilidad como el maximo entre la aceptacion SEC y el
timestamp del snapshot Yahoo que aporto la capitalizacion del emisor. Un
timestamp ausente, futuro o distinto del maximo de dependencias queda
fail-closed. Conserva como formacion el `as_of` original del run: la fecha de
recuperacion no rejuvenece el dato.

Esta ruta no convierte SEC/Yahoo en Compustat/CRSP ni crea intervalos
historicos GVKEY/PERMNO. Quince salidas futuras seran `reconstructed`;
`AccrualsBM` y `BMdec` conservaran `unvalidated_proxy`. Todas tendran
`strict_score_eligible=false` e incremento estricto cero. El workflow es solo
manual y sigue sin ejecutarse; por tanto, no hay valores nuevos ni cambios en
los recuentos.

El consolidador preparado acepta este artefacto y el de las 31 senales de
mercado solo si ambos proceden del mismo run futuro y declaran exactamente el
SHA de la implementacion consolidada. Verifica contratos, hash del CSV,
objetivos, filas actuales utilizables, ausencia de duplicados y puertas
`OOS_LOCKED`, `FORWARD`, seleccion por validacion y score estricto cerradas.
La verificacion posterior compara de forma dinamica las filas fuente con las
filas consolidadas; no presupone cobertura ni altera los recuentos actuales.

### Institucionales y 13F: 7

Ruta principal: SEC 13F + SEC y artefactos de mercado ya adquiridos para
acciones o capitalizacion + OpenFIGI para CUSIP/FIGI/ticker. Twelve Data queda
como respaldo.

Activism1, Activism2, DelBreadth, IO_ShortInterest, RIO_MB, RIO_Turnover, RIO_Volatility.

`IO_ShortInterest` no necesita precio ni capitalizacion y, por tanto, tampoco
necesita Twelve Data. El codigo OpenAP fijado divide `shortint` por `shrout`,
calcula el percentil 99 por mes y conserva `instown_perc` solo para los titulos
en esa cola. Las fuentes gratuitas necesarias ya se adquirieron por separado:

- El manifiesto verificado del run `31333714423` registra 6.975.953 posiciones
  SEC 13F, 4.182.960 posiciones enlazadas por OpenFIGI (59,96256 %), ultimo
  periodo 2026-03-31 y ultima fecha de filing 2026-05-29. El parser conserva
  `SSHPRNAMT`, excluye opciones y principal, trata enmiendas de forma cerrada y
  ya suma acciones institucionales por titulo.
- El run `31340242772` produjo 2.988 ratios `ShortInterest` desde posiciones
  FINRA de 2026-07-15, publicadas el 2026-07-24, y acciones SEC causales.
- El artefacto recuperado `31341580689` demuestra 1.478 valores utilizables de
  `DelBreadth` desde SEC 13F + OpenFIGI, pero mantiene las 2.157 filas de
  `IO_ShortInterest` sin valor porque el pipeline antiguo aun intenta usar el
  snapshot de propiedad institucional de Yahoo.

El bloqueo correcto ya no es ausencia de fuente. La union gratuita queda ahora
preparada en codigo, pero no ejecutada. El calculador aplica el percentil 99
sobre todo el universo actual de ratios FINRA/SEC antes de filtrar por
disponibilidad 13F; de ese modo no eleva artificialmente al percentil extremo
unicamente los titulos que OpenFIGI pudo enlazar. Para cada mes solo admite el
ultimo periodo 13F cuyo plazo legal de 45 dias ya ha terminado, conserva las
fechas de filing y exige una identidad reforzada: el CUSIP debe tener un unico
`shareClassFIGI` de accion ordinaria estadounidense (`exchCode=US`), y ticker y
nombre normalizado del emisor 13F deben coincidir con un unico CIK SEC. No se
permite una union solo por ticker. Despues divide las acciones institucionales
por un denominador SEC causal.
Una identidad ambigua, un denominador futuro o una posicion no enlazada quedan
sin valor; no se convierten en cero aunque la formula OpenAP rellene con cero
los ausentes del panel Thomson ya limpio.

Los tres parquets normalizados necesarios estaban dentro del artefacto fallido
de 2,74 GB del run `31333714423`; no existe actualmente un artefacto separado
`openap-93-public-inputs`. Se ha ampliado el recuperador existente para leer por
rangos HTTP solo `sec_13f_filings.parquet`, `sec_13f_holdings.parquet` y
`openfigi_cusip_map.parquet`, comprobar primero su tamano comprimido declarado,
rechazar mas de 128 MiB y validar cada miembro contra el SHA-256 del manifiesto
fuente. El directorio central remoto declara 85.159.102 bytes comprimidos para
los tres miembros y el manifiesto, frente a 2.741.147.673 bytes del ZIP; no
descarga el ZIP completo.

La salida prevista sigue siendo reconstruccion no estricta: SEC 13F no es el
panel limpio de Thomson Reuters, acciones SEC no son `shrout` mensual CRSP y
OpenFIGI actual no aporta intervalos historicos PERMNO/GVKEY. Como el usuario ha
prohibido iniciar un nuevo run, esta ruta permanece `prepared_unexecuted`, sin
cobertura medida, sin valores publicados y sin cambios en los recuentos ni en
el score estricto.

`Activism1` y `Activism2` tienen un bloqueo adicional distinto de 13F. El
[codigo OpenAP fijado](https://raw.githubusercontent.com/OpenSourceAP/CrossSection/8db892442c2c3a3779b0f1eac4370d3655be15a1/Signals/pyCode/Predictors/ZZ1_Activism1_Activism2.py)
exige conjuntamente `maxinstown_perc`, el G-index, la clase dual y la identidad
historica. `Activism1` emite `24-G` solo en el cuartil superior de propiedad
institucional y excluye clase dual; `Activism2` conserva el bloque institucional
superior al 5 % solo si `24-G >= 19` y tambien excluye clase dual. El dataset
CCG Index de Harvard Dataverse (`doi:10.7910/DVN/T8UTXL`) es una ruta historica
gratuita con licencia CC BY-SA 4.0, pero su descarga exige completar un
guestbook con datos y aceptacion del usuario, y no ofrece un panel actual 2026
equivalente a las 24 provisiones. No se inventaron esos datos ni se aceptaron
condiciones en nombre del usuario. Por tanto, ambas senales siguen sin valor
actual calculable y su ruta solo puede considerarse historica/incompleta hasta
obtener un G-index y un historial de clases duales causales y validables.

### Eventos: 8

Ruta principal: submissions y filings SEC, prospectos, 8-K, 10-12B y hechos
XBRL. Cuando la formula consume retornos, la entrada principal son los
artefactos de mercado ya adquiridos y Twelve Data queda como respaldo; ninguna
es una entrada de `AgeIPO`, `IndIPO` ni `RDIPO`.

AgeIPO, DivInit, DivOmit, DivSeason, ExchSwitch, IndIPO, RDIPO, Spinoff.

La ruta de las tres senales IPO queda ahora concretada y preparada, pero no
ejecutada. La pagina oficial de Jay Ritter enlaza el Excel
`https://site.warrington.ufl.edu/ritter/files/IPO-age.xlsx`; el 2026-08-10
respondio HTTP 200, con 1.346.041 bytes y `Last-Modified` de
2026-01-19 16:47:15 UTC. El libro contiene una unica hoja `1975-2025`, 16.030
registros y las columnas reales `offer date`, nombre, ticker, CUSIP, PERMNO,
ano de fundacion y banderas de clases multiples, ADR y rollup. El PDF oficial
aclara que incluye IPO y direct listings, excluye las nuevas cotizaciones por
fusion con SPAC y puede contener juicios subjetivos sobre la fundacion.

El cargador preparado exige URL, HTTP 200, `Last-Modified`, tamano y SHA-256,
rechaza cambios de esquema y archivos XLSX inseguros, verifica o deriva el
digito de control CUSIP y replica la regla fijada por OpenAP de conservar la
primera observacion valida de cada PERMNO. La union actual no usa ticker solo:
exige CUSIP, un unico `shareClassFIGI` estadounidense de accion ordinaria,
ticker coincidente y nombre de emisor compatible con un unico CIK SEC.

Las formulas tambien quedan fijadas: `AgeIPO` usa edad desde fundacion solo
entre 3 y 36 meses y exige al menos 100 IPO confirmadas en el mes; `IndIPO`
marca 1 entre 3 y 36 meses; `RDIPO` exige mas de 6 y hasta 36 meses y un
`ResearchAndDevelopmentExpense` SEC explicitamente igual a cero. Una etiqueta
R&D ausente nunca se convierte en cero. Los titulos sin union confirmada
permanecen sin valor, porque el fichero termina en 2025 y no demuestra que una
empresa no sea una IPO de 2026 o una cotizacion derivada de SPAC.

Existe un workflow nuevo exclusivamente `workflow_dispatch`; no tiene
disparador por `push`, no redistribuye el Excel bruto y etiqueta cualquier
resultado futuro como `reconstructed_not_strict`. Como el usuario ha prohibido
iniciar un run, no hay cobertura medida ni valores nuevos: los recuentos y el
score estricto permanecen sin cambios.

`ExchSwitch` tampoco necesita Twelve Data. La formula fijada vale 1 cuando la
bolsa actual es NYSE y alguno de los 12 meses anteriores era AMEX/NASDAQ, o
cuando la bolsa actual es AMEX y alguno era NASDAQ. La ruta gratuita preparada
usa los tres facts SEC del mismo contexto (`TradingSymbol`,
`SecurityExchangeName` y `Security12bTitle`) y el endpoint oficial de tickers y
bolsas actual. Solo emite un positivo si dos filings causales de la misma clase
prueban la transicion con un hueco maximo de 160 dias; para emitir cero en NYSE
o NYSE American exige que los 13 inicios de mes queden cubiertos por intervalos
SEC no solapados. NASDAQ actual da cero directamente porque la condicion OpenAP
no puede cumplirse con codigo de bolsa actual 3.

La fecha de aceptacion del filing es la primera fecha causal de deteccion, no
la fecha efectiva mensual CRSP del cambio, y CIK/titulo actual no equivale a un
PERMNO historico. Por eso cualquier salida futura seguira siendo reconstruida y
no estricta. El workflow manual preparado solicita cinco periodos SEC Notes,
fija el hash oficial de la formula, no tiene `push` y no se ha iniciado.

`Spinoff` tiene otra ruta SEC positiva y fail-closed. La formula fijada marca 1
solo a las companias identificadas como escisiones durante sus primeros 24
meses. La preparacion nueva parte de un Form 10-12B/10-12G causal del propio
CIK, descarga de SEC un conjunto acotado de filings posteriores y solo acepta
evidencia que diga expresamente que la escision se completo y contenga su fecha.
Una operacion propuesta, prevista, sujeta a condiciones o sin fecha no produce
valor. La edad desde ese evento permite 1 hasta 24 meses y 0 despues, pero sigue
siendo una reconstruccion: la fecha SEC no es `FirmAgeNoScreen` CRSP ni prueba
historia PERMNO. Las empresas sin evento positivo quedan sin valor, no en cero.
El workflow manual no conserva ni publica los documentos brutos y no se ha
iniciado.

La reauditoria tambien corrige las tres senales de dividendos. `DivInit`,
`DivOmit` y `DivSeason` no pueden depender ya del endpoint `/dividends` de
Twelve Data Basic porque la fuente lo limita a planes de pago. Alpha Vantage
ofrece `DIVIDENDS` con clave gratuita, pero sus terminos consideran comercial
la investigacion y el testing mas alla del uso personal, por lo que no se
autoriza para Aurora. SEC puede aportar evidencia positiva en filings, pero no
entrega un panel mensual equivalente con `exdt` ni los codigos CRSP de
distribucion/frecuencia. Para `DivInit` queda preparada una reconstruccion
positiva y fail-closed: exige nueve trimestres SEC contiguos de dividendos por
accion ordinaria, ocho explicitamente a cero y el actual positivo. Acepta
primero `CommonStockDividendsPerShareCashPaid` y solo despues el declarado;
nunca transforma un fact ausente en cero.

Como el trimestre SEC no revela el dia `exdt`, solo emite 1 cuando la fecha de
formacion sigue dentro de los seis meses incluso suponiendo que el dividendo
ocurrio el primer dia del trimestre. No emite ceros ni alarga el evento desde la
fecha del filing. El run CompanyFacts emitio cero valores, por lo que esta ruta
queda como evidencia de origen pero no como salida final.

`DivOmit` tambien aporta evidencia positiva retrasada SEC. Exige seis
trimestres contiguos con importe explicito positivo y un septimo trimestre con
cero explicito; despues mantiene el 1 durante el mes de disponibilidad del
filing y el siguiente. Esto reproduce la duracion de dos meses, pero no la fecha
exacta: empieza al conocerse el filing y no desde el `exdt` ausente. No emite
ceros. El run CompanyFacts emitio 14 positivos. La consolidacion preparada
conserva ambos resultados SEC como procedencia, pero prioriza las 2.157 clases
0/1 por senal del artefacto OpenAP93: Yahoo aporta ex-dates y permite aplicar
las ventanas mensuales de iniciacion y omision. La salida sigue reconstruida no
estricta porque Yahoo no prueba codigos CRSP ni identidad PERMNO historica y sus
terminos aun requieren cierre.

`DivSeason` queda preparada solo para la fraccion con facts SEC directos de uno
a 45 dias. Exige cuatro eventos regulares para frecuencia trimestral o tres
para semestral/anual, comprueba sus separaciones y aplica los lags oficiales
2/5/8/11, 5/11 u 11. Solo emite el 1 previsto; no emite 0. El cierre del periodo
SEC sigue siendo un proxy de `exdt` y la frecuencia inferida no es el codigo
CRSP `cd3`, por lo que tampoco sera estricta. El run CompanyFacts
`31392473937` ejecuto esta ruta y emitio tres positivos, sin clase cero.

Los 1.191 valores finitos de `DivSeason` del artefacto OpenAP93 no son una
alternativa recuperable: 586 son cero y 605 son uno, pero el calculador aplica
siempre los retardos trimestrales 2/5/8/11. No distingue las reglas oficiales
semestral 5/11 y anual 11, no usa `cd3` y tampoco puede filtrar `cd1=1` y
`cd2=2`. Esos valores se rechazan por fidelidad de formula y no cambian la
cobertura ejecutada de tres positivos SEC.

### Precio: 27

Ruta principal para las formulas OHLCV: los 48 artefactos YFinance ya
adquiridos y ligados por hash + factores Kenneth French + Cboe/FRED cuando
corresponda + SEC para eventos o clasificacion. Twelve Data queda como respaldo.

AnnouncementReturn, Beta, BetaFP, BetaLiquidityPS, BetaTailRisk, betaVIX, CoskewACX, Coskewness, FirmAgeMom, High52, IdioVol3F, IdioVolAHT, IndMom, IndRetBig, Mom6mJunk, MomOffSeason11YrPlus, MomRev, MomVol, PriceDelayRsq, PriceDelaySlope, PriceDelayTstat, RealizedVol, ResidualMomentum, retConglomerate, ReturnSkew3F, Size, TrendFactor.

`betaVIX` solo puede ser proxy desde que VXO dejo de publicarse en 2021. `retConglomerate` exige reconstruir segmentos SEC y no debe llamarse equivalente exacto a Compustat sin validacion.

La reauditoria de los numeros finitos no utilizables del artefacto OpenAP93
rechaza otras tres recuperaciones aparentes:

- Los 561 valores de `AnnouncementReturn` usan la fecha de presentacion del
  10-Q/10-K. La formula fijada usa `rdq`, la fecha de anuncio de resultados, y
  suma las cuatro sesiones -2/-1/0/+1. Un filing periodico posterior mide otro
  evento. La ruta gratuita debe adquirir primero una fecha de anuncio causal
  desde un 8-K Item 2.02 y no reutilizar esos 561 numeros. El recolector SEC ya
  conserva accesion, filing, aceptacion y documento, pero `_submission_rows`
  omite actualmente el vector `items` de Submissions y el parquet tampoco lo
  declara. La implementacion debe retener ese campo, aceptar solo 8-K/8-K/A
  con Item 2.02, extraer la fecha declarada del anuncio de forma fail-closed y
  usar como `available_at` el maximo entre la publicacion causal, la aceptacion
  SEC y la sesion +1 que cierra la ventana de retornos.
- Los 373 valores de `FirmAgeMom` ordenan la edad desde
  `first_clean_price_date`, pero el run solo adquirio 84 meses desde
  2019-08-09. La primera fecha del shard no es la primera aparicion de la
  accion exigida por OpenAP. El calculador recuperado de 16 anos conserva el
  mismo defecto mientras priorice `first_price_date` sobre una fecha de
  cotizacion verificada.
- Los 1.432 valores de `IndRetBig` usan la industria actual de Yahoo. El
  calculador recuperado posterior cambia esa etiqueta por SIC2, pero la formula
  oficial exige transformar SIC a FF48 antes de ordenar capitalizacion y
  promediar el 30 % mayor. Ambas salidas quedan bloqueadas por formula hasta
  usar el mapa FF48 ya fijado en el repositorio.

`MS` presenta el mismo problema fuera del grupo de precio. Sus cuatro numeros
OpenAP93 usan una aproximacion SEC anual; la formula oficial de Mohanram exige
entradas trimestrales, ventanas de 12 y 48 meses, filtro previo por el quintil
bajo de book-to-market y comparaciones SIC2. Los cuatro se rechazan y la ruta
gratuita queda pendiente de implementar sobre historia trimestral SEC.

`VarCF` tiene una ruta gratuita reconstruida tambien mas concreta. La formula
fijada calcula la varianza de `(ib+dp)/mve_permco` en 60 meses con al menos 24
observaciones. CompanyFacts ya retiene ocho contextos anuales y los alias SEC
de ingreso neto y depreciacion; los 48 shards de precio recuperados cubren mas
de cinco anos. No puede ejecutarse todavia con el panel mensual preparado,
porque este repite las acciones actuales a lo largo de todo el historico y usa
ese valor para derivar la capitalizacion mensual. Hace falta resolver acciones
SEC disponibles en cada mes y agregar todas las clases causales del mismo CIK,
con identidad fail-closed. Aun corregido, SEC/Yahoo no demostrara equivalencia
con `ib`, `dp`, `mve_permco` ni PERMNO historico, por lo que la salida sera
`reconstructed_not_strict`.

### Trading: 9

Ruta principal para OHLCV: los 48 artefactos YFinance ya adquiridos y ligados
por hash; FINRA para short interest, SEC para acciones y calendario bursatil.
Twelve Data queda como respaldo.

BidAskSpread, ShortInterest, std_turn, VolMkt, VolSD, VolumeTrend, zerotrade12M, zerotrade1M, zerotrade6M.

FINRA short interest es la posicion corta real y no debe sustituirse por volumen corto diario.

### Ruta de mercado por artefactos existentes, preparada y no ejecutada: 31

Las 31 senales congeladas cuyo bloqueo especifico es OHLCV son las recogidas
por el contrato `TWELVE_DATA_MARKET_SIGNALS`. La auditoria de la formula
oficial elimina del grupo provisional de 36 a `Activism1`, `Activism2`, `Herf`,
`HerfAsset` y `HerfBE`: ninguna consume precio o volumen. Las dos primeras
requieren 13F, G-index y clase de accion; las tres ultimas, contabilidad SEC e
industria. Cualquier fuente OHLCV aporta solo la pata de mercado y no convierte
por si sola ninguna formula en calculada.

La ruta principal ya no necesita registro ni clave. El run `31256096194`
conserva 48 artefactos de una adquisicion ya realizada y sus 48 jobs de precios
terminaron correctamente. El merge auditado `31270341796` reutilizo ese run y
publico `yfinance_source_manifest.csv` con el SHA-256 de cada parquet. El nuevo
recuperador usa HTTP Range para extraer unicamente `prices_NNN.parquet`, valida
hash, filas, simbolos y retrieval time, y mantiene el bruto en artefacto
privado. No contiene endpoints de Yahoo ni realiza peticiones nuevas al
proveedor.

La reauditoria oficial del 2026-08-10 encontro una segunda ruta gratuita con
cuenta: [Tiingo](https://www.tiingo.com/about/pricing). Su plan Free ofrece
decadas de EOD bruto y ajustado para uso interno, pero solo 500 simbolos unicos
al mes; cubrir 2.157 empresas exigiria al menos cinco meses. Finnhub Free no
incluye OHLC historico en su tabla de producto; EODHD Free limita el historico
al ultimo ano y 20 llamadas diarias; Marketstack Free, a un ano y 100 llamadas
mensuales. Ninguna mejora la recuperacion inmediata, sin cuenta nueva, de los
48 artefactos existentes. Tiingo y Twelve Data quedan documentados como
respaldos, no como fuentes primarias ni como excusa para mezclar proveedores
durante una reanudacion.

La implementacion principal preparada aplica estas puertas:

- Recuperacion selectiva por rangos de `security_master.parquet`,
  `execution_summary.json`, `source_manifest.csv` y
  `yfinance_source_manifest.csv` desde el run base correcto, con SHA-256 y
  aceptacion del job fuente; no descarga su ZIP completo. El
  contrato exige `source_sec=sec_company_tickers_exchange`,
  `retrieved_at_sec` valido y el manifiesto oficial SEC; no acepta el fallback
  derivado ni confunde la procedencia Yahoo con la observacion SEC.
- Universo actual fail-closed por `security_id + CIK + ticker + bolsa SEC`.
  Cada simbolo debe aparecer en los shards recuperados; una identidad SEC sin
  historial queda rechazada expresamente y no se transforma en un valor.
- Construccion local dentro de Actions de las dos vistas necesarias,
  `adjust=all` y `adjust=none`, a partir del parquet recuperado. Se limita la
  memoria a 16 anos, suficiente para la ventana oficial maxima de 15 anos, y
  usa `available_at` causal conservador.
- Calculo directo, solo tras validar los 48 hashes, de 9 objetivos cuya formula
  queda preparada:
  `BidAskSpread`, `BetaTailRisk`, `High52`, `MomOffSeason11YrPlus`, `MomRev`,
  `MomVol`, `RealizedVol`, `VolSD` y `VolumeTrend`. El runner construye las
  vistas nominal y
  ajustada, excluye sesiones incompletas y publica solo observaciones derivadas.
- Workflow solo manual y obligado a repositorio privado. Los OHLCV se separan
  en un artefacto interno. Un artefacto derivado de 31 salidas no se considera
  valido mientras las tres `zerotrade` conserven la formula incorrecta; la
  salida aceptable debe excluirlas o corregirlas, conservar el origen y las
  formulas y mantener siempre score estricto cero.

No se ha iniciado ningun run nuevo de mercado. De las 31 rutas, 25 permanecen
`prepared_unexecuted`, cinco quedan `blocked_formula_fidelity` y una
`blocked_source_staleness`. Hay 25 calculadores preparados: 9 directos, 11 que
combinan el panel recuperado con los ZIP publicos diario y mensual de Kenneth
French (`Beta`, `BetaFP`, dos variantes
de coskewness, dos momentos residuales FF3, `IdioVolAHT`,
`ResidualMomentum` y las tres
variantes `PriceDelay`). Los factores se congelan por SHA-256 durante todas las
reanudaciones. El ensamblado calcula ademas `BetaTailRisk`, `MomRev` y `MomVol`
sobre el universo completo, como exigen sus cortes transversales. Los cinco
calculadores adicionales preparados son `IndMom`, `Size`, `TrendFactor`,
`VolMkt` y `std_turn`. `FirmAgeMom` e `IndRetBig` quedan fuera por los fallos
de edad truncada y SIC2 frente a FF48 descritos arriba. `BetaLiquidityPS`
tambien queda fuera: la serie oficial gratuita de Chicago Booth solo llega a
diciembre de 2025 y no es actual para julio de 2026. Faltan ejecucion,
intervalos historicos de ticker, cobertura y fidelidad. No cambian los
recuentos ejecutados ni el score estricto de 31.

Las tres variantes `zerotrade` no forman parte de esos 25 calculadores. El
artefacto OpenAP93 contiene 2.150 numeros por variante, pero usa las ultimas
21/126/252 sesiones hasta el 7 de agosto de 2026 y acciones actuales. El
calculador compartido preparado usa solo la fraccion de sesiones con volumen
cero. Ninguno replica la formula fijada: agregacion por meses completos de
`vol/shrout`, ajustes 480.000/11.000 y desplazamiento de un mes. Esos 6.450
numeros no son valores actuales de la formula oficial y siguen bloqueados.

La novena ruta directa es `BidAskSpread`. Calcula el estimador estandar
Corwin-Schultz de dos dias con los maximos y minimos nominales del ultimo mes
completo. OpenAP, sin embargo, importa `hlspread` desde un fichero preparado por
un programa SAS no publicado. Por ello esta implementacion se etiqueta como
proxy reconstruido y nunca como equivalencia estricta.

La capa de corroboracion SEC tambien queda preparada de extremo a extremo en
codigo y sin ejecutar. El workflow SEC Notes es exclusivamente manual y acepta
un periodo `YYYYqN` o `YYYY_MM`; no tiene disparador por `push`. Cada ZIP debe
coincidir exactamente con un manifiesto oficial descargado por HTTP 200, tamano
y SHA-256. El cargador lee `TXT` por bloques, restringe CIK y conceptos y
normaliza `TradingSymbol`, `SecurityExchangeName` y `Security12bTitle` solo
cuando coinciden en un contexto de un filing periodico oficial y causal. Rechaza
enmiendas, periodos solapados, clases o contextos ambiguos, cambios de identidad,
fechas invalidas y huecos superiores a 160 dias. El runner liga tambien el
`security_master` y su manifiesto de recuperacion por SHA-256. Los tramos
resultantes siguen marcados como `historical_ticker_interval_verified=false` y
no son PERMNO. Falta adquirir los ZIP historicos y ejecutar esta normalizacion:
los archivos son voluminosos y el acceso GitHub ya mostro HTTP 403. El catalogo
oficial comprobado el 2026-08-10 publica `2026_07_notes.zip` con 102,91 MiB, de
modo que ese 403 es un fallo de transporte concreto y no ausencia o pago de la
fuente. Esta implementacion preparada no aumenta ningun recuento.

### Otras: 11

Ruta principal segun senal: USPTO para patentes; BEA/Census para redes
industriales; SEC Notes/filings para empleados, segmentos y clientes;
artefactos de mercado ya adquiridos para retornos, con Twelve Data de respaldo.

CitationsRD, CustomerMomentum, FirmAge, Herf, HerfAsset, HerfBE, hire, iomom_cust, iomom_supp, PatentsRD, sinAlgo.

`CustomerMomentum`, `FirmAge` y `sinAlgo` son reconstrucciones actuales: los
campos publicos existen, pero la semantica Compustat/CRSP y la cobertura deben
medirse.

Para `sinAlgo` queda preparada una ruta positiva sin fuente de pago. Usa el SIC
del ultimo filing SEC causal y emite 1 solo para cerveza (`2080-2085`) o tabaco
(`2100-2199`), que son dos reglas literales de la formula fijada. No emite 0 ni
clasifica gaming: faltan NAICS/segmentos completos, el backfill historico, los
codigos de accion CRSP y el grupo comparable. La salida futura sera
`reconstructed_not_strict`; no se ha ejecutado ni medido su cobertura.

`CitationsRD` y `PatentsRD` tampoco carecen de datos gratuitos. PatentsView
publica datos desambiguados hasta diciembre de 2025 y su documentacion aplica
CC BY 4.0 a las descargas y a la API. El dataset academico KPSS fijado en el
repositorio ya aporta patentes, citas totales y enlace PERMNO/PERMCO hasta
2024; sus tres archivos estan fijados por SHA-256 y los autores piden cita,
pero no autorizan redistribuir los archivos brutos.

El bloqueo es de construccion y fidelidad. Para `CitationsRD` hay que derivar
las citas recibidas durante cinco anos, escalarlas por ano y subcategoria y
aplicar los lags de OpenAP; el campo KPSS `cites` es un total y no sustituye
`ncitscale`. Para `PatentsRD` debe formarse el capital de R&D de seis anos y
unir causalmente patentes con el emisor. El artefacto SEC actual ya contiene
1.955 valores utilizables de R&D sobre activos, por lo que R&D no es una
fuente ausente, aunque esa razon no es todavia el capital de R&D oficial. La
identidad PatentsView/KPSS -> CIK/titulo sigue sin estar demostrada y debe
fallar cerrada ante nombres ambiguos.

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
