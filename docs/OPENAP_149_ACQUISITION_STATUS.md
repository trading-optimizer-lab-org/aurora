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
declara `current_usable=False`. El nuevo lote CompanyFacts `31392473937`
sustituye esa evidencia de origen para `DelNetFin` y `EarningsConsistency`;
solo `CBOperProf` conserva la cuarentena en el contrato de consolidacion
preparado. El CSV se conserva sin reescribir manualmente porque el usuario ha
prohibido iniciar un nuevo run y aun no existe un artefacto consolidado nuevo.

## CompanyFacts ampliado: lote gratuito ejecutado, pendiente de consolidar

El run `31392473937` termino correctamente y publico
`openap-149-sec-companyfacts-current`. Su manifiesto declara 3.734.050 hechos
CompanyFacts procesados, 134.417 observaciones causales, 95.936 valores actuales
y 48 senales calculadas con formacion `2026-08-09T00:00:00Z`. No abrio
`OOS_LOCKED` ni `FORWARD`, no uso validacion para seleccionar y no promociono
ninguna senal al score estricto.

Frente al lote anterior de 38 senales, el artefacto incorpora diez senales con
valor actual:

- `ChInvIA`: 3.124 valores, reconstruida.
- `ConvDebt`: 265 valores, reconstruida.
- `DelDRC`: 1.949 valores, proxy no validado.
- `DelNetFin`: 36 valores, reconstruida.
- `DivOmit`: 14 valores, reconstruida.
- `DivSeason`: 3 valores, reconstruida.
- `EarningsConsistency`: 1.441 valores, reconstruida.
- `EarningsSurprise`: 2.132 valores, reconstruida.
- `RevenueSurprise`: 1.828 valores, reconstruida.
- `sinAlgo`: 22 valores, reconstruida.

Todas usan `sec_edgar` como fuente declarada y siguen siendo no estrictas. El
contrato preparado valida recuento, fidelidad y formula fila por fila. Este lote
de origen aun no se ha consolidado con los demas artefactos, por lo que no
cambia los recuentos globales demostrados al principio del documento.

## hire: evidencia SEC actual separada de referencias obsoletas

El artefacto `openap-93-current-recovered-results` del run `31341580689`
contiene 2.157 filas de `hire`. Solo 40 tienen valor reconstruido y
`current_usable=True`; otras 24 tienen numero pero estan declaradas
`stale_reference_only`, y las 2.093 restantes no tienen valor. Todas usan
`sec_edgar` y la formula `openap_employee_growth_sec`.

El CSV consolidado antiguo conto las 64 filas numericas. El contrato preparado
ahora exige exactamente 40 valores actuales y rechaza las 24 referencias
obsoletas. `hire` queda reconstruida, no estricta, porque el tag SEC de empleados
y la identidad CIK/ticker no prueban equivalencia con el historial Compustat y
CRSP. Hasta ejecutar otra consolidacion, el recuento global publicado no cambia.

## Tres senales IPO: lote gratuito ejecutado, pendiente de consolidar

`AgeIPO`, `IndIPO` y `RDIPO` no necesitan Twelve Data. El Excel oficial
Field-Ritter `IPO-age.xlsx` respondio HTTP 200 el 2026-08-10, pesa 1.346.041
bytes, fue modificado el 2026-01-19 y contiene 16.030 registros con fecha de
oferta, nombre, ticker, CUSIP, PERMNO y ano de fundacion. El documento oficial
indica que cubre 1975-2025, incluye direct listings, excluye cotizaciones por
fusion con SPAC y solicita citar el dataset.

La implementacion ejecutada:

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

El run `31395454942` termino correctamente y publico el artefacto
`openap-149-field-ritter-ipo-current`. El lote conserva 13.149 filas actuales:
701 valores finitos de `IndIPO`, 700 de `RDIPO` y ninguno de `AgeIPO`.
`AgeIPO` queda con datos de la ruta adquiridos pero bloqueado por cobertura;
no se convierte en senal calculada. La cobertura 2026 y las nuevas
cotizaciones por SPAC siguen necesitando una ruta SEC primaria. El puente
actual tampoco prueba un intervalo historico CRSP-CIK. Por ello los valores
son `reconstructed_not_strict`. Como el lote aun no se ha consolidado, los
recuentos globales demostrados permanecen `56/50/18/99/96814`.

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

### Alternativas gratuitas de OHLCV reauditadas

La comprobacion oficial del 2026-08-10 confirma que el bloqueo es de cuenta y
capacidad gratuita, no de inexistencia de datos:

