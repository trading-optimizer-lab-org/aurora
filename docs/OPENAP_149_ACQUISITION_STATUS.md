# Estado de adquisicion de las 149 senales OpenAP

Extraccion fail-closed de artefactos ya verificados.
No incorpora ninguna senal al score estricto.

- Senales objetivo: 149
- Senales con datos adquiridos por ruta gratuita aprobada: 56
- Senales con valor calculado: 50
- Senales aptas para el score estricto: 0
- Reconstruidas pero no estrictas: 18
- Bloqueadas o pendientes: 99
- Filas empresa-senal conservadas: 96814
- Fecha maxima de formacion: `2026-08-09T23:59:59+00:00`

Los valores conservados solo quedan demostrados hasta esa fecha de formacion.

## Recuento por estado

- `blocked_coverage`: 4
- `blocked_fidelity`: 39
- `blocked_source_failure`: 56
- `current_signal_computed`: 50

- SHA-256 de valores fuente: `f173b7cdfe568aabfa95b17267844f10e6cf3ceeb6df69a66d9a66993312c8d8`
- SHA-256 del inventario de formulas: `dfb2a6d0553cddc5ff11fd210f57cfae034510cf90bdda480da036d2aa370ecb`

La matriz registra fuentes permitidas, hashes de formulas oficiales,
fechas point-in-time, cobertura y bloqueo pendiente por senal.

## Reconciliacion fail-closed posterior

El recuento anterior esta demostrado por el manifiesto emitido en el run
`31354890734`. El run termino en fallo porque aun contenia las aserciones
antiguas `57/53/96/99824`; la consolidacion termino correctamente antes de
esa comprobacion y emitio `56/50/99/96814`. El contrato corregido paso
despues 60 pruebas en el run `31355047369`.

Las filas de `CBOperProf`, `DelNetFin` y `EarningsConsistency` del CSV
publicado por el run anterior a la correccion no son utilizables: su evidencia
declara `current_usable=False` y el contrato actual las pone en cuarentena.
El CSV se conserva sin reescribir manualmente porque el usuario ha prohibido
iniciar un nuevo run y no existe un artefacto publicado del run fallido.

`ChInvIA` queda tambien preparada sin ejecutar a partir de CompanyFacts y
submissions SEC: CAPEX anual, respaldo por cambio de PP&E y ajuste por la media
del SIC SEC a dos digitos. Falla cerrado ante periodos, hechos o SIC ambiguos.
La salida futura sera reconstruida y no estricta porque SIC SEC actual y
CIK/ticker no equivalen al historial CRSP/PERMNO. No altera los recuentos
ejecutados anteriores.

## Tres senales IPO: fuente gratuita y ruta completa preparadas

`AgeIPO`, `IndIPO` y `RDIPO` no necesitan Twelve Data. El Excel oficial
Field-Ritter `IPO-age.xlsx` respondio HTTP 200 el 2026-08-10, pesa 1.346.041
bytes, fue modificado el 2026-01-19 y contiene 16.030 registros con fecha de
oferta, nombre, ticker, CUSIP, PERMNO y ano de fundacion. El documento oficial
indica que cubre 1975-2025, incluye direct listings, excluye cotizaciones por
fusion con SPAC y solicita citar el dataset.

La implementacion preparada, todavia sin ejecutar:

- descarga una sola vez el fichero oficial mediante un workflow exclusivamente
  manual, conserva HTTP, `Last-Modified`, tamano y SHA-256 y no publica el Excel
  bruto;
- parsea el XLSX con biblioteca estandar, esquema exacto y limites contra ZIP
  malicioso, sin introducir `openpyxl` como dependencia del proyecto;
- replica la seleccion OpenAP de la primera fila valida por PERMNO y conserva
  el digito de control CUSIP;
- enlaza CUSIP con un unico `shareClassFIGI` de accion ordinaria de EE. UU. y
  exige coincidencia de ticker y nombre con un CIK SEC no ambiguo; ticker solo
  nunca basta;
