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

### Auditoria de los tres consolidados antiguos

Se revisaron completos los artefactos locales de los runs `31341667121`,
`31351139546` y `31353944479`. Contienen respectivamente 95.383, 95.390 y
99.824 filas, y 51, 52 y 53 senales con valor. El segundo solo anadio las siete
filas de `realestate`; el tercero anadio `FirmAge` y no descubre otra senal
oculta que pueda recuperarse.

La diferencia exacta entre las 99.824 filas del ultimo consolidado antiguo y
las 96.814 filas fail-closed demostradas despues es de 3.010 filas. Se
reconcilia por completo contra la declaracion `current_usable` del artefacto de
origen:

- 2.585 filas pertenecian a tres senales cuya evidencia completa era no
  utilizable: `CBOperProf` (415), `DelNetFin` (2.157) y
  `EarningsConsistency` (13).
- 425 filas eran observaciones no actuales dentro de seis senales que si
  conservan otras filas utilizables: `BrandInvest` (9), `GrLTNOA` (75),
  `HerfBE` (63), `hire` (24), `NumEarnIncrease` (4) y `Tax` (250).

Los dos subtotales suman 3.010 y explican exactamente
`99.824 - 3.010 = 96.814`. Por tanto, los consolidados antiguos no aportan una
senal adicional valida. `DelNetFin` y `EarningsConsistency` tienen ya
sustituciones ejecutadas de 36 y 1.441 valores en CompanyFacts `31392473937`,
pendientes de una consolidacion autorizada; `CBOperProf` sigue en cuarentena.
Esta comprobacion fue solo de lectura sobre artefactos existentes: no ejecuto
tests, calculos de senales, descargas ni workflows y no cambia los recuentos
publicados ni el score estricto de 31.

### Auditoria de cinco salidas finitas rechazadas de OpenAP93

Tambien se compararon con el codigo oficial cinco senales del artefacto
`31341580689` que conservaban numeros finitos pero
`current_usable=False`. Ninguna puede recuperarse sin corregir primero su
entrada o su formula:

- `DivSeason` contiene 1.191 valores, 586 ceros y 605 unos. El calculador
  aplica siempre los retardos trimestrales 2/5/8/11 y no usa `cd3`; la formula
  oficial distingue frecuencia trimestral o desconocida, semestral y anual,
  ademas de filtrar dividendos ordinarios por `cd1=1` y `cd2=2`. Puede marcar
  meses incorrectos para pagadores semestrales o anuales. Los 1.191 valores se
  rechazan; solo permanecen los tres positivos SEC ejecutados, no estrictos y
  sin clase cero.
- `AnnouncementReturn` contiene 561 valores calculados alrededor de la fecha
  del 10-Q/10-K. La formula oficial usa `rdq`, la fecha de anuncio de
  resultados, y suma retornos anormales entre las sesiones -2 y +1. Un filing
  periodico puede publicarse dias o semanas despues del anuncio; esos 561
  numeros miden otro evento. La ruta gratuita pendiente debe identificar el
  anuncio, por ejemplo mediante un 8-K Item 2.02 causal, antes de calcular la
  ventana.
- `FirmAgeMom` contiene 373 valores. La formula oficial ordena la edad desde la
  primera aparicion de cada accion; el run solo adquirio 84 meses desde
  2019-08-09 y usa `first_clean_price_date`. Ese borde de descarga no permite
  ordenar la edad real de las empresas antiguas. Se necesita una primera fecha
  de cotizacion verificada, no el inicio del shard recuperado.
- `IndRetBig` contiene 1.432 valores agrupados por la etiqueta industrial
  actual de Yahoo. La formula oficial exige SIC CRSP transformado a FF48,
  ranking de capitalizacion dentro de industria y la rentabilidad media del
  30 % mayor, excluyendo despues las propias empresas grandes. La etiqueta
  Yahoo no es ese grupo y los valores se rechazan.
- `MS` contiene cuatro valores de una aproximacion SEC anual. La formula
  oficial de Mohanram combina entradas trimestrales, ventanas de 12 y 48
  meses, filtro previo del quintil bajo de book-to-market y medianas SIC2. La
  estabilidad anual usada por el proxy no reproduce esas ventanas.

Esta auditoria descarta `1.191 + 561 + 373 + 1.432 + 4 = 3.561` numeros que no
representan la formula declarada. No elimina las rutas gratuitas: fija el dato
o calculador que falta para poder reintentarlas. No cambia los recuentos
publicados porque ninguna de esas filas estaba marcada como utilizable.

## Seis lotes de origen: verificacion hash-bound preparada, no ejecutada

El consolidador anterior leia directamente los CSV de CompanyFacts, FINRA,
realestate, ExchSwitch, Field-Ritter y Spinoff. Esa lectura comprobaba despues
las filas de forma agregada, pero no ligaba cada lote a su run, hash y
manifiesto antes de aceptarlo.

Se ha preparado un cargador fail-closed para cada uno de los seis artefactos
ya existentes. Los contratos fijan los runs `31392473937`, `31384007094`,
`31384049772`, `31389285731`, `31395454942` y `31393646423`, junto con el
SHA-256 exacto de cada CSV. Tambien comprueban, segun el esquema disponible:

- manifiesto y hash de salida;
- inventario de formulas fijado;
- senales y recuentos exactos;
- fuente, formula y hash de formula por senal;
- identidad no vacia y ausencia de duplicados;
- fechas causales y ausencia de lookahead;
- coherencia entre valor finito y `current_usable`;
- `strict_score_eligible=false`, score estricto cero y niveles protegidos
  cerrados.

Los tres artefactos antiguos que no incluian todas las columnas de puerta solo
pueden normalizarlas porque su hash exacto y su manifiesto declaran el lote
completo como no estricto. Los manifiestos pasan a formar parte del hash
agregado y de `verified_current_batches` en la salida de consolidacion.

Las pruebas negativas se escribieron antes del codigo y cubren alteracion del
CSV, run incorrecto, duplicados, lookahead, valor incoherente, fuente o formula
distinta, inventario de formulas cambiado e intento de activar strict. No se
han ejecutado localmente ni en GitHub porque la instruccion vigente prohibe
arrancar runs y no existe autorizacion posterior para ejecutar localmente.
Por tanto, esta mejora no cambia todavia los recuentos publicados
`56/50/18/99/96814`, la matriz CSV ni el score estricto confirmado de 31.

### Union prospectiva de artefactos ya ejecutados

Sin ejecutar calculadores ni volver a descargar datos, se hizo la union por
nombre de senal de los seis CSV de origen fijados por los contratos anteriores.
Los artefactos contienen al menos una fila finita declarada
`current_usable=True` para 55 senales. Su union con las 50 senales canonicas
fail-closed aporta 15 senales nuevas y deja un total prospectivo de 65:

`ChInvIA`, `ConvDebt`, `DelDRC`, `DelNetFin`, `DivOmit`, `DivSeason`,
`EarningsConsistency`, `EarningsSurprise`, `ExchSwitch`, `IndIPO`,
`IO_ShortInterest`, `RDIPO`, `RevenueSurprise`, `sinAlgo` y `Spinoff`.

Las 17 rutas estrechas OpenAP93 descritas a continuacion anaden 16 nombres
unicos sobre esas 65; `DivOmit` ya estaba presente. Los 16 adicionales son:

`BetaTailRisk`, `betaVIX`, `CompEquIss`, `CoskewACX`, `Coskewness`, `DivInit`,
`DivYieldST`, `EquityDuration`, `MomRev`, `MomVol`, `OScore`, `PriceDelayRsq`,
`ResidualMomentum`, `RIO_MB`, `RIO_Turnover` y `RIO_Volatility`.

Por tanto, hay evidencia fuente ya adquirida para un total prospectivo de 81
senales con algun valor actual. No es todavia el recuento publicado: la union
solo prueba disponibilidad en artefactos, no que el consolidador y sus pruebas
hayan aceptado cada fila. Algunas rutas son positivas y parciales, y todas las
nuevas siguen siendo no estrictas. Los recuentos canonicos permanecen en
`56/50/18/99/96814` y el score estricto confirmado permanece en 31 hasta una
consolidacion autorizada y verificada.

### Resto exacto despues de las rutas preparadas

La union anterior distingue evidencia adquirida de implementacion preparada.
Si se incorporan, sin darlas por ejecutadas, las 17 salidas del recuperador de
ratios contables, el conjunto cubierto por una ruta concreta sube de 81 a 98.
Al anadir los 25 calculadores de mercado cuya formula permanece preparada y
descontar siete solapes con OpenAP93, sube a 116.

Quedan exactamente 33 senales fuera de esas rutas adquiridas o preparadas:

`Activism1`, `Activism2`, `AgeIPO`, `AnnouncementReturn`, `BetaLiquidityPS`,
`BPEBM`, `CBOperProf`, `CitationsRD`, `CustomerMomentum`, `EarnSupBig`, `EBM`,
`FirmAgeMom`, `FR`, `Frontier`, `IndRetBig`, `IntanBM`, `IntanCFP`, `IntanEP`,
`IntanSP`, `iomom_cust`, `iomom_supp`, `Mom6mJunk`, `MS`, `OrderBacklog`,
`OrderBacklogChg`, `OrgCap`, `PatentsRD`, `RDS`, `retConglomerate`, `VarCF`,
`zerotrade12M`, `zerotrade1M` y `zerotrade6M`.

Los numeros 98 y 116 son cobertura de implementacion prospectiva, no valores
calculados ni senales aceptadas. El siguiente trabajo de adquisicion debe
centrarse en esas 33 y, en paralelo, verificar la consolidacion de las rutas ya
preparadas cuando vuelva a estar autorizada una ejecucion.

Dos auditorias del resto fijan el siguiente trabajo concreto:

- `Frontier` tiene ocho valores reconstruidos con la regresion oficial de 60
  meses y precio del mes corriente, pero el codigo del SHA fuente publica como
  `available_at` solo la fecha del filing anual e ignora `price_date`, aunque ya
  calcula el maximo de ambas dependencias en `current_available`. Por eso las
  ocho filas aparecen artificialmente con 160 a 261 dias de antiguedad. La
  correccion debe probar que disponibilidad y `period_end` reflejan la
  dependencia de mercado actual antes de intentar recuperar la senal.
- `OrgCap` no se arregla cambiando una fecha. Sus 689 numeros usan todos los
  cierres fiscales y ajustan por SIC2; la formula oficial conserva diciembre y
  estandariza por FF17 despues de winsorizar. Esas filas siguen rechazadas
  hasta corregir ambas diferencias y obtener historia SG&A contigua.
