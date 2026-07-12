# Protocolo De 36 Pruebas De Acciones Con Datos Limitados: Diseño

## Objetivo

Ejecutar en GitHub Actions el protocolo de 36 pruebas del documento adjunto con un máximo solicitado de 360 jobs simultáneos, usando únicamente las 25 pruebas que pueden calcularse con el dataset público disponible y registrando las 11 restantes como `unsupported_missing_data`.

El resultado no se presentará como libre de sesgo de supervivencia. El estado de las candidatas será `research_candidate_survivorship_limited` porque el universo disponible contiene principalmente valores activos actuales y no el historial completo de empresas desaparecidas.

## Alcance temporal

- Investigación y walk-forward: `1995-01-01` a `2015-12-31`.
- Prueba final intacta: `2016-01-01` a `2020-12-31`.
- Locked cerrado: desde `2021-01-01`.
- Ninguna petición de datos, feature, merge o ranking leerá fechas posteriores a `2020-12-31`.

## Pruebas

### Ejecutables con limitaciones

Se ejecutan las pruebas `1`, `2`, `3`, `8`, `9`, `13`, `15`, `16`, `17`, `18`, `19`, `20`, `21`, `22`, `23`, `24`, `25`, `26`, `27`, `28`, `29`, `32`, `34`, `35` y `36`.

Sus limitaciones se registran por resultado: universo activo actual, ausencia de delistings completos, capitalización y clasificación histórica no bitemporal, ausencia de bid/ask observados y secuencia intradía desconocida cuando una vela toca stop y objetivo.

### Bloqueadas

Se registran como `unsupported_missing_data` las pruebas `4`, `5`, `6`, `7`, `10`, `11`, `12`, `14`, `30`, `31` y `33`.

Motivos principales:

- Falta de EPS, consenso, revisiones y guidance point-in-time.
- Falta de un panel contable completo con `available_at` histórico.
- Falta de clasificación histórica por país, sector, industria y tamaño.
- Falta de universo histórico con identificador permanente, empresas desaparecidas y retornos de exclusión.
- Falta de un universo regional materializado para Europa, Japón y emergentes.

No se inventarán proxies para convertir estas pruebas en ejecutables.

## Reglas comunes

- Sólo acciones ordinarias de la cotización principal disponible en el universo descargado.
- El precio y volumen conocidos al cierre de `t` sólo pueden producir una entrada en la apertura de `t+1`.
- Se conservarán OHLC sin ajustar para breakouts, stops y gaps; el retorno total ajustado se usará para rendimiento cuando la fuente lo permita.
- Los stops y objetivos se ejecutarán con la regla conservadora si una vela atraviesa ambos niveles y no existe secuencia intradía.
- Costes fijos: `0`, `5`, `10`, `25` y `50` puntos básicos por lado, con spreads observados sólo cuando existan.
- No se usará apalancamiento en la prueba principal.
- La selección y el aprendizaje ocurrirán dentro del protocolo temporal definido; la prueba final de 2016-2020 permanecerá intacta.
- `locked_opened=false` es una condición obligatoria del workflow y de todos los artefactos finales.

## Arquitectura

El workflow será un DAG único con preparación, olas secuenciales y merge. Cada ola pesada se divide en dos matrices de 180 entradas, ninguna matriz supera el límite de 256 y el máximo solicitado simultáneo es 360.

```text
validate
  -> prepare_data
  -> build_research_pack
  -> layer_1_signal (2 x 180)
  -> freeze_layer_1
  -> layer_2_weights (2 x 180)
  -> freeze_layer_2
  -> layer_3_entries (2 x 180)
  -> freeze_layer_3
  -> layer_4_exits (2 x 180)
  -> freeze_layer_4
  -> layer_5_portfolio (2 x 180)
  -> freeze_layer_5
  -> layer_6_costs (2 x 180)
  -> freeze_layer_6
  -> layer_7_walk_forward (2 x 180)
  -> freeze_layer_7
  -> layer_8_robustness (2 x 180)
  -> final_pareto
```

Las fases de preparación, congelación y merge usan un solo job y nunca se ejecutan a la vez que una matriz completa. El total de jobs del workflow puede superar 360, pero el máximo concurrente solicitado es 360.

## Distribución de datos

`prepare_data` reconstruirá en GitHub el universo público actual usando el descargador diario disponible, con una fecha final efectiva de `2020-12-31`. Se añadirá un parámetro de fin explícito al descargador si la interfaz actual no lo soporta, para evitar solicitar locked.