- aplica 3-36 meses para `AgeIPO`/`IndIPO`, la puerta mensual de 100 IPO para
  `AgeIPO` y mas de 6 hasta 36 meses para `RDIPO`;
- para `RDIPO`, solo trata como cero un
  `ResearchAndDevelopmentExpense` anual SEC explicitamente igual a cero. Una
  etiqueta ausente queda sin valor.

La cobertura 2026 y las nuevas cotizaciones por SPAC siguen necesitando una
ruta SEC primaria. El puente actual tampoco prueba un intervalo historico
CRSP-CIK. Por ello la salida futura sera `reconstructed_not_strict`; mientras
no se ejecute el workflow, estas tres senales siguen sin valor nuevo y los
recuentos ejecutados permanecen `56/50/18/99/96814`.

## OScore: ruta gratuita preparada, pendiente de reconsolidar

- Formula OpenAP fijada: usa el deflactor GNP dentro del Ohlson O-Score y
  despues forma deciles transversales.
- Fuente nueva autorizada solo para esta senal: `fred_public_csv`, serie
  `GNPDEF`, con origen BEA, frecuencia trimestral, acceso sin clave y etiqueta
  `Public Domain: Citation Requested`.
- Evidencia existente: el artefacto `openap-93-current-recovered-results` del
  run `31341580689` contiene 2157 filas de OScore; 1100 declaran
  `current_usable=True`, formula
  `openap_ohlson_oscore_decile_sec_gnpdefl` y fuente
  `sec_edgar|fred_public_csv`.
- Clasificacion: reconstruida, no estricta. No se incorpora al score estricto.
- Resultado esperado al reconsolidar, todavia no declarado como ejecutado:
  57 adquiridas, 51 calculadas, 19 reconstruidas no estrictas, 98 bloqueadas
  y 97914 filas empresa-senal.

## OrgCap: falso bloqueo de fuente corregido, pendiente de reconsolidar

- La formula oficial usa SG&A real, depreciacion anual del 15 %, escala por
  activos, winsorizacion transversal y ajuste por industria FF17.
- El pipeline existente ya emitia una reconstruccion gratuita con SEC
  CompanyFacts y `GNPDEF` de FRED, pero la matriz de rutas no autorizaba FRED
  para `OrgCap`; por eso la consolidacion la rechazaba como fuente no aprobada.
- La ruta autoriza ahora `fred_public_csv` y ya no exige Twelve Data. No se ha
  ejecutado una nueva consolidacion, por lo que los recuentos demostrados no
  cambian.
- La reconstruccion existente sigue siendo no estricta: usa SIC SEC actual a
  dos digitos, no SIC historico CRSP/FF17, y aun debe demostrar continuidad de
  historia, cobertura e identidad antes de una validacion de solapamiento.

## Credencial gratuita pendiente para mercado

Las 31 rutas cuyo bloqueo especifico es el OHLCV de Twelve Data requieren el
secreto `TWELVE_DATA_API_KEY`. El plan Basic es gratuito, permite uso interno
no visible y ofrece 8 creditos por minuto y 800 al dia. La ausencia de esa
clave es un bloqueo de credencial gratuita, no prueba de que los datos sean
de pago o imposibles de obtener.

La ruta de adquisicion queda preparada en codigo, pero no ejecutada:

- Parte del `security_master.parquet` del run verificado `31270341796`. Lo
  recupera por rangos junto con `execution_summary.json` y
  `source_manifest.csv`, sin descargar el artefacto completo. Exige que el
  run, el job `merge` y sus dos pasos de aceptacion hayan terminado
  correctamente, liga los tres miembros por SHA-256 y rechaza el fallback SEC
  derivado. El contrato usa los nombres reales posteriores al merge,
  `source_sec` y `retrieved_at_sec`; no acepta como sustitutos los campos Yahoo
  ni columnas sin sufijo. Tambien comprueba las puertas `locked_opened=false`,
  `backtest_enabled=false`, `validation_used_for_selection=false` y
  `partial=false`.