- [Tiingo](https://www.tiingo.com/about/pricing) ofrece en el plan gratuito
  historico EOD de mas de 30 anos, precios brutos y ajustados, 1.000 peticiones
  diarias y uso interno. Sin embargo, limita la API a 500 simbolos unicos al
  mes. Cubrir las 2.157 empresas exigiria al menos cinco meses y tambien un
  token gratuito; queda como respaldo lento, no como sustituto operativo de
  Twelve Data.
- [Finnhub](https://finnhub.io/pricing) permite 60 llamadas por minuto en el
  plan gratuito, pero su tabla oficial no incluye OHLC historico; el historico
  diario aparece en planes de mercado de pago.
- [EODHD](https://eodhd.com/financial-apis/api-for-historical-data-and-volumes)
  limita el plan gratuito a 20 llamadas diarias y al ultimo ano, insuficiente
  para la ventana oficial maxima de 180 meses.
- [Marketstack](https://marketstack.com/pricing/) limita el plan gratuito a
  100 llamadas mensuales y un ano de historia, tambien insuficiente.

La mejor ruta gratuita operativa sigue siendo Twelve Data Basic: cubre el
historico requerido en unos seis cupos diarios y no obliga a esperar varios
meses. Requiere que el usuario cree la cuenta gratuita y anada el secreto
`TWELVE_DATA_API_KEY`; no se usara ninguna clave publica o ajena.

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

Sobre esa evidencia se ejecuto el calculo causal de `ExchSwitch`. Replica
la condicion OpenAP de bolsa actual NYSE/AMEX frente a los 12 meses anteriores,
pero falla cerrado: un 1 exige una transicion entre dos filings de la misma
clase con un hueco maximo de 160 dias; un 0 para NYSE o NYSE American exige
cobertura SEC de los 13 inicios de mes. El workflow manual
`openap-149-sec-exchange-switch.yml` descarga solo los cinco periodos Notes
necesarios, comprueba la formula oficial por SHA-256 y publica solo derivados y
manifiestos. El run `31389285731` termino correctamente y publico el artefacto
`openap-149-sec-exchange-switch-current`: 7.659 filas totales y 2.869 valores
finitos. La aceptacion SEC no es la fecha efectiva CRSP y el puente CIK no es
PERMNO; la salida sigue siendo reconstruida no estricta. El lote aun no se ha
consolidado y no cambia los recuentos globales demostrados.

## Spinoff: prueba SEC positiva ejecutada, pendiente de consolidar

La formula OpenAP usa la clasificacion `SpinoffCo` de CRSP y la mantiene durante
los primeros 24 meses de `FirmAgeNoScreen`. La ruta gratuita preparada no
rellena ceros por ausencia. Selecciona CIK actuales con un Form 10-12B/10-12G
causal, descarga de SEC como maximo 24 documentos por titulo y exige una frase
de finalizacion junto a una fecha efectiva. Operaciones propuestas, previstas o
sujetas a condiciones se rechazan.

El calculo emite 1 durante los 24 meses siguientes a la fecha probada
y 0 despues; los demas titulos quedaran sin valor. La fecha de escision SEC es
un proxy de edad y no equivale a la primera observacion CRSP/PERMNO, por lo que
todo resultado es `reconstructed_not_strict`. El workflow manual
`openap-149-sec-spinoff.yml` fija el hash de la formula, usa identidad SEC
actual, respeta fair access, no conserva documentos brutos y no tiene `push`.
El run `31393646423` termino correctamente: proceso 264 filings por el
readthrough auditado, encontro 23 filas de evidencia de finalizacion y genero
8 valores finitos. Publico el artefacto `openap-149-sec-spinoff-current`.
El lote aun no se ha consolidado y no cambia los recuentos actuales.

## Dividendos: la antigua ruta Basic no es valida

La documentacion actual de Twelve Data reserva `/dividends` a Grow/Venture o
superior. Alpha Vantage documenta `DIVIDENDS` con clave gratuita, pero sus
terminos clasifican la investigacion y el testing fuera del uso personal como
uso comercial; no es una fuente autorizada para Aurora. SEC sigue siendo una
fuente publica para evidencia positiva, pero no aporta directamente los codigos
CRSP `cd1/cd2/cd3`, un calendario `exdt` completo ni la ausencia mensual
necesaria para reproducir exactamente `DivInit`, `DivOmit` y `DivSeason`.

El calculador de `DivInit` se ejecuto en el run CompanyFacts `31392473937`, pero
genero exactamente 0 valores. Retiene 48 contextos de dividendos por accion
ordinaria y exige nueve trimestres contiguos: los ocho anteriores deben declarar
cero y el actual un importe positivo. Prioriza el tag de efectivo pagado y usa
el declarado solo como respaldo. Nunca convierte un fact ausente en cero. Como
falta `exdt`, solo emite 1 si la formacion cae dentro de la ventana oficial de
seis meses incluso suponiendo que el evento ocurrio el primer dia del trimestre;
no emite ceros. La evidencia positiva y la cobertura siguen siendo insuficientes;
no se marca como dato adquirido ni como senal calculada.

El run CompanyFacts `31392473937` genero 14 valores de `DivOmit`: exige seis
trimestres consecutivos con dividendo explicito y un septimo con cero explicito,
y mantiene 1 durante el mes de disponibilidad SEC y el siguiente. No inventa
ausencias ni emite ceros. La ventana empieza en el filing y no en `exdt`, por
lo que la salida queda como reconstruccion no estricta.

El mismo run genero 3 valores de `DivSeason` a partir de facts SEC directos de
uno a 45 dias. Exige varios eventos con separaciones regulares, infiere una
frecuencia trimestral, semestral o anual y aplica los lags oficiales. Solo emite
el 1 previsto; nunca un 0. El cierre SEC no es `exdt` y la frecuencia inferida
no es el codigo CRSP `cd3`, de modo que sigue siendo reconstruccion no estricta.

## Cuatro senales contables sin dependencia de precio

`DelDRC`, `ConvDebt`, `OrderBacklog` y `OrderBacklogChg` se han separado de
Twelve Data: sus formulas solo necesitan datos contables SEC e identidad. El
lote CompanyFacts produjo 1.949 valores de `DelDRC` como proxy no validado y
265 valores reconstruidos de `ConvDebt`. `OrderBacklog` y `OrderBacklogChg`
siguen dependiendo del ingreso causal de etiquetas personalizadas de Notes.

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
- `DelDRC` ya tiene calculador ejecutado sobre etiquetas estandar CompanyFacts.
  Su equivalencia contable no esta validada y por eso no supera la clase
  `unvalidated_proxy`; las formulas de backlog siguen pendientes de Notes.
- El cero de etiquetas `ConvDebt` del run diagnostico `31342908279` no era una
  prueba de ausencia global: los shards fuente solo conservaban la lista
  cerrada de alias contables y excluian los conceptos de deuda convertible.
  La retencion acotada y el calculador positivo fail-closed se ejecutaron en
  `31392473937` y generaron 265 valores. Solo emite `1` ante evidencia causal
  del ultimo periodo anual; nunca convierte ausencia, una etiqueta amplia o un
  hecho antiguo en `0`. Sigue siendo reconstruccion no estricta hasta validar
  la equivalencia de `dc`/`cshrc` y ampliar cobertura.

## DelNetFin: dos periodos anuales SEC ejecutados

La formula fijada de `DelNetFin` calcula el cambio a doce meses de inversiones
corrientes y de largo plazo menos deuda corriente, deuda de largo plazo y
acciones preferentes, dividido por activos medios. La preparacion oficial
aplica seis meses de retraso al cierre anual y convierte la accion preferente
faltante en cero.

La ruta ejecutada exige dos cortes SEC anuales alineados para
`Assets`, `ShortTermInvestments`/`MarketableSecuritiesCurrent`,
`LongTermInvestments`/`OtherInvestments`, `LongTermDebtNoncurrent` y
`LongTermDebtCurrent`. No acepta `LongTermDebt` total ni
`ShortTermBorrowings` como sustitutos que puedan duplicar u omitir deuda. Usa
una sola etiqueta por componente, reproduce el calendario de seis meses y
falla cerrado ante cualquier hueco, conflicto o desalineacion. La accion
preferente sigue la regla de cero de la formula oficial.

El run `31392473937` genero 36 valores. La salida es
`reconstructed_not_strict`: los agregados XBRL no prueban
equivalencia con `ivst/ivao/dltt/dlc/pstk`, la vintage SEC actual puede contener
restatements y CIK/ticker no es GVKEY/PERMNO historico. Las antiguas filas
inutilizables quedan sustituidas en el lote de origen, pendiente de consolidar.

## EarningsConsistency: formula anual SEC ejecutada

La formula fijada de `EarningsConsistency` usa `epspx` anual, no EPS
trimestral. La preparacion oficial de OpenAP aplica un retraso de seis meses al
cierre fiscal, replica cada observacion durante doce meses, calcula cinco
crecimientos interanuales separados por doce meses y aplica filtros de magnitud
y consistencia de signo.

Se ha ejecutado una ruta gratuita con
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
por accion. El run nuevo `31392473937` declaro el contrato versionado en los 48
manifiestos y genero 1.441 valores de `EarningsConsistency`.

La salida es `reconstructed_not_strict`: el EPS basico SEC no prueba
equivalencia con `epspx` Compustat y la identidad CIK/ticker actual no sustituye
GVKEY/PERMNO historico. Los 13 valores inutilizables del artefacto anterior no
se aceptan; el nuevo lote de origen permanece pendiente de consolidar.

## Dos sorpresas trimestrales SEC: historia completa ejecutada

El lote anterior no genero valores de `EarningsSurprise` ni `RevenueSurprise`
por historia trimestral normalizada insuficiente. La formula actual necesita 21
trimestres contiguos para formar la sorpresa corriente, la deriva de ocho
cambios interanuales y la desviacion tipica de ocho sorpresas anteriores.

La adquisicion nueva conserva hasta 48 contextos de ingresos, ventas y acciones
medias basicas por etiqueta en los shards CompanyFacts y reconstruye cada
trimestre desde hechos acumulados SEC.
Los flujos se obtienen por diferencia y las acciones medias se separan usando
los dias de cada tramo. Se rechazan huecos, unidades incorrectas, etiquetas
mezcladas, conflictos y hechos disponibles despues de la formacion. El runner
SEC existente queda conectado a ambos calculos y a pruebas sinteticas de los 21
trimestres. El run `31392473937` genero 2.132 valores de `EarningsSurprise` y
1.828 de `RevenueSurprise`.

Aunque produjo valores, la salida sigue siendo `reconstructed_not_strict`:
ingreso SEC por acciones medias no demuestra equivalencia con `epspxq`, ventas
SEC por acciones no son por si solas `revtq/cshprq` Compustat y la identidad
CIK/ticker actual no es un intervalo GVKEY/PERMNO. Ambos resultados son
reconstruidos no estrictos y siguen pendientes de consolidar.

## sinAlgo: SIC positivo SEC ejecutado

`sinAlgo` tampoco carece por completo de fuente gratuita. La formula fijada
clasifica directamente cerveza con SIC `2080-2085` y tabaco con SIC
`2100-2199`. El calculador toma el SIC del ultimo filing SEC disponible antes de
la formacion y solo emite 1 para esos rangos. Un conflicto en el ultimo
timestamp queda sin valor. El run `31392473937` genero 22 valores.

No emite 0 ni clasifica gaming: la SEC submissions no aporta por si sola los
NAICS y segmentos completos, el backfill historico, los codigos de accion CRSP
ni el grupo comparable. Los valores son `reconstructed_not_strict`; el lote de
origen aun no se ha consolidado.

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
- El run manual `31384007094` termino correctamente y publico el artefacto
  `openap-149-finra-short-interest-current`: 2.988 valores de `ShortInterest` y
  1 valor reconstruido de `IO_ShortInterest`.

Por ello se elimina Twelve Data de esta ruta. El calculador y su conexion con
el runner FINRA ya se ejecutaron:

- Calcula el percentil 99 sobre todo el universo FINRA/SEC antes de aplicar la
  cobertura 13F/OpenFIGI.
- Solo usa el ultimo trimestre 13F cuyo plazo legal de 45 dias ya ha terminado.
- Rechaza mapeos OpenFIGI ambiguos y cualquier union basada solo en ticker. El
  CUSIP debe resolver a un unico `shareClassFIGI` de accion ordinaria con
  `exchCode=US`, y el nombre del emisor 13F debe coincidir, de forma
  conservadora, con el nombre SEC del CIK. Tambien rechaza denominadores
  futuros y ausencias de propiedad institucional no demostrables; no inventa
  ceros.
- La ejecucion recupero por rangos HTTP unicamente los tres parquets
  institucionales del artefacto `31333714423`, comprobo sus hashes y mantuvo
  un limite fail-closed de 128 MiB comprimidos. El directorio central remoto
  declara 85.159.102 bytes para esos tres miembros y el manifiesto, frente a
  2.741.147.673 bytes del ZIP completo; no descarga el ZIP completo.
- Etiqueta el resultado como `reconstructed`, nunca estricto,
  porque SEC 13F/OpenFIGI/SEC shares no equivalen al panel Thomson/CRSP.

El manifiesto declara coste cero, 6.975.953 posiciones 13F, 4.182.960 posiciones
enlazadas, 29.103 correspondencias OpenFIGI y una union que prohibe ticker-only.
El unico valor de `IO_ShortInterest` tiene `available_at=2026-07-24`, ocho
observaciones y la formula
`openap_io_shortinterest_finra_sec13f_current_reconstruction`. La cobertura es
demasiado baja y la fidelidad Thomson/CRSP no esta demostrada: sigue sin ser
estricta. El lote de origen no se ha consolidado, por lo que tampoco cambia los
recuentos globales demostrados.
