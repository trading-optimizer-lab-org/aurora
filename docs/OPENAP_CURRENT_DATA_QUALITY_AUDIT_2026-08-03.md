# Auditoria De Calidad OpenAP Current

Estado: `COMPLETED_CLEAN_WITH_DOCUMENTED_LIMITATIONS`

Run final de GitHub Actions: `30837929185`

Commit: `3e77df856f41910fd187c1388ca5b28d6ba42464`

Artifact: `openap-yfinance-sec-current-score-results`

Base auditada: `E:\AURORA_DATA\OPENAP_FINAL_FIXED_30837929185\openap_current.duckdb`

Esta auditoria cubre la base actual de OpenAP construida con YFinance y SEC
EDGAR. La integridad estructural por si sola no demuestra que un dato o score
sea economicamente correcto. La aceptacion final exige tambien los controles
semanticos descritos aqui.

## Problemas Encontrados Y Correccion

| Area | Problema encontrado | Correccion | Gate final |
|---|---|---|---|
| Formulas contables | Varias formulas parciales figuraban como exactas | Formula oficial cuando las entradas bastan; si falta una parte central se rebaja a proxy o unavailable | `exact_formula_policy_violations=0` |
| Acciones en circulacion | Algunos valores SEC pertenecian a otra clase, unidad o periodo y generaban turnovers absurdos | Seleccion del ultimo dato instantaneo y contraste SEC/Yahoo; discrepancias grandes usan Yahoo como proxy auditado | No se admiten formulas antiguas de unidades mezcladas |
| ShareVol y std_turn | Volumen bruto se mezclaba con acciones en circulacion | Turnover mensual adimensional; ShareVol binario oficial y std_turn de 36 meses | `mixed_unit_turnover_rows=0` |
| Ventanas de precio | MRreversal, LRreversal, DolVol e Illiquidity no seguian las ventanas oficiales | MR 18-13, LR 36-13, DolVol mensual lag 2 e Illiquidity 252 sesiones | Tests de formula y `formula_id` |
| Mes parcial | STreversal y estacionalidad podian desplazarse al incluir el mes en curso incompleto | Las senales mensuales usan solo meses naturales cerrados; las diarias conservan el ultimo precio | Test causal de mes parcial |
| Sesion diaria parcial | Yahoo puede publicar la vela diaria antes del cierre y contaminar precio, volumen y volatilidad | Solo se usa la ultima sesion regular cerrada, con margen de 15 minutos tras las 16:00 de Nueva York | `incomplete_clean_price_rows=0` |
| Volatilidad realizada | Volatilidad total se presentaba demasiado cerca de una medida residual | Se mantiene solo como proxy explicito | Ninguna fila proxy puede llamarse exacta |
| Senales constantes | OptionVolume2 y variantes zerotrade podian aumentar confianza sin discriminar acciones | Deteccion transversal automatica; peso cero y estado `uninformative_cross_section` | `uninformative_weighted_rows=0`, `weighted_constant_predictors=0` |
| Senales demasiado escasas | Un predictor con muy pocas acciones podia producir percentiles extremos poco comparables | Minimo 100 observaciones y 5% del universo; por debajo pesa cero | `undercovered_weighted_predictors=0` |
| Opciones | Cadenas con muy pocos contratos producian proxies inestables | Hasta tres vencimientos descargados; se elige el mas cercano con profundidad minima de calls y puts | `shallow_option_feature_rows=0` |
| Score 0-100 | El valor anterior era una media comprimida, no un percentil final real | Se conserva `raw_score`; el score principal es el percentil transversal real entre acciones admitidas | `overall_score_scale_violations=0` |
| Universo del percentil | Acciones luego rechazadas influian en el percentil de las validas | El percentil final se recalcula solo entre acciones que pasan todos los requisitos | Minimo 0 y maximo 100 en el leaderboard |
| Cobertura | Entraban acciones con demasiados predictores ausentes o confianza muy baja | Minimo 60 calculados, maximo 125 ausentes y confianza minima 50 | `undercovered_leaderboard_rows=0` |
| Conteo de cobertura | `computed_features` se calculaba antes de filtros, frescura y controles transversales | Solo cuentan predictores exact/proxy con peso positivo y percentil utilizable final | El conteo coincide con las contribuciones observadas |
| Frescura SEC | Un dato reciente de acciones podia ocultar fundamentales antiguos | Fecha causal por predictor y dos relojes globales: actividad SEC maxima 183 dias y cuentas anuales maximo 550 dias; avisos a 92 y 365 dias | `stale_sec_leaderboard_rows=0`, `stale_accounting_leaderboard_rows=0`, `stale_weighted_feature_rows=0` |
| Historia de precios | Historias reiniciadas, demasiado cortas o con cotizacion vieja podian entrar | Minimo 756 sesiones limpias y ultimo cierre con antiguedad maxima de 5 dias naturales | `insufficient_clean_price_history` y `stale_leaderboard_prices=0` |
| Liquidez y small caps | El ranking de investigacion mezclaba valores poco operables con acciones liquidas | Vista separada deployable: market cap >= 1.000 M USD, ADV >= 10 M USD y 1.260 sesiones | `deployment_eligible` y motivo explicito |
| Clases de acciones | Se eliminaban clases ordinarias validas por compartir CIK con otra clase del mismo emisor | Se conservan todas las clases elegibles y se etiquetan `issuer_share_class_count` e `issuer_primary_security` | Ninguna clase valida se descarta solo por compartir CIK |
| Pais del emisor | Un `country` vacio en Yahoo excluia acciones domesticas validas | Si Yahoo no informa pais, se exige evidencia SEC de domicilio o negocio en EE. UU.; un pais Yahoo extranjero sigue excluyendo | Motivo de exclusion explicito y auditable |
| Capitalizacion multiclase | Fundamentales del emisor podian dividirse por la capitalizacion aislada de una clase | Capitalizacion consolidada por CIK: valores repetidos similares no se duplican; valores claramente distintos se suman | `missing_issuer_market_cap_leaderboard_rows=0` |
| Horizontes | `portperiod` se describia como horizonte predictivo probado | Se etiqueta como periodo oficial de mantenimiento diagnostico; el ranking usa un score conjunto actual | `score_bucket_semantics` |
| Explicabilidad | No existia desglose completo del score | Contribucion por predictor, grupo y familia; debe reconstruir el raw score | `score_contribution_mismatches=0` |
| Grupos con familias mixtas | Un grupo redundante podia formar una etiqueta de familia combinada y eludir el limite familiar | Cada grupo recibe una sola familia dominante por evidencia y conserva un unico voto | `family_weight_cap_violations=0` |
| SEC | Miles de peticiones individuales dependian de un read-through externo | La ruta primaria usa un ZIP oficial; si SEC bloquea las IP compartidas de GitHub, la reparacion usa 48 shards de endpoints oficiales y conserva cada JSON canonico con hash | `sec_source_layout` y `source_mode` explicitos |
| Acceso SEC desde GitHub | Tanto `www.sec.gov` como `data.sec.gov` devolvieron 403 aun con identidad, `Host` y backoff correctos | Fallback fail-closed mediante read-through publico de cada endpoint oficial, con URL SEC original, URL de acceso, JSON canonico y SHA-256 por emisor | Cualquier emisor sin Company Facts o Submissions queda fuera del ranking |
| Volumen SEC bulk | El primer lector bulk recorria todo XBRL; limitar sin separar trimestres tambien podia borrar el historial anual de cinco anos | El ZIP se filtra por 52 etiquetas y conserva 24 observaciones recientes mas al menos 8 anuales | Cobertura causal suficiente para lags de cinco anos sin guardar XBRL ajeno |
| Retencion | Artifacts fuente se eliminaban a los 30 dias | Retencion de 90 dias | Contrato YAML/workflow |
| Documentacion | Cifras y significado del score habian quedado obsoletos | Estado historico separado y contrato v2 documentado | Revision documental |