- Conserva solo acciones ordinarias primarias y aptas para ranking con una
  identidad actual no ambigua `security_id + CIK + ticker + bolsa SEC`. Rechaza
  OTC, duplicados y cualquier discrepancia; la respuesta de Twelve Data debe
  corroborar simbolo, bolsa, MIC, tipo, USD y zona `America/New_York`.
- Para las 2.157 empresas conocidas planifica 4.314 peticiones de un credito:
  2 por empresa, `adjust=all` para retornos y `adjust=none` para precio y
  volumen nominales. Pide 182 meses, suficientes para el maximo oficial de
  180 meses de `MomOffSeason11YrPlus` mas margen.
- El minimo teorico es 6 cupos diarios y 540 minutos limitados a 8 peticiones
  por minuto, sin contar reintentos. Cada invocacion consume como maximo 800
  creditos, guarda checkpoint por peticion y puede reanudarse con un artefacto
  interno anterior. Cada evento queda ligado por hash al commit de
  implementacion, run y artefacto fuente, security master, fecha de formacion,
  plan de peticiones, conjunto de 31 senales y contrato `available_at`; se
  rechaza mezclar checkpoints de planes o revisiones distintas.
- La clave viaja solo en la cabecera `Authorization`; nunca entra en URL,
  checkpoint o manifiesto. Los OHLCV quedan en un artefacto restringido de un
  repositorio privado durante 10 dias. El artefacto publicable contiene plan,
  identidad, manifiesto y solo las observaciones derivadas no reversibles;
  nunca publica filas OHLCV.
- El workflow es exclusivamente manual (`workflow_dispatch`) y se niega a
  adquirir en un repositorio publico. No existe disparador por `push`.
- Cuando las 4.314 peticiones terminan correctamente, el mismo runner calcula
  ya once senales directas: `BetaTailRisk`, `High52`,
  `MomOffSeason11YrPlus`, `MomRev`, `MomVol`, `RealizedVol`, `VolSD`,
  `VolumeTrend`, `zerotrade1M`,
  `zerotrade6M` y `zerotrade12M`. Exige
  por empresa los dos historicos ligados por hash, excluye sesiones
  incompletas y no convierte faltantes en cero. Si queda una sola peticion
  pendiente o fallida, no genera el artefacto derivado.
- Las tres formulas transversales (`BetaTailRisk`, `MomRev` y `MomVol`) se
  calculan sobre el universo completo, no empresa por empresa. Se corrigio el
  ensamblado preparado del runner para que no redujera accidentalmente cada
  corte transversal a una sola empresa.
- Ademas quedan preparados once calculadores que combinan esos OHLCV con dos
  ZIP publicos y gratuitos de Kenneth French: `Beta`, `BetaFP`,
  `CoskewACX`, `Coskewness`, `IdioVol3F`, `IdioVolAHT`, `PriceDelayRsq`,
  `PriceDelaySlope`, `PriceDelayTstat`, `ResidualMomentum` y `ReturnSkew3F`.
  Los ZIP diario y
  mensual se congelan por SHA-256 en la primera invocacion y se reutilizan en
  cada reanudacion, evitando mezclar revisiones de factores. `Beta` reproduce
  la ventana movil de 60 meses con minimo 20 y mercado equiponderado;
  `BetaFP` usa volatilidad de 252 sesiones y correlacion de retornos solapados
  de tres dias en 1.260 sesiones; las tres medidas de retraso comparten la
  regresion anual julio-junio con cuatro retardos del mercado y disponibilidad
  desde julio. Las otras seis respetan las ventanas oficiales de 12 o 60
  meses, el minimo mensual de 15 sesiones para residuos FF3 y las regresiones
  moviles de 36 meses para momentum residual. `IdioVolAHT` replica por separado
  el RMSE CAPM de 252 observaciones con minimo 100.