- `AnnouncementReturn` tiene una ruta gratuita primaria mas concreta que el
  bloqueo generico anterior. SEC Submissions ya aporta accesion, formulario,
  fecha de filing, aceptacion y documento, pero `_submission_rows` descarta el
  vector `items` y el parquet no conserva Item 2.02. El Form 8-K oficial exige
  que Item 2.02 declare la fecha del anuncio o release de resultados. La
  correccion debe retener `items`, seleccionar 8-K/8-K/A con Item 2.02, extraer
  fail-closed la fecha real del anuncio y fijar `available_at` como el maximo
  entre la publicacion causal, la aceptacion SEC y la sesion +1 que cierra la
  ventana oficial -2/-1/0/+1. Los 561 numeros construidos con la fecha del
  10-Q/10-K siguen rechazados.
- `VarCF` tampoco carece de entradas gratuitas. La formula oficial es la
  varianza movil de 60 meses de `(ib+dp)/mve_permco`, con un minimo de 24
  observaciones. El recolector ya retiene `NetIncomeLoss`/`ProfitLoss`,
  `DepreciationDepletionAndAmortization`/`Depreciation` y ocho observaciones
  anuales; los artefactos de precio recuperados cubren la ventana. El hueco es
  el denominador historico: el panel de mercado preparado repite las acciones
  actuales hacia atras y deriva con ellas la capitalizacion mensual. Antes de
  calcular `VarCF` hay que resolver acciones SEC disponibles en cada mes,
  agregar causalmente todas las clases del mismo CIK y fallar cerrado ante
  intervalos de identidad ambiguos. La ruta resultante sera reconstruida y no
  estricta, no CRSP/Compustat exacta.
- `EBM` y `BPEBM` comparten una ruta SEC concreta. Caja, deuda corriente y no
  corriente, deferred charges, patrimonio y preferred stock ya estan en los
  alias o en la retencion preparada. La taxonomia publica incluye ademas
  `PreferredStockAmountOfPreferredDividendsInArrears` para `dvpa` y
  `TreasuryStockPreferredValue` para `tstkp`. El artefacto OpenAP93 emitio cero
  valores porque esas dos etiquetas no se retienen, no porque EDGAR carezca de
  ellas. La futura reconstruccion debe exigir los siete componentes del mismo
  periodo causal y capitalizacion de emisor; una etiqueta ausente no equivale
  a cero. La cobertura puede ser reducida porque ambos desgloses son poco
  frecuentes, pero debe medirse antes de volver a bloquear las dos senales.
- `IntanBM`, `IntanCFP`, `IntanEP` e `IntanSP` ya tienen formula implementada y
  84 meses de precio en el artefacto OpenAP93, pero las 8.628 filas quedaron
  sin valor por `missing_causal_multiyear_inputs`. El panel pivota las acciones
  SEC junto al resto de la contabilidad por `period_end`; la fecha de contexto
  de `EntityCommonStockSharesOutstanding` suele ser la fecha de portada y no el
  cierre fiscal, por lo que desaparece de la fila anual. La reparacion debe
  resolver las acciones independientemente por `available_at`, construir la
  capitalizacion mensual del emisor por clases y solo despues aplicar el lag
  exacto de 60 meses y las cuatro regresiones transversales. No hace falta una
  fuente de pago, pero las salidas seguiran siendo reconstruidas/no estrictas.
- `FR` tiene una ruta gratuita en las notas XBRL de pensiones. Para el ano
  actual la formula oficial ya no usa los regimenes historicos de 1980-1997:
  exige exclusivamente `(pplao-pbpro)/mve_permco`, es decir, activos y PBO de
  los planes de pensiones en superavit. EDGAR publica tanto los totales
  estandar `DefinedBenefitPlanFairValueOfPlanAssets` y
  `DefinedBenefitPlanBenefitObligation` como tablas que separan planes en
  superavit y deficit. Estas ultimas pueden usar dimensiones o extensiones del
  emisor, por lo que el colector debe leer Financial Statement and Notes o el
  filing individual, aceptar solo una tabla que declare explicitamente
  pension y superavit, y conservar accesion, aceptacion, periodo, unidad y
  dimensiones. Los totales genericos no se sustituyen por `pplao/pbpro`. El
  codigo actual no retiene ninguna etiqueta `DefinedBenefitPlan*`; su bloqueo
  demuestra una omision del colector, no que el dato sea de pago.
- `RDS` tambien puede reconstruirse con SEC Notes y mercado. La formula
  oficial necesita cambios anuales de los ajustes acumulados de traduccion y
  valores disponibles para la venta, patrimonio, beneficio, dividendos
  comunes/preferentes, precio y acciones. EDGAR publica roll-forwards AOCI por
  componente y los conceptos `DividendsCommonStockCash` y
  `DividendsPreferredStockCash`. Hay que extraer los saldos finales actual y
  anterior mediante sus ejes/miembros, sin usar AOCI total como sustituto, y
  resolver precio y acciones en la fecha fiscal con identidad de emisor. El
  propio OpenAP convierte a cero el termino de pensiones si falta `pcupsu` o
  `paddml`, pero deja `RDS` ausente cuando no identifica ni `msa` ni `recta` en
  ambos cortes; la reconstruccion debe respetar esas dos reglas. Sigue sin ser
  Compustat exacta porque las taxonomias y la base fiscal de AOCI pueden
  diferir, pero no necesita una fuente de pago.