`build_research_pack` generará un paquete compacto y particionado por bloques de fechas. Cada worker recibe únicamente el bloque que necesita para su cálculo. Las fases de señales devuelven estadísticas y observaciones parciales; las fases posteriores reciben bundles compactos de eventos y precios para las candidatas congeladas.

Cada paquete incluye:

- OHLCV diario.
- Precio ajustado y retornos.
- Splits y dividendos disponibles.
- Benchmark `SPY` y `GSPC`.
- Metadatos de país, sector, industria y capitalización actuales, marcados como no bitemporales.
- `dataset_hash`, rango de fechas, proveedor y versión.

No se copiarán datos grandes repetidamente a los 360 workers. No se subirá ningún dato real al repositorio Git.

## Congelaciones entre capas

Cada `freeze_layer_N`:

1. Descarga todos los shards de la capa.
2. Rechaza duplicados, ausencias y hashes incompatibles.
3. Combina resultados de entrenamiento y ventanas internas permitidas.
4. Selecciona la configuración no dominada de la capa según las métricas definidas.
5. Escribe un snapshot inmutable con `config_hash`, `dataset_hash`, `policy_hash` y lista exacta de variantes.
6. Produce los bundles compactos que consumirá la siguiente capa.

La prueba final de 2016-2020 no participa en ninguna congelación.

## Control de completitud

Cada worker sube un artefacto con un nombre único basado en `phase`, `test_id`, `variant_id`, `time_block` y `shard_id`. El merge descarga cada artefacto en su propio directorio; no usa un merge plano que pueda sobrescribir nombres iguales.

El merge falla si:

- falta un shard esperado;
- aparece un shard duplicado o extra;
- cambia `dataset_hash`, `config_hash` o `policy_hash`;
- hay fechas posteriores a `2020-12-31`;
- `locked_opened` no es `false`;
- una capa intenta avanzar sin snapshot congelado;
- el resultado no contiene filas verificables.

Si una fase falla, las fases posteriores no arrancan y el resumen se publica con `partial=true` y el motivo exacto.

## Resultados

El artifact final será `stock-protocol-36-tests-360jobs-results` y contendrá:

- `protocol_manifest.json` — las 36 pruebas, estado, variantes y motivo.
- `data_audit.json` — cobertura, hashes y limitaciones.
- `test_status.csv` — estado por prueba y variante.
- `signal_layer_results.csv`.
- `entry_layer_results.csv`.
- `exit_layer_results.csv`.
- `portfolio_layer_results.csv`.
- `cost_scenarios.csv`.
- `walk_forward_results.csv`.
- `robustness_results.csv`.
- `pareto_frontier.csv`.
- `unsupported_missing_data.csv`.
- `final_summary.json`.
- `run_audit.md`.

`final_summary.json` debe contener al menos:

```json
{
  "tests_total": 36,
  "tests_executed_with_limitations": 25,
  "tests_unsupported_missing_data": 11,
  "locked_opened": false,
  "data_end": "2020-12-31",
  "final_holdout_start": "2016-01-01",
  "final_holdout_end": "2020-12-31",
  "survivorship_free": false,
  "full_protocol_compliance": false,
  "candidate_status": "research_candidate_survivorship_limited",
  "max_parallel_requested": 360,
  "partial": false
}
```

## Métricas

Se calcularán CAGR, Sharpe, Sortino, máximo drawdown, Calmar, rotación, exposición, retorno por capital-día, duración media y mediana, tiempo hasta beneficio, tiempo bajo máximos, peor sesión, peor mes, expected shortfall del 5%, peor gap y concentración en las diez mejores operaciones.

La selección final conservará la frontera no dominada por rendimiento neto, riesgo y tiempo de capital. No se declarará una única ganadora si varias permanecen en la frontera.

## Robustez

La fase 35 usará las implementaciones existentes cuando sean compatibles y añadirá los adaptadores que falten para:

- bootstrap por bloques;
- Sharpe deflactado;
- CSCV/PBO;
- corrección de múltiples pruebas;
- comparación contra benchmark;
- leave-one-period, leave-one-sector y leave-one-region cuando los datos existan;
- vecindarios de parámetros.

## Verificación en GitHub

Antes de ejecutar las fases pesadas, el propio workflow hará:

- validación del manifiesto de 36 pruebas;
- validación de YAML y matrices de 180 + 180;
- comprobación de fechas y bloqueo de locked;
- comprobación de que las 11 pruebas bloqueadas no entran en las matrices;
- comprobación de imports y sintaxis dentro de un job de GitHub;
- comprobación de que el artifact fuente no se sube al repositorio.

No se ejecutarán backtests, smokes ni pruebas locales en el PC.