Estado exacto: `prepared_unexecuted`. Falta que el usuario facilite una clave
gratuita de Twelve Data y una ejecucion privada compatible con sus terminos.
Hay 23 calculadores preparados: 12 directos y 11 con factores franceses
gratuitos. `BidAskSpread` usa el estimador estandar Corwin-Schultz sobre maximos
y minimos nominales, pero permanece como proxy no estricto porque OpenAP carga
un fichero preprocesado por SAS cuyo tratamiento exacto no esta publicado. Las
otras 8 rutas necesitan sus entradas o transformaciones adicionales. En todas habra
que completar los intervalos
historicos de ticker y medir cobertura y fidelidad. Por ello las 31 siguen sin
valor nuevo y con
`strict_score_eligible=false`. Esta cifra corrige el grupo provisional de 36:
`Activism1`, `Activism2`, `Herf`, `HerfAsset` y `HerfBE` no consumen OHLCV en
su formula oficial. Los tres `Herf` ya estaban entre los valores SEC
calculados; las dos `Activism` siguen bloqueadas por gobierno corporativo,
clase de accion e identidad, no por la clave de mercado. Los recuentos
ejecutados permanecen `56/50/18/99/96814` y el score estricto confirmado
permanece en 31.

La SEC ofrece una base gratuita para corroborar identidad historica, pero no
un intervalo listo para usar. Los filings Inline XBRL pueden etiquetar
`dei:TradingSymbol`, `dei:SecurityExchangeName` y `dei:Security12bTitle` en el
mismo contexto del CIK y de la accesion. El JSON general de submissions solo
describe asociaciones de ticker y bolsa y la propia SEC no garantiza su
exactitud o alcance. Por tanto, no se usara como historial ni se extendera el
ticker actual hacia atras.

La capa de identidad queda preparada de extremo a extremo en codigo, pero no
ejecutada. El acceso SEC Notes es solo manual y parametrizable por periodo; no
tiene disparador por `push`. El cargador exige por cada ZIP manifiesto oficial,
HTTP 200, tamano y SHA-256 exactos, lee `TXT` por bloques y filtra unicamente los
CIK actuales y los tres conceptos de cotizacion. La normalizacion exige los tres
facts en el mismo contexto, CIK, accesion, formulario periodico sin enmienda,
`accepted_at` causal y URL oficial cuyo path corresponda al CIK y la accesion.
Rechaza clases multiples, contextos ambiguos, fechas malformadas, periodos
solapados, cambios de simbolo o titulo y huecos de mas de 160 dias. Solo genera
tramos corroborados entre dos observaciones o
entre la ultima observacion y el endpoint SEC actual. Incluso en esos tramos
mantiene `historical_ticker_interval_verified=false` y
`strict_score_eligible=false`: es evidencia
`historical_identity_corroborated`, no equivalencia PERMNO.

La documentacion SEC vigente confirma que el JSON principal de submissions
contiene al menos un ano o 1.000 filings y referencia ficheros adicionales para
el historial anterior. El dataset Financial Statement and Notes incluye los
facts no numericos en `TXT` y sus dimensiones en `DIM`, pero sus ZIP historicos
son de cientos de MiB por periodo y el intento previo desde GitHub termino en
HTTP 403. El catalogo oficial comprobado el 2026-08-10 si publica
`2026_07_notes.zip` con 102,91 MiB; por tanto, aquel 403 es un fallo de ese
transporte, no evidencia de inexistencia, pago ni bloqueo global de la fuente.
Falta elegir y ejecutar una ingestion oficial acotada de esos facts;
El runner liga ademas ZIP, manifiesto SEC Notes, `security_master`, manifiesto
SEC actual y manifiesto de recuperacion mediante hashes. Sus salidas declaran
explicitamente `historical_ticker_interval_verified=false`,
`market_bars_acquired=false` y `strict_score_eligible=false`.