- `OrderBacklog` y `OrderBacklogChg` tienen datos gratuitos en filings, aunque
  no en el alias cerrado actual. El calculador solo busca
  `us-gaap:OrderBacklog` en Company Facts; esa API excluye etiquetas propias y
  por eso obtuvo cobertura cero. EDGAR contiene etiquetas de emisor como
  `tgen:Backlog` y 10-K actuales que declaran el backlog operativo con importes
  comparables de dos cierres. La ingesta debe aceptar un hecho monetario
  instantaneo o una tabla/texto solo cuando etiqueta, definicion y contexto
  demuestren pedidos/contratos operativos pendientes; debe rechazar el activo
  intangible denominado backlog. Tampoco puede sustituir automaticamente
  `RevenueRemainingPerformanceObligation`, cuya definicion ASC 606 es precio
  de transaccion no reconocido, no backlog de pedidos. Para la primera senal
  hacen falta backlog y activos actual/anterior; para el cambio hacen falta
  dos ratios causales completos, incluido el tercer corte de activos. Cada
  version debe conservar su propia accesion y `accepted`, sin retrotraer el
  comparable republicado por un filing posterior.
- `CBOperProf` no requiere una fuente nueva, sino completar la formula. Los
  415 numeros antiguos restan solo cambios de cuentas a cobrar e inventario y
  omiten prepagos, deferred revenue corriente/no corriente, cuentas a pagar y
  gastos devengados; por eso siguen en cuarentena. SEC publica conceptos
  estandar para los cinco grupos, incluidos `PrepaidExpenseCurrent`,
  `ContractWithCustomerLiabilityCurrent/Noncurrent`,
  `AccountsPayableCurrent` y `AccruedLiabilitiesCurrent`. La reparacion debe
  retener todos los campos actuales y de doce meses, aplicar exactamente el
  zero-fill de OpenAP a cada variable del numerador y despues imponer acciones
  ordinarias, capitalizacion/BM, activos y exclusion SIC 6000-6999. Los
  agregados amplios de prepagos o cuentas a pagar mas devengos son proxies y
  deben distinguirse de los conceptos separados.
- `EarnSupBig` puede derivarse del lote gratuito ya adquirido. CompanyFacts
  `31392473937` produjo 2.132 `EarningsSurprise` actuales con 21 trimestres; el
  repositorio ya dispone del mapa oficial FF48 de Kenneth French y de
  capitalizacion de emisor. El calculador anterior usa la industria Yahoo,
  que no es la formula. Hay que mapear el SIC SEC actual a FF48, calcular por
  industria-mes el percentil de capitalizacion, promediar
  `EarningsSurprise` solo en el 30 % superior y emitirlo solo para el 70 %
  restante. `available_at` debe ser el maximo de todas las empresas grandes
  que intervienen en cada media, no solo la fecha de la empresa receptora.
- `CustomerMomentum` admite una salida positiva parcial desde SEC Notes y
  filings. La formula fijada usa la media simple de retornos de clientes
  identificados, no una ponderacion por ventas como afirma el contrato local;
  hace disponible la relacion seis meses despues del cierre y la deja caducar
  aproximadamente a los doce meses. Solo deben aceptarse clientes nombrados
  que resuelvan sin ambiguedad a CIK y clase de accion. Filings que digan
  "Customer 1" o "un cliente", entidades privadas y ausencias no producen
  enlaces ni ceros. El resultado sera reconstruido y de cobertura parcial.
- `iomom_cust` y `iomom_supp` disponen gratuitamente de Supply/Make/Use y
  vintages BEA. El bloqueo real es asignar cada empresa al NAICS historico y
  despues a la industria BEA de 71 categorias: SEC ofrece SIC y las
  concordancias Census pueden ser muchos-a-muchos. El R oficial aplica cinco
  anos de retraso, excluye la propia industria y guarda el retorno industrial
  relacionado continuo. Ese R no esta fijado por hash en el contrato y declara
  un bug post-1997 para proveedores; hay que congelar y probar el
  comportamiento literal antes de calcular `iomom_supp`.
- `retConglomerate` tiene tablas SEC actuales de ingresos por segmento, pero
  no un SIC2 estandar por segmento. Solo puede reconstruirse para emisores con
  ventas reconciliadas y descripciones que permitan asignacion SIC2 univoca.
  Ademas, el contrato local exige activos y "80 % asset coverage", mientras
  que la fuente fijada no carga activos: divide ventas del segmento por ventas
  anuales y aplica alli el corte. Esa contradiccion de formula debe resolverse
  antes de escribir el calculador; no es ausencia de una fuente gratuita.
- `Mom6mJunk` tiene una ruta SEC gratuita positiva, no un panel completo. La
  formula fijada usa el rating S&P del emisor, forward-fill y la momentum
  geometrica de los retardos 1 a 5; el filtro oficial es `0 < credrat <= 14`,
  descrito en `SignalDoc.csv` como BBB o inferior. Solo se aceptan ratings
  corporativos/emisor publicados con CIK y fecha verificables. No se pueden
  usar ratings de una emision, inferir junk por ausencia de rating ni llamar
  estricta a la salida. La ruta sera reconstruida, positiva y parcial; la
  escala numerica abierta de `currentratingnum`/`credrat` sigue pendiente.