## Requisitos De Ranking

Una accion solo aparece en `openap_current_leaderboard` si cumple todos estos
requisitos:

1. Accion comun estadounidense operativa y emisor SEC valido.
2. Market cap minimo de 100 M USD y precio minimo de 1 USD.
3. Volumen medio de 21 dias minimo de 10.000 acciones.
4. Volumen monetario medio de 21 dias minimo de 1 M USD.
5. Al menos 756 sesiones de precios limpios y precio reciente.
6. Company Facts y Submissions disponibles.
7. Al menos 60 predictores calculados y no mas de 125 ausentes.
8. Confianza agregada minima de 50.
9. Inputs SEC usados con antiguedad maxima de 183 dias.
10. Score operativo no nulo y contribuciones reconciliadas.

La vista `openap_current_deployable_leaderboard` endurece market cap, liquidez e
historia. La separacion evita convertir una decision practica de ejecucion en
una alteracion silenciosa del universo cientifico.

## Limitaciones Que No Deben Ocultarse

- Es una fotografia transversal actual, no un backtest.
- El score no es una probabilidad de subida.
- Los periodos oficiales de cartera no prueban horizontes predictivos
  independientes.
- Algunas señales de OpenAP requieren CRSP, Compustat, IBES, OptionMetrics,
  13F historico, short interest historico, factores o microestructura que no
  ofrecen YFinance y SEC EDGAR.