Sobre esa evidencia queda preparado el calculo causal de `ExchSwitch`. Replica
la condicion OpenAP de bolsa actual NYSE/AMEX frente a los 12 meses anteriores,
pero falla cerrado: un 1 exige una transicion entre dos filings de la misma
clase con un hueco maximo de 160 dias; un 0 para NYSE o NYSE American exige
cobertura SEC de los 13 inicios de mes. El workflow manual
`openap-149-sec-exchange-switch.yml` descarga solo los cinco periodos Notes
necesarios, comprueba la formula oficial por SHA-256 y publica solo derivados y
manifiestos. No se ha ejecutado. La aceptacion SEC no es la fecha efectiva CRSP
y el puente CIK no es PERMNO; la salida seguira siendo reconstruida no estricta.
Hasta ejecutar y medir cobertura, esta mejora no cambia valores ni recuentos.

## Spinoff: prueba SEC positiva preparada

La formula OpenAP usa la clasificacion `SpinoffCo` de CRSP y la mantiene durante
los primeros 24 meses de `FirmAgeNoScreen`. La ruta gratuita preparada no
rellena ceros por ausencia. Selecciona CIK actuales con un Form 10-12B/10-12G
causal, descarga de SEC como maximo 24 documentos por titulo y exige una frase
de finalizacion junto a una fecha efectiva. Operaciones propuestas, previstas o
sujetas a condiciones se rechazan.

El calculo futuro emitira 1 durante los 24 meses siguientes a la fecha probada
y 0 despues; los demas titulos quedaran sin valor. La fecha de escision SEC es
un proxy de edad y no equivale a la primera observacion CRSP/PERMNO, por lo que
todo resultado sera `reconstructed_not_strict`. El workflow manual
`openap-149-sec-spinoff.yml` fija el hash de la formula, usa identidad SEC
actual, respeta fair access, no conserva documentos brutos y no tiene `push`.
No se ha ejecutado y no cambia los recuentos actuales.

## Dividendos: la antigua ruta Basic no es valida

La documentacion actual de Twelve Data reserva `/dividends` a Grow/Venture o
superior. Alpha Vantage documenta `DIVIDENDS` con clave gratuita, pero sus
terminos clasifican la investigacion y el testing fuera del uso personal como
uso comercial; no es una fuente autorizada para Aurora. SEC sigue siendo una
fuente publica para evidencia positiva, pero no aporta directamente los codigos
CRSP `cd1/cd2/cd3`, un calendario `exdt` completo ni la ausencia mensual
necesaria para reproducir exactamente `DivInit`, `DivOmit` y `DivSeason`.

Para `DivInit` queda preparada, sin ejecutar, una ruta SEC positiva y
fail-closed. Retiene 48 contextos de dividendos por accion ordinaria y exige
nueve trimestres contiguos: los ocho anteriores deben declarar cero y el actual
un importe positivo. Prioriza el tag de efectivo pagado y usa el declarado solo
como respaldo. Nunca convierte un fact ausente en cero. Como falta `exdt`, solo
emite 1 si la formacion cae dentro de la ventana oficial de seis meses incluso
suponiendo que el evento ocurrio el primer dia del trimestre; no emite ceros.
Seguira siendo reconstruccion no estricta y su cobertura no esta medida.

`DivOmit` tambien queda preparado como evidencia positiva retrasada: exige seis
trimestres consecutivos con dividendo explicito y un septimo con cero explicito,
y mantiene 1 durante el mes de disponibilidad SEC y el siguiente. No inventa
ausencias ni emite ceros, pero esa ventana empieza en el filing y no en el
`exdt`; por tanto, sigue siendo proxy no estricto.