- `Activism1` y `Activism2` comparten la formula oficial: `TR_13F` para
  `maxinstown_perc`, `monthlyCRSP.shrcls` y `GovIndex.G` unido por ticker y
  mes. SEC/13F cubre la posicion institucional, pero no ofrece un panel
  completo y estandarizado de las 24 provisiones de `G` ni una historia fiable
  de clases duales. Se mantienen como reconstrucciones parciales no estrictas.
- `AgeIPO` requiere `IPOdate`, `FoundingYear`, una ventana de 3--36 meses y
  al menos 100 IPO recientes por mes. Ritter cubre fechas de fundacion hasta
  2025, pero faltan IPOs de 2026 para una formacion actual; el lote existente
  queda bloqueado por cobertura.
- `BetaLiquidityPS` requiere retornos mensuales, factores Fama--French y
  `ps_innov` en una regresion rolling de 60 meses con minimo 36. La serie
  oficial gratuita de Pastor llega a diciembre de 2025: sirve para historia,
  pero no para el valor actual de julio/agosto de 2026. Sigue bloqueada por
  actualidad, identidad y cobertura pendiente.

## Diecisiete senales OpenAP93: recuperacion selectiva preparada, no ejecutada

El artefacto gratuito y ya existente `openap-93-current-recovered-results` del
run `31341580689` contiene 2.157 filas de `CompEquIss`; 1.585 tienen valor
finito y `current_usable=True` (73,4817 %). La formula declarada es
`openap_compequiss_60m_sec_shares_yahoo_return`, con 62 a 85 observaciones para
las filas utilizables. Calcula la expresion oficial de 60 meses, pero sustituye
la capitalizacion CRSP de la empresa por precio de la accion primaria y
acciones del emisor SEC.

El consolidador queda preparado para aceptar exclusivamente este contrato. El
nuevo cargador comprueba los cuatro ficheros del artefacto, la cadena de
SHA-256, el run de origen `31333714423`, su HEAD `34464d5327598282aa2af1523422105dfd5dd184`,
el commit OpenAP fijado, las 93 senales, la cobertura, la formula, las fechas,
los duplicados y la identidad actual CIK-ticker. Despues reemplaza solo
`CompEquIss` por la fuente estrecha `recovered_openap93_compequiss`; no autoriza
`yahoo_public` de forma general ni recupera `DivYieldST`, `Frontier` o `MS`.

La salida permanece `reconstructed`, con identidad CRSP historica no verificada,
`strict_score_eligible=false` e incremento estricto cero. Se han escrito las
pruebas fail-closed antes del codigo, pero no se han ejecutado porque el usuario
ha prohibido iniciar runs. Por ello los recuentos publicados `56/50/18/99/96814`
y el score estricto confirmado de 31 no cambian todavia.

El mismo artefacto contiene 37 valores actuales de `EquityDuration` sobre 2.157
empresas (1,7153 %). La implementacion conserva las constantes oficiales de
Dechow-Sloan-Soliman/OpenAP: persistencia de ROE 0,57, coste de capital 0,12,
persistencia de crecimiento 0,24, crecimiento de largo plazo 0,06 y proyeccion
de distribuciones a diez anos. SEC sustituye `ceq`, `ib`, `sale` y `csho`, y el
precio Yahoo del cierre fiscal sustituye `prcc_f` de CRSP/Compustat.

El contrato acepta exclusivamente `openap_equity_duration_dss2004_sec_yahoo`,
la fuente estrecha `recovered_openap93_equityduration`, las fechas causales y
los 37 valores declarados por la cobertura hash-bound. Queda reconstruida, con
cobertura muy baja, identidad historica Compustat/CRSP no verificada y aptitud
estricta falsa. Tampoco cambia los recuentos publicados hasta una consolidacion
ejecutada.

`betaVIX` aporta 2.157 valores (100 % del universo) con la regresion oficial de
20 sesiones y minimo 15 observaciones: exceso de retorno sobre `mktrf` y cambio
diario de VIX, usando Kenneth French, Cboe y retornos Yahoo. El contrato exige
un minimo de 15 observaciones y el artefacto conserva 20 por valor, la formula
`openap_beta_vix_20d_min15_market_control` y la fuente estrecha
`recovered_openap93_betavix`. Yahoo sustituye CRSP y la identidad historica no
esta verificada, por lo que sigue siendo reconstruida no estricta.

El mismo lote prepara tres interacciones RIO reconstruidas: `RIO_MB` con 305
valores, `RIO_Turnover` con 231 y `RIO_Volatility` con 158. Conservan SEC 13F,
OpenFIGI, el residual de propiedad institucional, el retardo de seis meses, el
filtro de tamano NYSE/AMEX y los quintiles 1-5. Sustituyen Thomson/CRSP/Compustat
por SEC y Yahoo, y usan la fuente estrecha `recovered_openap93_rio`. El cargador
reconcilia por separado universo, aplicables, no aplicables, faltantes y
cobertura, y rechaza valores que no sean quintiles enteros entre 1 y 5.