- Esas señales deben seguir como `unavailable` o proxy explicito. Convertirlas
  en formulas inventadas seria peor que dejarlas fuera.
- La estabilidad walk-forward y los costes reales necesitan otra fase con
  historia causal. No se incorporan como pesos ficticios al score actual.

## Evidencia Final Verificada

La reconstruccion final cumple los controles de integridad y aceptacion:

- 35 de 35 archivos verificados contra `output_manifest.csv`.
- 5.446.947.489 bytes comprobados y cero diferencias de tamano o SHA-256.
- 74 de 74 contratos DuckDB aprobados y cero violaciones.
- 36 de 36 controles duros de calidad aprobados, todos con cero incidencias.
- 48 de 48 shards YFinance y 48 de 48 shards SEC presentes, indices 0 a 47.
- 26.525.313 precios raw y 18.717.934 precios clean sin duplicados ni futuro.
- 3.304.389 filas Company Facts y 3.987.615 filas Submissions.
- 2.338 acciones elegibles, 876 en ranking de investigacion y 757 deployable.
- Score transversal en escala real 0-100 y 411.488 contribuciones reconciliadas.
- Diferencia maxima de reconstruccion del score: aproximadamente `3,55e-14`.
- 29.297 contratos de opciones utilizables, cero duplicados utilizables.
- `locked_opened=false`, `backtest_enabled=false`,
  `validation_used_for_selection=false` y `partial=false`.
- Cero fallos SEC entre las acciones admitidas en el ranking.

## Problemas Que Siguen Existiendo

No son corrupcion de la base, pero limitan el uso del score:

1. **Cobertura incompleta de OpenAP.** De 185 predictores, 30 tienen valores
   exactos, 61 proxy, 1 mezcla exact/proxy y 93 siguen `unavailable`. Una accion
   del ranking tiene entre 60 y 82 predictores utilizables, mediana 67.
2. **Score sin validacion historica.** El estado oficial es
   `unvalidated_current_snapshot_only`. El valor 0-100 es atractivo relativo
   actual, no probabilidad de subida ni evidencia de rentabilidad futura.
3. **Dependencia de read-through para SEC.** GitHub no obtuvo ninguna descarga
   SEC directa; 11.497 superficies validas llegaron mediante Jina sobre las URL
   oficiales. Se conserva URL, JSON canonico y hash, pero el intermediario anade
   riesgo operativo y de disponibilidad.
4. **203 Company Facts incompletos fuera del ranking.** Todos pertenecen a
   valores no elegibles/no admitidos, por lo que no contaminan el leaderboard,
   pero el lago raw no cubre al 100% esos fondos u otros instrumentos excluidos.
5. **Frescura desigual.** Hay 463 inputs SEC y 12 inputs contables por encima
   del umbral de aviso. Ninguno supera el limite duro dentro del ranking ni
   aporta peso estando caducado.
6. **Calidad raw de mercado.** Se pusieron en cuarentena 14.609 filas de precio
   no positivo. La capa clean no las contiene.
7. **Opciones estrictamente filtradas.** De 224.174 filas raw quedan 29.297
   utilizables. Se aislaron 7 duplicados raw y 14 identidades OCC incoherentes;
   no queda ninguna en la capa utilizable.
8. **119 valores son solo de investigacion.** Pasan el ranking cientifico, pero
   no los requisitos deployable de capitalizacion, liquidez o historia.
9. **235 clases secundarias ordinarias conservadas.** Es intencionado y esta
   auditado por emisor, pero cualquier cartera debe controlar concentracion por
   CIK para no comprar dos clases del mismo negocio sin querer.

La base queda estructuralmente limpia y reproducible. La siguiente mejora de
valor no es reparar DuckDB: es conseguir fuentes gratuitas adicionales para
los 93 predictores ausentes y validar el score con historia causal walk-forward.