`DivSeason` queda preparada solo para facts SEC directos de uno a 45 dias.
Exige varios eventos con separaciones regulares, infiere una frecuencia
trimestral, semestral o anual y aplica los lags oficiales. Solo emite el 1
previsto; nunca un 0. El cierre SEC no es `exdt` y la frecuencia inferida no es
el codigo CRSP `cd3`, de modo que la salida seguira siendo no estricta y con
cobertura pendiente de medir.

## Cuatro senales contables sin dependencia de precio

`DelDRC`, `ConvDebt`, `OrderBacklog` y `OrderBacklogChg` se han separado de
Twelve Data: sus formulas solo necesitan datos contables SEC e identidad. No
se aumenta por ello el recuento ejecutado, porque todavia no hay observaciones
utilizables en el artefacto consolidado.

- La API CompanyFacts agrega taxonomias no personalizadas y hechos de entidad
  completa; no garantiza los desgloses personalizados necesarios.
- El dataset Financial Statement and Notes contiene etiquetas estandar y
  personalizadas, valores `as filed`, accesion y fecha/hora `accepted`.
- El run existente `31343497010` solicito solo `2026_07_notes.zip`: la descarga
  real fue 0/1 y termino en `HTTP 403` despues de cinco intentos. El workflow
  global salio verde porque su contrato consistia en conservar tanto exito
  como bloqueo; no demuestra adquisicion. El archivo figura actualmente en el
  catalogo oficial SEC, asi que tampoco demuestra que la fuente sea inaccesible.
- El filing de Apple conservado por el run `31347614238` contiene deferred
  revenue total para 2025 y 2024. Prueba disponibilidad en el filing, pero la
  URL SEC directa dio 403 y el contenido se obtuvo por readthrough, cuya
  autorizacion como transporte de produccion sigue pendiente.
- `DelDRC` y las dos formulas de backlog ya tienen calculador y pruebas
  sinteticas. Falta el ingreso causal de etiquetas personalizadas y medir
  cobertura real.
- El cero de etiquetas `ConvDebt` del run diagnostico `31342908279` no era una
  prueba de ausencia global: los shards fuente solo conservaban la lista
  cerrada de alias contables y excluian los conceptos de deuda convertible.
  Se ha preparado, sin ejecutarla, la retencion acotada de etiquetas SEC y un
  calculador positivo y fail-closed. Solo emite `1` ante evidencia causal del
  ultimo periodo anual; nunca convierte ausencia, una etiqueta amplia o un
  hecho antiguo en `0`. Sigue siendo reconstruccion no estricta hasta validar
  la equivalencia de `dc`/`cshrc` y medir cobertura real.

## DelNetFin: dos periodos anuales SEC preparados

La formula fijada de `DelNetFin` calcula el cambio a doce meses de inversiones
corrientes y de largo plazo menos deuda corriente, deuda de largo plazo y
acciones preferentes, dividido por activos medios. La preparacion oficial
aplica seis meses de retraso al cierre anual y convierte la accion preferente
faltante en cero.

La ruta preparada, sin ejecutar, exige dos cortes SEC anuales alineados para
`Assets`, `ShortTermInvestments`/`MarketableSecuritiesCurrent`,
`LongTermInvestments`/`OtherInvestments`, `LongTermDebtNoncurrent` y
`LongTermDebtCurrent`. No acepta `LongTermDebt` total ni
`ShortTermBorrowings` como sustitutos que puedan duplicar u omitir deuda. Usa
una sola etiqueta por componente, reproduce el calendario de seis meses y
falla cerrado ante cualquier hueco, conflicto o desalineacion. La accion
preferente sigue la regla de cero de la formula oficial.

La salida futura sera `reconstructed_not_strict`: los agregados XBRL no prueban
equivalencia con `ivst/ivao/dltt/dlc/pstk`, la vintage SEC actual puede contener
restatements y CIK/ticker no es GVKEY/PERMNO historico. Las antiguas filas
inutilizables siguen en cuarentena y los contadores ejecutados no cambian.