`RIO_Disp` no se recupera: el propio artefacto la clasifica
`unvalidated_proxy`, `current_usable=false`, porque el rango alto-bajo de
previsiones Yahoo no equivale a la desviacion estandar IBES oficial. Ninguna de
estas cuatro senales incrementa el score estricto ni modifica todavia los
recuentos publicados.

La septima senal es `OScore`, con 1.100 valores SEC+FRED actuales y binarios.
La fuente estrecha `recovered_openap93_oscore` sustituye solo esas filas tras
validar hash, formula, cuatro entradas, cobertura y fechas. Tampoco incrementa
el score estricto.

El mismo artefacto aporta cuatro senales de mercado reconstruidas con retornos
Yahoo y factores publicos de Kenneth French: `PriceDelayRsq` (2157),
`CoskewACX` (2157), `Coskewness` (2157) y `ResidualMomentum` (2144). Cada una
tiene una fuente estrecha propia, formula y script OpenAP fijados, observaciones
minimas, cobertura reconciliada, fechas causales e identidad CIK+ticker. Son
8.615 valores actuales adicionales, pero siguen fuera del score estricto por
la sustitucion de CRSP, la identidad historica y la revision de terminos de
Yahoo pendientes.

Otras cuatro salidas Yahoo del artefacto pasan por contratos separados:
`BetaTailRisk` (1989), `DivYieldST` (1191), `MomVol` (719) y `MomRev` (232).
El cargador exige respectivamente 72, 12, 6 y 37 observaciones minimas;
tambien restringe `DivYieldST` a categorias 0-3, `MomVol` a deciles 1-10 y
`MomRev` a valores binarios. `DivYieldST` conserva expresamente que infiere la
frecuencia de pagos a partir de ex-dates Yahoo, en lugar de usar el codigo de
frecuencia CRSP. Las cuatro siguen reconstruidas y no estrictas.

`DivInit` y `DivOmit` aportan 2.157 clasificaciones binarias cada una. El
contrato exige al menos 24 meses, las ventanas oficiales de iniciacion u
omision, formula, script, fechas, cobertura y caveat exactos. La consolidacion
debe priorizar estas filas Yahoo sobre el lote SEC positivo: CompanyFacts no
emitio iniciaciones y solo emitio 14 omisiones positivas, sin clases negativas.
Yahoo permite la clasificacion completa, pero no expone los codigos de
distribucion CRSP; ambas siguen reconstruidas y no estrictas.

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
Las 14 filas positivas de `DivOmit` conservan su evidencia de origen, pero la
salida final debe ser sustituida por las 2.157 clasificaciones Yahoo del lote
OpenAP93, que tambien conserva explicitamente las clases negativas.

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
- El cargador estrecho `recovered_openap93_oscore` valida el artefacto y los
  manifiestos por hash, las 2157 identidades, las fechas, la cobertura 1100 de
  2157, cuatro observaciones por valor y que la salida sea binaria. Solo las
  1100 filas utilizables sustituyen el lote general.
- Clasificacion: reconstruida, no estricta. No se incorpora al score estricto.
- El cargador de las diecisiete senales prepara 22.633 filas actuales, pero no se
  suman manualmente a los recuentos globales: la siguiente consolidacion debe
  resolver tambien los demas lotes pendientes, sustituciones y cuarentenas.
  Hasta entonces prevalecen `56/50/18/99/96814` y el score estricto 31.

## OrgCap: fuente gratuita confirmada, pero valores actuales no disponibles

- La formula oficial usa SG&A real, depreciacion anual del 15 %, escala por
  activos, winsorizacion transversal y ajuste por industria FF17.
- El artefacto existente contiene 689 numeros con SEC CompanyFacts y `GNPDEF`
  de FRED, pero todos son `stale_reference_only`; las 2157 filas declaran
  `current_usable=False`. No es correcto afirmar que una reconsolidacion los
  admitira como valores actuales.
- La ruta autoriza `fred_public_csv` y no exige Twelve Data, pero sigue faltando
  historia SG&A causal, contigua y suficientemente larga. Los recuentos
  demostrados no cambian.
- La reconstruccion existente sigue siendo no estricta: usa SIC SEC actual a
  dos digitos, no SIC historico CRSP/FF17, y aun debe demostrar continuidad de
  historia, cobertura e identidad antes de una validacion de solapamiento.

## Diecisiete ratios contables recuperables de un artefacto auditado

El run correcto `31270341796` produjo una cuadricula
`openap_features_current.parquet` de 185 senales, su `coverage_185.csv`, los
conceptos SEC elegidos en `sec_concept_inputs_current.parquet` y un
`output_manifest.csv` con tamano y SHA-256 de cada salida. Se ha preparado una
recuperacion selectiva de esos miembros para `AM`, `BM`, `CashProd`, `CF`,
`cfp`, `EP`, `Leverage`, `NetDebtPrice`, `NetPayoutYield`, `PayoutYield`, `RD`,
`SP`, `AdExp`, `AccrualsBM`, `BMdec`, `EntMult` y `PS`.

