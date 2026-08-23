# Auditoría de ejecución: optimización máxima del catálogo SPY

**Fecha:** 17 de agosto de 2026
**Worktree autoritativo:** `C:\Users\HP\AURORA_sp500_search_method_benchmark_short`
**Rama:** `codex/sp500-search-method-benchmark-short`
**HEAD auditado:** `7af75ec86aea31273b03b52e8e1befaec3a2593a`
**Ámbito:** SPY, catálogo completo, entrenamiento hasta `2010-12-31`
**Periodos protegidos:** validation 2011–2020 y locked 2021+ cerrados en todas las pruebas

## Resultado ejecutivo

El motor optimizado queda verificado para el catálogo SPY train-only. Las 37.258 recetas se mantienen, la ciencia coincide exactamente con el oráculo congelado y el mejor benchmark frío estable queda por debajo de un tercio del tiempo de la línea base.

La cifra de referencia del HEAD final es 270 segundos frente a 863 segundos de la línea base, aproximadamente **3,20 veces más rápido**. Dos fríos finales consecutivos dieron 270 s y el frío anterior compatible dio 267 s. Un run intermedio quedó en 517 segundos por espera de runners de GitHub; esa espera está identificada y separada en la auditoría, y no se ha ocultado.

## Identidad científica y contrato

| Campo | Evidencia | Resultado |
|---|---|---|
| Recetas solicitadas y canónicas | Runs `32007581030`, `32008536493`, `32009083553`, `32009762589` | 37.258 / 37.258 |
| Componentes físicos | `sp500-global-component-store/manifest.json` | 7.281 |
| Construcciones físicas | `component_performance.json` | 7.281 |
| Hash del contrato | `run_plan.json` y recibos | `98c788628688d8d0c4bdf52463dd0d0e5d11d42a1fa4eebe108395877c917253` |
| Hash de identidad científica | recibo final | `f0e8c6db17a915f7c5f1dfec7d49ce5a69375c7252c23b49d82283120266419f` |
| Oráculo congelado | run `31948898747` | hash de resultados `0c83b5a6957c0f85f37d88c8e7c0af46cb5d1d97f5f990cbd1bcf00de34573ac` |
| Fecha final de entrenamiento | manifiesto de runtime | `2010-12-31` |
| Validation | todos los recibos y manifiestos | `false` |
| Locked | todos los recibos y manifiestos | `false` |

## Benchmarks reales del catálogo completo

La línea base congelada es el run `31904259109`: 863 s, 37.258 recetas y aproximadamente 2.590 recetas/minuto.

| Estado | Run | HEAD | Pared | Recetas físicas | Recetas/min | Runner-horas | Equivalencia |
|---|---:|---|---:|---:|---:|---:|---|
| Línea base fría | `31904259109` | `ea0f968c` | 863 s | 37.258 | 2.590 | 28,74 | Oráculo |
| Frío | `32004690025` | `587cee51` | 267 s | 37.258 | 8.373 | 2,38 | Exacta |
| Frío, espera externa alta | `32007581030` | `dd4fe545` | 517 s | 37.258 | 4.324 | 2,38 | Exacta |
| Frío | `32008536493` | `dd4fe545` | 288 s | 37.258 | 7.762 | 2,40 | Exacta |
| Frío, HEAD final | `32009083553` | `eb56b707` | 270 s | 37.258 | 8.280 | 2,40 | Exacta |
| Frío, reducción auditada | `32009762589` | `7af75ec8` | 270 s | 37.258 | 8.280 | 2,40 | Exacta |
| Componentes preparados | `32005182219` | `587cee51` | 109 s | 37.258 | 20.509 | 0,50 | Exacta |
| Totalmente caliente | `32005427859` | `587cee51` | 81 s | 0 físicas / 37.258 recuperadas | 27.599 | 0,02 | Exacta |

El run `32009762589` registra además 528 s de espera de cola de GitHub, 760 s de cálculo de los workers y 10 s de reducción. La reducción representa el 3,70 % de la pared medida. El run caliente no cuenta aciertos de caché como evaluaciones físicas nuevas.

## Qué quedó verificado por fase