## EarningsConsistency: formula anual SEC preparada

La formula fijada de `EarningsConsistency` usa `epspx` anual, no EPS
trimestral. La preparacion oficial de OpenAP aplica un retraso de seis meses al
cierre fiscal, replica cada observacion durante doce meses, calcula cinco
crecimientos interanuales separados por doce meses y aplica filtros de magnitud
y consistencia de signo.

Se ha preparado, sin ejecutar, una ruta gratuita con
`EarningsPerShareBasic` de CompanyFacts. Conserva ocho contextos anuales por
etiqueta, acepta solo hechos anuales de `10-K/10-K/A` con unidad `USD/shares`,
exige que todo hecho estuviera disponible antes de la formacion, reproduce el
retraso oficial y replica la semantica oficial de faltantes y excepciones. La
vintage SEC corriente puede contener restatements posteriores al mes historico
representado; esa limitacion impide tratarla como point-in-time estricta. El
runner SEC y las pruebas sinteticas quedan conectados.

El batch rechaza expresamente los shards del run `31270341796`: son anteriores
a este contrato de retencion y no prueban que contengan EPS basico, los 48
contextos trimestrales, los componentes agregados de `DelNetFin` ni dividendos
por accion. Un futuro calculo necesitara primero una adquisicion SEC nueva que
declare el contrato versionado en los 48 manifiestos.

La salida futura sera `reconstructed_not_strict`: el EPS basico SEC no prueba
equivalencia con `epspx` Compustat y la identidad CIK/ticker actual no sustituye
GVKEY/PERMNO historico. Los 13 valores del artefacto anterior siguen en
cuarentena, no se ha medido cobertura y los contadores ejecutados no cambian.

## Dos sorpresas trimestrales SEC: historia completa preparada

`EarningsSurprise` y `RevenueSurprise` tienen los datos brutos SEC marcados
como adquiridos, pero el artefacto ejecutado no genero ningun valor por historia
trimestral normalizada insuficiente. La formula actual necesita 21 trimestres
contiguos para formar la sorpresa corriente, la deriva de ocho cambios
interanuales y la desviacion tipica de ocho sorpresas anteriores.

La preparacion nueva conserva hasta 48 contextos de ingresos, ventas y acciones
medias basicas por etiqueta en los shards CompanyFacts y reconstruye cada
trimestre desde hechos acumulados SEC.
Los flujos se obtienen por diferencia y las acciones medias se separan usando
los dias de cada tramo. Se rechazan huecos, unidades incorrectas, etiquetas
mezcladas, conflictos y hechos disponibles despues de la formacion. El runner
SEC existente queda conectado a ambos calculos y a pruebas sinteticas de los 21
trimestres, pero no se ha ejecutado.

Aunque produzca valores, la salida seguira siendo `reconstructed_not_strict`:
ingreso SEC por acciones medias no demuestra equivalencia con `epspxq`, ventas
SEC por acciones no son por si solas `revtq/cshprq` Compustat y la identidad
CIK/ticker actual no es un intervalo GVKEY/PERMNO. Los contadores ejecutados
siguen en `56/50/18/99/96814`.

## sinAlgo: SIC positivo SEC preparado

`sinAlgo` tampoco carece por completo de fuente gratuita. La formula fijada
clasifica directamente cerveza con SIC `2080-2085` y tabaco con SIC
`2100-2199`. Queda preparado, sin ejecutar, un calculador que toma el SIC del
ultimo filing SEC disponible antes de la formacion y solo emite 1 para esos
rangos. Un conflicto en el ultimo timestamp queda sin valor.

No emite 0 ni clasifica gaming: la SEC submissions no aporta por si sola los
NAICS y segmentos completos, el backfill historico, los codigos de accion CRSP
ni el grupo comparable. Cualquier valor futuro sera
`reconstructed_not_strict`; cobertura y fidelidad siguen sin medir.