La recuperacion no confia solo en que exista un numero. Antes de admitir una
fila obliga a reconciliar las 185 senales por cada titulo elegible, los 185
registros de cobertura y los conceptos SEC exactos usados por cada formula.
Tambien exige una identidad `security_id + CIK + ticker`, el filtro oficial,
una fecha SEC causal y la fecha real del snapshot Yahoo que aporto la
capitalizacion de mercado. La disponibilidad final es el maximo de ambas. Una
fecha ausente, posterior a la formacion o incoherente deja la observacion sin
valor y registra el motivo. Para `AccrualsBM` y `PS` se comprueban ademas todos
los retardos anuales declarados: cada lag debe tener un unico cierre fiscal y
los cierres consecutivos deben estar separados entre 330 y 400 dias.

La fecha de formacion permanece siendo el `as_of` original del run; ni la
recuperacion ni una ejecucion posterior pueden rejuvenecerla. Quince salidas
seran `reconstructed`; `AccrualsBM` y `BMdec` conservaran
`unvalidated_proxy`. Ninguna sera estricta: usan conceptos SEC y capitalizacion
actual de Yahoo, no Compustat/CRSP, ni intervalos historicos GVKEY/PERMNO, ni
todos los lags y filtros de cartera oficiales. El workflow manual existente
queda preparado para publicar un artefacto derivado separado, sin llamadas
nuevas a Yahoo y con incremento estricto cero.

Estado exacto: `prepared_unexecuted`. No se ha iniciado ningun run, no hay
valores nuevos recuperados y los recuentos ejecutados siguen siendo
`56/50/18/99/96814`. Esta preparacion tampoco modifica las 31 senales del score
estricto confirmado.

El consolidador queda preparado para descargar este lote y el lote de mercado
desde un mismo run manual futuro. Antes de sustituir una senal exige el SHA-256
exacto del CSV, la version completa del contrato, el mismo SHA de implementacion
de 40 caracteres y todas las puertas no estrictas cerradas. El CSV recuperado
debe contener solo filas actuales utilizables, sin claves duplicadas y con
`strict_score_eligible=false`. El manifiesto y el CSV entran tambien en el hash
conjunto y en la lista de fuentes del artefacto consolidado.

## Mercado sin credencial: artefactos existentes recuperables

Las 31 rutas de mercado ya no dependen de obtener una clave nueva. El run
`31256096194` completo correctamente sus 48 jobs `yfinance (0)..(47)` y
conserva 48 artefactos `openap-yfinance-*`. El run auditado `31270341796`
reutilizo exactamente ese origen y publico el manifiesto de 48 hashes junto
con `security_master.parquet`. La ruta nueva recupera por rangos solo cada
`prices_NNN.parquet`, comprueba el SHA-256 contra ese manifiesto, pone en
cuarentena las filas OHLCV invalidas y nunca llama de nuevo a Yahoo.

El workflow manual
`.github/workflows/openap-149-recovered-yfinance-market.yml` estaba preparado
para calcular 31 salidas no estrictas: 12 directas, 11 con factores Kenneth
French y 8 adicionales (`BetaLiquidityPS`, `FirmAgeMom`, `IndMom`, `IndRetBig`,
`Size`, `TrendFactor`, `VolMkt` y `std_turn`). Una auditoria posterior de la
formula redujo el bloque realmente preparado a 25. Las tres variantes
`zerotrade` no implementan todavia la formula mensual fijada; `FirmAgeMom`
usa el inicio truncado del historico descargado como edad; `IndRetBig` usa
SIC2 en vez de FF48; y `BetaLiquidityPS` no dispone de factor mensual actual.
La innovacion de liquidez procede de la
pagina oficial de Lubos Pastor en Chicago Booth. Esa serie llega hasta
diciembre de 2025: permite calcular historicamente `BetaLiquidityPS`, pero no
declararla actual para la formacion de julio de 2026. El resto conserva
explicitamente las limitaciones de identidad, industria, acciones y
capitalizacion actuales frente a CRSP historico.

Estado exacto: 25 rutas `prepared_unexecuted`, cinco
`blocked_formula_fidelity` y una `blocked_source_staleness`. No se ha lanzado
ningun run nuevo y, por tanto,
ninguna de las 31 se marca aun como adquirida o calculada en el
consolidado. Todas siguen con `strict_score_eligible=false`; el incremento del
score estricto es cero. Los recuentos ejecutados permanecen
`56/50/18/99/96814` y el score estricto confirmado permanece en 31.

La consolidacion futura usa el mismo `recovered_current_run_id` para los dos
artefactos derivados y comprueba dinamicamente cada senal, cada fila y su
procedencia. No contiene recuentos de cobertura prefijados: solo aceptara los
que publique y firme el run recuperador. Preparar esta conexion no ejecuta el
workflow ni modifica los recuentos publicados.

### Respaldo con Twelve Data

La ruta anterior sigue disponible como respaldo y requiere el secreto
`TWELVE_DATA_API_KEY`. El plan Basic es gratuito, permite uso interno no
visible y ofrece 8 creditos por minuto y 800 al dia. Esa credencial ya no es
necesaria para la ruta principal basada en artefactos existentes.

La ruta de adquisicion Twelve Data queda preparada en codigo, pero no ejecutada:

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
  ocho senales directas verificables: `BetaTailRisk`, `High52`,
  `MomOffSeason11YrPlus`, `MomRev`, `MomVol`, `RealizedVol`, `VolSD` y
  `VolumeTrend`. Exige
  por empresa los dos historicos ligados por hash, excluye sesiones
  incompletas y no convierte faltantes en cero. Si queda una sola peticion
  pendiente o fallida, no genera el artefacto derivado.
