# Auditoria De Calidad OpenAP Current

Estado: `PENDING_FINAL_REBUILD`

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

## Evidencia Final Pendiente

La auditoria solo cambiara a `COMPLETED_CLEAN` cuando un run de GitHub genere
una base nueva y se comprueben:

- todos los tests enfocados en verde;
- todos los errores de `data_quality_issues.csv` a cero;
- contrato DuckDB sin violaciones;
- manifiesto y hashes validos;
- leaderboard no vacio;
- score 0-100 real;
- contribuciones reconciliadas;
- procedencia SEC declarada por fila, JSON canonico con hash y cero fallos SEC
  entre las acciones admitidas; el uso de read-through debe permanecer visible.