## Dos senales de patentes con datos gratuitos parciales

`CitationsRD` y `PatentsRD` disponen de dos fuentes gratuitas complementarias:

- PatentsView/USPTO ofrece bulk downloads actualizados hasta diciembre de
  2025 y licencia CC BY 4.0. La API requiere clave, limita a 45 peticiones por
  minuto y actualmente no concede claves nuevas; el bulk evita esa dependencia.
- KPSS aporta patentes, citas totales y enlace PERMNO/PERMCO hasta 2024, con
  archivos fijados por hash y uso con cita, pero sin permiso explicito para
  redistribuir los brutos.
- SEC ya produjo 1.955 observaciones utilizables de R&D sobre activos. Esto
  prueba disponibilidad de R&D, no la construccion oficial de capital de R&D.

Siguen a cero en la matriz ejecutada. `CitationsRD` necesita reconstruir
`ncitscale` a cinco anos por subcategoria; `PatentsRD`, el capital de R&D de
seis anos. Ambas requieren una union causal y no ambigua entre patente,
PERMNO/PERMCO, CIK y titulo. No se ha ejecutado esa union ni medido cobertura.

## IO_ShortInterest: entradas gratuitas adquiridas por separado

La formula fijada de OpenAP requiere el ratio mensual `shortint/shrout`, su
percentil 99 transversal y `instown_perc` para los titulos que alcanzan ese
corte. No requiere precio ni capitalizacion.

- El manifiesto verificado del run `31333714423` conserva 6.975.953 posiciones
  SEC 13F, de las que 4.182.960 quedaron enlazadas mediante OpenFIGI; el ultimo
  periodo institucional disponible es 2026-03-31 y la ultima presentacion
  causal es de 2026-05-29.
- El run `31340242772` ya calculo 2.988 ratios `ShortInterest` con FINRA
  2026-07-15, publicado el 2026-07-24, y acciones SEC.
- El artefacto `31341580689` contiene 1.478 valores `DelBreadth` utilizables,
  prueba de que la ruta SEC 13F + OpenFIGI funciona. Sus 2.157 filas de
  `IO_ShortInterest` siguen vacias porque proceden del pipeline Yahoo anterior,
  no de una union con FINRA.

Por ello se elimina Twelve Data de esta ruta. El calculador y su conexion con
el runner FINRA quedan preparados, sin ejecutar:

- Calcula el percentil 99 sobre todo el universo FINRA/SEC antes de aplicar la
  cobertura 13F/OpenFIGI.
- Solo usa el ultimo trimestre 13F cuyo plazo legal de 45 dias ya ha terminado.
- Rechaza mapeos OpenFIGI ambiguos y cualquier union basada solo en ticker. El
  CUSIP debe resolver a un unico `shareClassFIGI` de accion ordinaria con
  `exchCode=US`, y el nombre del emisor 13F debe coincidir, de forma
  conservadora, con el nombre SEC del CIK. Tambien rechaza denominadores
  futuros y ausencias de propiedad institucional no demostrables; no inventa
  ceros.
- Recupera por rangos HTTP unicamente los tres parquets institucionales del
  artefacto `31333714423`, comprueba sus hashes y aborta antes de descargarlos
  si superan en conjunto 128 MiB comprimidos. El directorio central remoto
  declara 85.159.102 bytes para esos tres miembros y el manifiesto, frente a
  2.741.147.673 bytes del ZIP completo; no descarga el ZIP completo.
- Etiqueta cualquier resultado futuro como `reconstructed`, nunca estricto,
  porque SEC 13F/OpenFIGI/SEC shares no equivalen al panel Thomson/CRSP.

La prohibicion de iniciar un nuevo run mantiene la ruta en
`prepared_unexecuted`: cobertura sin medir, cero valores actuales publicados y
ningun aumento del recuento ejecutado ni del score estricto.