- `zerotrade1M`, `zerotrade6M` y `zerotrade12M` no estan preparados. La formula
  oficial agrega `vol/shrout` por meses completos, usa ventanas de 1, 6 y 12
  meses con deflactores 480.000/11.000 y desplaza el resultado un mes. El
  calculador compartido actual solo mide la fraccion de sesiones de volumen
  cero sobre 21/126/252 sesiones hasta la fecha de formacion; no aplica el
  ajuste de turnover, los bloques mensuales ni el desplazamiento. No se puede
  ligar ese resultado al hash oficial ni marcarlo `current_usable`.
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

Estado exacto del respaldo: `prepared_unexecuted`. Ya no se necesita que el
usuario facilite una clave para la ruta principal. Hay 20 calculadores
compartidos cuya formula queda preparada: 9 directos, incluido
`BidAskSpread`, y 11 con factores franceses gratuitos. Las tres variantes
`zerotrade` conservan una ruta de datos gratuita, pero no un calculador fiel.
`BidAskSpread` usa el estimador estandar Corwin-Schultz sobre maximos y minimos
nominales, pero permanece como proxy no estricto porque OpenAP carga un fichero
preprocesado por SAS cuyo tratamiento exacto no esta publicado. La ruta de
artefactos añade cinco calculadores restantes con formula preparada (`IndMom`,
`Size`, `TrendFactor`, `VolMkt` y `std_turn`): 25 en total. `BetaLiquidityPS`,
`FirmAgeMom` e `IndRetBig` conservan fuentes gratuitas documentadas, pero no
una salida actual fiel. En todas habra que completar
los intervalos historicos de ticker y medir cobertura y fidelidad. Por ello
las 31 siguen sin valor nuevo consolidado y con
`strict_score_eligible=false`. Esta cifra corrige el grupo provisional de 36:
`Activism1`, `Activism2`, `Herf`, `HerfAsset` y `HerfBE` no consumen OHLCV en
su formula oficial. Los tres `Herf` ya estaban entre los valores SEC
calculados; las dos `Activism` siguen bloqueadas por gobierno corporativo,
clase de accion e identidad, no por la clave de mercado. La formula exacta
necesita el G-index de 24 provisiones y excluye clases duales. El dataset CCG
Index (`doi:10.7910/DVN/T8UTXL`) es historico, exige un guestbook que no se ha
aceptado en nombre del usuario y no aporta un panel actual 2026 equivalente;
no se fabricaran esas entradas. Los recuentos
ejecutados permanecen `56/50/18/99/96814` y el score estricto confirmado
permanece en 31.

### Alternativas gratuitas de OHLCV reauditadas

La comprobacion oficial del 2026-08-10 confirma que el bloqueo es de cuenta y
capacidad gratuita, no de inexistencia de datos:

- [Tiingo](https://www.tiingo.com/about/pricing) ofrece en el plan gratuito
  historico EOD de mas de 30 anos, precios brutos y ajustados, 1.000 peticiones
  diarias y uso interno. Sin embargo, limita la API a 500 simbolos unicos al
  mes. Cubrir las 2.157 empresas exigiria al menos cinco meses y tambien un
  token gratuito; queda como respaldo lento, no como sustituto de la
  recuperacion inmediata de los artefactos ya existentes.
- [Finnhub](https://finnhub.io/pricing) permite 60 llamadas por minuto en el
  plan gratuito, pero su tabla oficial no incluye OHLC historico; el historico
  diario aparece en planes de mercado de pago.
- [EODHD](https://eodhd.com/financial-apis/api-for-historical-data-and-volumes)
  limita el plan gratuito a 20 llamadas diarias y al ultimo ano, insuficiente
  para la ventana oficial maxima de 180 meses.
- [Marketstack](https://marketstack.com/pricing/) limita el plan gratuito a
  100 llamadas mensuales y un ano de historia, tambien insuficiente.

La mejor ruta operativa ahora es recuperar los 48 artefactos existentes: no
requiere cuenta ni clave nueva y mantiene el vinculo de hashes del merge
auditado. Twelve Data Basic queda como respaldo para una adquisicion
independiente futura; no se usara ninguna clave publica o ajena.

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
no emite ceros. Esa evidencia SEC positiva es insuficiente y queda sustituida
en la consolidacion preparada por 2.157 clasificaciones binarias del artefacto
OpenAP93. Estas usan ex-dates Yahoo, exigen 24 meses previos sin pago y la
ventana oficial de seis meses, pero siguen sin codigos de distribucion CRSP.

El run CompanyFacts `31392473937` genero 14 valores de `DivOmit`: exige seis
trimestres consecutivos con dividendo explicito y un septimo con cero explicito,
y mantiene 1 durante el mes de disponibilidad SEC y el siguiente. No inventa
ausencias ni emite ceros. La ventana empieza en el filing y no en `exdt`, por
lo que la salida queda como reconstruccion no estricta. La consolidacion
preparada conserva esta procedencia, pero sustituye el resultado por las 2.157
clases 0/1 Yahoo que aplican las ventanas de omision de 3, 6 y 12 meses. La
sustitucion tambien es reconstruida no estricta y mantiene pendiente la
revision de terminos Yahoo.

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