| Fase | Resultado | Evidencia principal |
|---:|---|---|
| 0. Medición e instrumentación | PASS | `runtime_audit.json`: pared, cola, cálculo, CPU, RAM, bytes y percentiles; diferencia contable 0 |
| 1. Contrato y admisión | PASS | `RunOptimizationContractV1`, token de admisión, rechazo de bypass y límites cerrados |
| 2. Costes y reparto | PASS | modelo de costes, planificación ponderada y matrices por carga medida |
| 3. Almacén global de componentes | PASS | 7.281 componentes, 7.281 construcciones físicas y manifiesto hash-bound |
| 4. Caché persistente | PASS | run caliente: 37.258 aciertos, 0 evaluaciones físicas, conflicto incompatible rechazado por pruebas |
| 5. Compilación de recetas | PASS | `recipe_dag_manifest.json`, canonización y 37.258 recetas conservadas |
| 6. Compactación de señales | PASS | round-trip exacto; 8× frente a float64 y 4× adicional de 2-bit frente a int8 |
| 7. Evaluación vectorizada | PASS | dos repeticiones: aceleración 29,56× y 43,06× en el kernel medido |
| 8. Multiproceso adaptativo | PASS | topologías y límites probados; 4 procesos para componentes, sin superar el límite de memoria |
| 9. Runtime preconstruido | PASS | setup P95 de 16–17 s y reducción de transferencia del 94,93 % |
| 10. Resultados y reducción | PASS | 496,56 bytes por receta y reducción auditada de 10 s / 270 s |
| 11. Autotuning | PASS | historial hash-bound con 10 muestras compatibles, decisión promovida y rollback probado |
| 12. Multi-activo | PASS | pruebas repetidas para 10 y 100 activos, calendario compartido y aislamiento |
| 13. Cross-sectional PIT | PASS en alcance de ingeniería | prueba end-to-end de pertenencia por fecha y escalado sparse a 1.000/5.000 activos |

Las fases 12–13 demuestran las interfaces y la memoria del motor con datos de prueba controlados; no constituyen todavía una campaña científica multi-activo con un universo externo nuevo.

## Gates permanentes

| Gate | Resultado | Prueba |
|---:|---|---|
| 1 | PASS | 37.258 recetas |
| 2 | PASS | identidades, procedencia y hashes del catálogo |
| 3 | PASS | decisiones y posiciones equivalentes al oráculo |
| 4 | PASS | 37.258 observadas, 37.258 esperadas, diferencias 0 |
| 5 | PASS | `validation_opened=false`, `locked_opened=false` |
| 6 | PASS | 7.281 componentes diferentes y 7.281 construcciones físicas; redundancia 0 % |
| 7 | PASS | 4.024 aciertos por equivalencia de comportamiento, sin eliminar recetas |
| 8 | PASS | incompatibilidades de datos, código y caché rechazadas por contrato y pruebas |
| 9 | PASS | reanudación solo de pendientes; escala de 10 millones con `resume_verified=true` |
| 10 | PASS | fríos, componentes preparados y caliente medidos por separado |
| 11 | PASS | pared, runner-horas, cola y cálculo registrados |
| 12 | PASS | CPU, memoria, transferencia, bytes y P50/P95 registrados |
| 13 | PASS | mejora de pared sin cambio científico |
| 14 | PASS en alcance probado | componentes y rutas multi-activo se añaden sin rehacer el historial compatible |
| 15 | PASS | prueba explícita de que una configuración más lenta no sustituye a la ganadora |
| 16 | PASS | frío auditado: 270 s frente a 863 s; 3,20× |
| 17 | PASS | construcciones redundantes de componentes: 0 % |
| 18 | PASS | reducción: 10 s / 270 s = 3,70 % |
| 19 | PASS | cero conflictos en manifiestos y recibos actuales |
| 20 | PASS | manifiestos reproducibles y hashes estables |

## Equivalencia y discrepancias históricas

El diagnóstico de equivalencia actual (`32006628848`) encontró 10/10 coincidencias con el resultado optimizado actual y 0 diferencias. Un resultado secundario antiguo contenía seis discrepancias en familias históricas; no se reutilizó como oráculo ni se mezcló con la campaña actual. La aceptación oficial se basa en el oráculo congelado completo `31948898747`, con diferencia 0.

## Pruebas locales

Prueba específica del motor y del contrato, ejecutada en el worktree autoritativo:

```text
70 passed
```

Incluye contrato, admisión, caché, reanudación, almacenamiento, scheduler, componentes, recetas, codec, vectorización, autotuning, rollback, multi-activo, PIT y guardas de workflow.

La batería general del repositorio no se usa como gate de este programa: terminó con 3 fallos no relacionados y un error interno del plugin de benchmarks en pruebas generales. No afectó a las 70 pruebas específicas ni a los runs de Actions del catálogo.

## Conclusión y límites

Para SPY y entrenamiento hasta 2010, el plan de optimización queda implementado y verificado. Los futuros runs de catálogo deben pasar por el contrato, construir o reutilizar únicamente componentes compatibles, informar frío/caliente por separado y conservar la evidencia de procedencia.

La extrapolación a un catálogo nuevo de un millón de estrategias queda preparada, pero las cifras de 1 y 10 millones del benchmark de arquitectura son una prueba de almacenamiento/flujo sintética: no equivalen a un millón de backtests científicos completos. La expansión multi-activo real necesitará sus propios datos y su propio contrato, sin abrir validation ni locked.
