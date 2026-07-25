# Estándar maestro Aurora para runs de GitHub

**Versión:** 3.0  
**Objetivo:** que cualquier run falle de forma controlada, conserve todo el trabajo válido, explique la causa y pueda reanudarse exactamente donde quedó.

## La verdad incómoda

No es posible garantizar que GitHub, Internet, una API o un runner jamás fallen. Sí es posible imponer estas garantías:

1. Un fallo nunca pasa desapercibido.
2. Un workflow verde nunca significa resultado vacío o parcial.
3. Un shard correcto nunca se repite por culpa de otro shard.
4. Cada etapa puede reanudarse.
5. Ningún dato prohibido entra en el cálculo.
6. Ningún resultado depende de una versión cambiante no registrada.
7. No se lanza el fan-out completo sin superar validación, smoke y piloto.
8. Cada decisión, input, hash, artifact y resultado queda auditado.

Esta plantilla sustituye el enfoque de “lanzar y vigilar” por un sistema de **prevenir, aislar, detectar, conservar y reanudar**.

---

# PARTE I. CONTRATO INMUTABLE DEL RUN

No se escribe el workflow hasta completar esta parte.

## 1. Identidad

| Campo | Valor obligatorio |
|---|---|
| `campaign_id` único | |
| Nombre legible | |
| Tipo | |
| Repo | `trading-optimizer-lab-org/aurora` |
| Rama de código | |
| SHA completo de código | |
| Workflow | |
| Versión del spec | |
| Fecha de creación UTC | |
| Responsable | |
| Presupuesto máximo | |
| Deadline | |

Tipos:

- `search`
- `optimization`
- `backtest`
- `robustness`
- `literature`
- `data_download`
- `merge_only`
- `nightly_campaign`
- `locked_report`
- `smoke`
- `infrastructure_test`

Reglas:

- El SHA queda congelado antes del smoke.
- Todos los jobs hacen checkout del mismo SHA.
- Ningún job usa una rama móvil como fuente de código.
- Un cambio de código crea una nueva versión de campaña.
- El `campaign_id` no se reutiliza.

## 2. Objetivo verificable

```text
OBJETIVO:


UNIDAD EVALUADA:


CONDICIÓN DE ÉXITO:


CONDICIÓN DE RESULTADO NEGATIVO VÁLIDO:


CONDICIÓN DE FALLO TÉCNICO:


QUÉ NO DEBE HACER:

```

## 3. Política cuantitativa

| Campo | Valor |
|---|---|
| Train inicio/fin | |
| Validación inicio/fin | |
| Locked inicio | |
| Locked abierto | `false` |
| Filas locked permitidas | `0` |
| Validación usada para selección | `false` |
| Frecuencia de señal | |
| Frecuencia de ejecución | |
| Lag causal mínimo | |
| Costes | |
| Slippage | |
| Financiación | |
| Size/apalancamiento | |
| Benchmark | |
| Proxy permitido | |
| Correlación mínima proxy | |

Bloqueos:

- `locked_opened` debe ser `false`.
- `locked_rows_accessed` debe ser `0`.
- `validation_used_for_selection` debe ser `false`.
- La validación no puede elegir reglas, parámetros, size, filtros ni ranking interno.
- Las señales deben usar sólo información disponible en la fecha de decisión.
- Los fundamentales usan `available_at`, no el cierre del periodo contable.
- Las noticias usan `published_at`.
- Los activos inexistentes no se rellenan con cero.
- Los proxies se identifican como proxies.
- Una réplica incompleta de un paper no se llama réplica exacta.

## 4. Contrato de resultados

| Resultado | Archivo | Esquema/version | Obligatorio |
|---|---|---|---:|
| Summary | `summary.json` | | Sí |
| Manifest usado | `manifest_used.json` | | Sí |
| Leaderboard | `leaderboard.parquet` y/o `.csv` | | Según run |
| Aceptadas | `accepted.csv` | | Según run |
| Rechazadas | `rejected.csv` | | Sí |
| Fallos técnicos | `technical_failures.csv` | | Sí |
| Shards ausentes | `missing_shards.csv` | | Sí |
| Auditoría de datos | `data_audit.json` | | Sí |
| Auditoría de política | `policy_audit.json` | | Sí |
| Auditoría de ejecución | `runtime_audit.json` | | Sí |
| Procedencia | `provenance.json` | | Sí |
| Contrato de rendimiento | `performance_contract.json` | | Sí |
| Plan de rendimiento | `performance_plan.json` | | Sí |
| Plan de ejecución resuelto | `execution_plan.json` | | Sí |
| Plan de shards | `balanced_shard_plan.json` | | Según run |
| Desglose temporal | `runtime_breakdown.parquet` | | Sí |
| Informe de cuello de botella | `bottleneck_report.json` | | Sí |
| Resultado de rendimiento | `performance_final.json` | | Sí |

El contrato define columnas, tipos, nulos permitidos, claves únicas y versión de esquema.

---

# PARTE II. PRINCIPIOS QUE NO SE NEGOCIAN

## 5. Fail closed

Ante una duda, el workflow falla. Nunca se convierte automáticamente:

- un archivo ausente en cero filas;
- un error de descarga en datos vacíos;
- una fecha ausente en cero;
- una estrategia no soportada en un proxy inventado;
- un merge parcial en resultado completo;
- un warning de artifact en éxito;
- una auditoría ausente en `false`;
- una excepción en una fila silenciosamente descartada.

## 6. Idempotencia

Repetir un job con los mismos inputs debe producir:

- el mismo `candidate_id` o `record_id`;
- el mismo rango de trabajo;
- la misma semilla;
- el mismo esquema;
- el mismo hash, salvo metadatos temporales separados.

Cada unidad de trabajo tiene una clave:

```text
unit_key =
  campaign_id
  + code_sha
  + data_snapshot_hash
  + spec_hash
  + wave
  + shard_id

attempt_id =
  unit_key
  + attempt_number
```

Reglas:

- `unit_key` identifica el trabajo lógico y nunca cambia al reintentarlo.
- `attempt_id` identifica cada intento físico.
- `candidate_id`, `record_id` y demás IDs científicos no incluyen ola, shard ni intento.
- Los artifacts de intentos usan nombres distintos y nunca sobrescriben un intento anterior.
- El manifest final identifica qué `attempt_id` válido produjo cada `unit_key`.

## 7. Trabajo durable

Cada unidad correcta se conserva antes de continuar. No depender de:

- disco temporal del runner;
- memoria de un proceso;
- outputs de job demasiado grandes;
- una variable de entorno;
- el estado de un monitor local;
- que el siguiente job arranque.

## 8. Fuente única de verdad

Un único `campaign_manifest.json` contiene:

- jobs esperados;
- olas;
- shards;
- rangos;
- semillas;
- hashes;
- schemas;
- datasets;
- artifacts esperados.

No repetir estos números manualmente en YAML, Python y documentación.

---

# PARTE III. EJECUCIÓN EN CINCO PUERTAS

El run completo no puede saltarse ninguna puerta.

## Puerta 0: validación estática

No consume fan-out.

Debe comprobar:

- YAML parseable.
- Workflow presente en la rama por defecto.
- Código presente en el SHA.
- Scripts y configs referenciados existen.
- Imports válidos.
- Nombres de jobs y artifacts únicos.
- Matrices expandidas menores o iguales a 256.
- Inputs tipados y dentro de rango.
- Timeouts coherentes.
- Permisos mínimos.
- Acciones externas fijadas por SHA completo.
- `persist-credentials: false` salvo necesidad escrita.
- No hay secretos en `env` global.
- No hay `continue-on-error: true` en pasos críticos.
- No hay artifacts críticos con warning ante archivos ausentes.
- No hay selección por validación.
- No hay lectura locked.
- No hay rutas Windows dentro de jobs Linux.
- No hay referencias operativas a repos o nombres antiguos.
- No hay dependencias sin versión fijada.
- No existe un run equivalente activo.

**Salida:** `preflight_report.json`.

## Puerta 1: smoke real en GitHub

Máximos:

- 1 dataset pequeño con el mismo esquema.
- 1 o 2 olas.
- 4 shards.
- 1.000 unidades.
- mismo camino de datos, trabajo, upload, download, merge y auditoría.

Debe probar:

- descarga;
- snapshot;
- manifest;
- dos shards distintos;
- archivo no vacío;
- hash;
- upload;
- download;
- merge;
- deduplicado;
- políticas;
- artifact final;
- cancelación limpia;
- shard ausente simulado;
- relanzamiento selectivo.

**Salida:** `smoke_verdict=pass`.

## Puerta 2: piloto

Ejecuta entre 1% y 5% del trabajo real, con mínimo suficiente para medir:

- segundos por unidad;
- RAM pico;
- disco pico;
- tamaño por shard;
- tiempo de upload;
- tiempo de merge proyectado;
- tasa de errores;
- paralelismo real observado;
- costes/minutos.

El piloto falla si:

- proyecta superar timeout;
- proyecta llenar disco;
- tamaño final supera presupuesto;
- tasa técnica de error supera 0,5%;
- los resultados no cumplen esquema;
- el paralelismo real invalida el deadline;
- el merge proyectado no cabe;
- aparece un warning no clasificado.

**Salida:** `pilot_verdict=pass`, `performance_pilot.json`,
`performance_plan.json` y presupuesto recalculado.

## Puerta 3: producción por olas

El fan-out se ejecuta en olas. Una ola nueva no comienza hasta:

- verificar todos los manifests de la anterior;
- conocer shards ausentes;
- relanzar o declarar parcial según política;
- guardar `campaign_state.json`.

No lanzar todo de golpe si impide recuperar por bloques.

## Puerta 4: merge y auditoría final

El merge final sólo produce `complete=true` si:

- encuentra todos los shards esperados;
- no hay IDs duplicados injustificados;
- hashes correctos;
- schemas correctos;
- filas cuadran;
- outputs obligatorios existen;
- locked cerrado;
- validación no intervino;
- no hay errores técnicos sin resolver.

---

# PARTE IV. MÁQUINA DE ESTADOS

## 9. Estados permitidos

```text
CREATED
VALIDATING
VALIDATED
SMOKE_RUNNING
SMOKE_PASSED
PILOT_RUNNING
PILOT_PASSED
DATA_READY
RUNNING
PAUSING
PARTIAL
RETRYING
MERGING
VERIFYING
COMPLETED
FAILED_TECHNICAL
COMPLETED_NEGATIVE_RESULT
CANCELLED_BY_USER
BLOCKED_EXTERNAL
```

No usar sólo `success/failure` de GitHub como estado de campaña.

## 10. Estado durable

El estado nunca se sobrescribe. Cada transición crea un archivo inmutable:

```text
campaign_state_v000001.json
campaign_state_v000002.json
...
campaign_state_latest.json
```

`campaign_state_latest.json` es sólo un puntero verificable a la última versión. Cada
estado incluye `state_version`, `previous_state_sha256` y `writer_run_id`. Una
actualización se rechaza si parte de una versión antigua, para impedir que dos
workflows de recuperación se pisen.

Contenido:

```json
{
  "campaign_id": "",
  "state_version": 1,
  "previous_state_sha256": null,
  "writer_run_id": "",
  "state": "CREATED",
  "code_sha": "",
  "spec_hash": "",
  "data_snapshot_hash": "",
  "last_completed_wave": -1,
  "completed_shards": [],
  "failed_shards": [],
  "missing_shards": [],
  "retry_count_by_shard": {},
  "run_ids": [],
  "last_updated_at": "",
  "resume_action": ""
}
```

Se sube tras cada ola y tras cada transición.

---

# PARTE V. DATOS

## 11. Snapshot

Todo run usa un snapshot inmutable:

```json
{
  "dataset_id": "",
  "dataset_version": "",
  "sha256": "",
  "source": "",
  "source_url": "",
  "downloaded_at": "",
  "min_date": "",
  "max_date": "",
  "rows": 0,
  "symbols": 0,
  "schema_version": ""
}
```

## 12. Controles de datos

- Fechas monotónicas.
- Sin duplicados de clave.
- Sin timestamps futuros.
- Zona horaria explícita.
- Calendario bursátil correcto.
- Horario regular, premarket y afterhours separados.
- Splits/dividendos coherentes.
- Ajustado y no ajustado diferenciados.
- Delisted incluidos cuando corresponda.
- `listed_from` y `delisted_at` causales.
- Huecos cuantificados, nunca ocultos.
- Outliers marcados.
- Cobertura mínima.
- Columnas y dtypes exactos.
- Revisión de cambios de schema del proveedor.
- Revisión de revisiones históricas.
- Checksum de archivos.
- Licencia y redistribución permitidas.

## 12.1 Contrato causal de mercado

Todo backtest declara explícitamente:

- zona horaria de decisión y de ejecución;
- calendario y mercado de referencia;
- instante exacto de observación de la señal;
- primera marca de precio realmente ejecutable;
- política para órdenes en días sin sesión o con sesión parcial;
- precio usado: open, close, VWAP, bid/ask u otro;
- retorno total o retorno de precio;
- adjusted y unadjusted, sin mezclarlos;
- splits, dividendos, distribuciones y cambios de ticker;
- tratamiento causal de delistings y `delisting_return`;
- divisa local, conversión FX y hora del fixing;
- rendimiento de cash/T-bills;
- borrow availability, borrow cost y financiación cuando existe short;
- redondeo, fracciones, lotes y límites de negociación.

El lag se expresa en tiempo de mercado, no sólo como `shift(1)`. El audit debe
demostrar que `execution_timestamp > latest_information_timestamp` en todas las
operaciones.

## 13. Fallos de proveedor

| Escenario | Detección | Acción |
|---|---|---|
| 401/403 | Código HTTP | Bloquear: credencial o plan |
| 404 | Código HTTP | Probar sólo URLs alternativas permitidas |
| 429 | Código y headers | Backoff con jitter y respeto a `Retry-After` |
| 5xx | Código HTTP | Reintento limitado e idempotente |
| Timeout | Excepción | Reintento limitado |
| HTML en vez de datos | Content-Type y firma | Rechazar |
| Respuesta truncada | Longitud, checksum, parser | Reintentar |
| Schema cambiado | Validación de columnas | Bloquear y versionar adaptador |
| Datos revisados | Hash distinto | Nueva versión de snapshot |
| Cuota agotada | Respuesta/proveedor | `BLOCKED_EXTERNAL` |

Nunca reintentar indefinidamente.

---

# PARTE VI. RECURSOS Y LÍMITES

## 14. Presupuesto

| Campo | Valor |
|---|---:|
| Olas | |
| Jobs por ola | |
| Jobs totales | |
| Matrices por ola | |
| Máximo por matriz | `256` |
| Paralelismo solicitado | |
| Paralelismo conservador | |
| Minutos internos por job | |
| Timeout por job | |
| RAM estimada/job | |
| Disco estimado/job | |
| Artifact estimado/job | |
| Merge estimado | |
| Minutos facturables máximos | |
| Coste máximo | |

## 15. Duración

```text
tandas_por_ola =
  ceil(jobs_por_ola / paralelismo_conservador)

tiempo_ola =
  tandas_por_ola × tiempo_p95_job

tiempo_total =
  preflight
  + smoke
  + piloto
  + datos
  + cola
  + suma(tiempo_olas)
  + uploads
  + merge
  + verificación
  + margen
```

Usar p95 del piloto, no la media.

## 16. Guardas de recursos en cada job

Registrar al inicio y cada cierto intervalo:

- espacio libre;
- RAM disponible;
- carga;
- filas procesadas;
- bytes escritos;
- tiempo por unidad;
- ETA interna.

Abortar de forma limpia antes de:

- disco menor de 10% libre;
- RAM sostenida mayor de 90%;
- ETA mayor que timeout menos margen;
- archivo mayor que límite interno;
- ausencia de progreso.

El presupuesto de disco usa el pico simultáneo, no sólo el tamaño final:

```text
peak_disk_required =
  source_download
  + extracted_source
  + existing_output
  + atomic_temporary_output
  + compression_workspace
  + upload_staging
  + safety_margin
```

Para reparaciones atómicas y conversiones grandes se exige medir el multiplicador
temporal real en el piloto. No se autoriza producción si el espacio libre p05
proyectado baja del umbral.

## 17. Límites externos

Antes de cada campaña grande se revisan las páginas oficiales de límites y el estado de la organización. No asumir que un límite histórico sigue igual.

Hechos que deben validarse:

- 256 jobs por matriz.
- concurrencia estándar disponible para la organización;
- duración máxima de job;
- cola de grupos de concurrencia;
- almacenamiento y retención;
- minutos y presupuesto;
- máximo de reruns;
- límites de API.

---

# PARTE VII. SEGURIDAD Y GOBIERNO

## 18. Permisos

Por defecto:

```yaml
permissions:
  contents: read
```

Permisos de escritura sólo en un job aislado y justificado.

Prohibido por defecto:

- `actions: write`;
- `contents: write`;
- `pull-requests: write`;
- `id-token: write`;
- secretos globales;
- token persistido por checkout.

## 19. Acciones y dependencias

- Acciones externas fijadas por SHA completo.
- Verificar que el SHA pertenece al repositorio oficial.
- `actions/checkout` con `persist-credentials: false`.
- Dependencias Python con lock/constraints y hashes.
- Versión exacta de Python.
- Versión exacta del SO/runner cuando sea crítico.
- No instalar desde ramas móviles.
- No ejecutar código externo configurable sin allowlist.
- Repos externos por SHA completo.
- SBOM o lista de dependencias en el artifact de auditoría.

## 20. Secretos

- Nunca imprimir secretos.
- Nunca pasarlos a pasos que no los necesitan.
- Nunca subir `.env`.
- Nunca incluirlos en arguments persistidos.
- Aplicar mínimo privilegio y caducidad.
- Detectar secretos en outputs antes de subir artifacts.
- Si un secreto puede haberse filtrado: cancelar, rotar y registrar incidente.

## 21. Inputs no confiables

No interpolar directamente en shell:

- títulos;
- nombres de rama;
- inputs libres;
- contenido de issues;
- rutas;
- URLs;
- nombres de artifacts.

Validar con allowlists y pasar como argumento o variable segura.

## 22. Protección del repositorio

Antes de producción:

- branch protection o ruleset para `main`;
- PR obligatorio para workflows críticos;
- checks obligatorios;
- force-push y borrado bloqueados;
- CODEOWNERS para `.github/workflows/**`;
- política de acciones permitidas;
- SHA pinning;
- auditoría de workflows remotos que no existen localmente.

---

# PARTE VIII. WORKFLOW UNIVERSAL

## 23. Triggers

Research pesado:

```yaml
on:
  workflow_dispatch:
```

No usar `push` para runs pesados.

`workflow_run` sólo si:

- existe en `main` antes del evento;
- no usa un ID histórico como única condición;
- tiene permisos mínimos;
- tiene anti-duplicado;
- se elimina cuando acaba la campaña.

## 24. Concurrency

No copiar una configuración sin decidir su semántica.

- `cancel-in-progress: false` si preservar el run activo es prioritario.
- `cancel-in-progress: true` sólo para trabajo sustituible.
- Comprobar el comportamiento de pendientes.
- La clave incluye campaña y rama.
- La capitalización de la clave no debe crear colisiones.

## 25. Matrices

- Máximo 256 por matriz.
- `fail-fast: false` en investigación por shards.
- Cada shard independiente.
- No esconder un fallo por `continue-on-error`.
- Matrices A/B sólo cuando suman el paralelismo deseado sin excederlo.
- Los IDs no dependen del orden de la matriz.
- El número y tamaño de matrices se generan desde el manifest.
- Para 360 jobs utilizables, la partición por defecto es `256 + 104`.
- No se escriben manualmente listas extensas de IDs dentro del YAML.
- El fan-out usa bundles equilibrados por coste estimado, no sólo por número de filas.

## 26. Timeouts

| Etapa | Regla |
|---|---|
| Validate | Corto |
| Data | p95 histórico + margen |
| Shard | presupuesto interno + 20% |
| Upload | tamaño proyectado + margen |
| Merge | proyección del piloto + 50% |
| Final audit | corto |

El proceso debe capturar señal de terminación y guardar checkpoint antes de morir.

## 27. `always()` y cancelación

`always()` puede dificultar cancelaciones y ejecutar pasos no deseados.

Usarlo sólo para:

- guardar logs;
- guardar state;
- generar auditoría;
- preservar parciales.

No usarlo para:

- aceptar resultados;
- ejecutar merge final como si todo fuera correcto;
- iniciar otra ronda;
- abrir locked.

Preferir condiciones que respeten `cancelled()`.

---

# PARTE IX. SHARDS Y ARTIFACTS

## 28. Manifest de shard

```json
{
  "campaign_id": "",
  "unit_key": "",
  "attempt_id": "",
  "attempt_number": 0,
  "shard_id": "",
  "wave": 0,
  "input_start": 0,
  "input_end": 0,
  "seed": 0,
  "rows_input": 0,
  "rows_output": 0,
  "sha256": "",
  "schema_version": "",
  "started_at": "",
  "completed_at": "",
  "duration_seconds": 0,
  "peak_memory_mb": 0,
  "peak_disk_mb": 0,
  "locked_opened": false,
  "locked_rows_accessed": 0,
  "validation_used_for_selection": false,
  "status": "success",
  "error_class": null
}
```

## 29. Formatos

| Uso | Formato |
|---|---|
| Datos tabulares | Parquet |
| Registros variables | JSONL comprimido |
| Estado/manifest | JSON |
| Tabla humana final | CSV |
| Informe | Markdown |

CSV no se usa como shard crítico.

Reglas de rendimiento:

- Proyección de columnas y filtros de Parquet obligatorios cuando aplican.
- Parquet o archivos ya comprimidos usan `artifact compression-level: 0`.
- Texto grande usa nivel 1 por defecto.
- Niveles superiores requieren evidencia del piloto.
- No generar CSV masivo si no es un requisito contractual explícito.
- Una sola pasada completa debe alimentar todas las salidas que puedan escribirse
  simultáneamente.

## 30. Verificación previa al upload

- Archivo existe.
- Tamaño mayor que cero.
- Parser puede abrirlo.
- Schema correcto.
- Filas coinciden con manifest.
- Hash calculado.
- No contiene secretos.
- Nombre único.
- Ruta exacta.

`upload-artifact` debe fallar si no encuentra archivos.

## 31. Retención

- Shards: retención corta pero suficiente para recuperación.
- Final: retención según valor.
- Datos sensibles o licenciados: almacenamiento privado, no artifact público.
- Registrar `expires_at`.
- Nunca borrar un run antes de copiar resultados necesarios: borrar el run borra sus artifacts.

## 32. Cache

La caché acelera, no es fuente de verdad.

- Clave incluye lockfile, SO y versión.
- Verificar contenido tras restaurar.
- Un cache miss no puede romper el run.
- Un cache corrupto se descarta.
- No guardar resultados finales sólo en cache.
- No mezclar cache entre campañas incompatibles.

---

# PARTE X. MERGE A PRUEBA DE FALLOS

## 33. Algoritmo

1. Leer `campaign_manifest`.
2. Enumerar artifacts disponibles.
3. Comparar expected/found.
4. Descargar por lotes.
5. Verificar manifest y hash.
6. Validar schema.
7. Elegir fan-in y niveles desde `merge_plan.json`.
8. Ejecutar merges parciales en paralelo cuando el volumen lo exija.
9. Leer incrementalmente con proyección de columnas.
10. Detectar duplicados.
11. Deduplicar por ID estable.
12. Conservar merges parciales válidos.
13. Generar parcial separado.
14. Generar final sólo si completo.
15. Verificar outputs finales.

## 34. Summary mínimo

```json
{
  "campaign_id": "",
  "code_sha": "",
  "spec_hash": "",
  "data_snapshot_hash": "",
  "expected_jobs": 0,
  "found_jobs": 0,
  "successful_jobs": 0,
  "failed_jobs": 0,
  "missing_ids": [],
  "duplicate_ids": [],
  "rows_before_dedup": 0,
  "rows_after_dedup": 0,
  "accepted_count": 0,
  "partial": false,
  "complete": true,
  "locked_opened": false,
  "locked_rows_accessed": 0,
  "validation_used_for_selection": false,
  "max_parallel_requested": 0,
  "max_parallel_observed": 0,
  "average_parallel_observed": 0,
  "technical_failure_count": 0,
  "critical_path_seconds": 0,
  "billable_minutes": 0,
  "units_per_critical_path_minute": 0,
  "straggler_ratio": 0,
  "performance_bottleneck": "",
  "performance_contract_passed": false
}
```

## 34.1 Ledger de reconciliación obligatorio

Toda unidad de entrada termina exactamente en uno de estos estados:

```text
completed
right_censored
unsupported
failed_technical
```

Se pueden añadir subestados, pero no reemplazar estos cuatro estados terminales.
Debe cumplirse globalmente y por shard, ola, periodo y combinación:

```text
expected_units =
  completed
  + right_censored
  + unsupported
  + failed_technical
```

Reglas:

- Ninguna fila se elimina silenciosamente.
- `right_censored` no se convierte en salida temporal ni en fallo.
- `unsupported` exige motivo determinista y evidencia.
- `failed_technical` nunca cuenta como resultado científico negativo.
- Cero filas sólo es válido si el contrato lo declaró previamente.
- El ledger completo se publica en `unit_reconciliation.parquet`.
- El resumen incluye la reconciliación global y por cada dimensión contractual.

## 35. Fallos duros

No hay final si:

- expected distinto de found;
- hash incorrecto;
- schema distinto;
- cero filas cuando se esperan filas;
- output obligatorio ausente;
- duplicado no justificable;
- locked abierto;
- validación usada;
- secreto detectado;
- versión de código o datos mezclada;
- error técnico sin clasificar.

---

# PARTE XI. REINTENTOS Y RECUPERACIÓN

## 36. Clases de error

| Clase | Reintento | Acción |
|---|---:|---|
| `transient_network` | Sí, limitado | Backoff + jitter |
| `github_5xx` | Sí, limitado | Esperar y reintentar |
| `provider_429` | Sí | Respetar Retry-After |
| `runner_lost` | Sí | Relanzar shard |
| `artifact_upload_transient` | Sí | Reintentar upload |
| `out_of_memory` | No idéntico | Reducir tamaño del shard |
| `disk_full` | No idéntico | Reducir outputs/limpiar temporal |
| `schema_mismatch` | No | Corregir adaptador |
| `invalid_config` | No | Corregir spec |
| `auth_permission` | No | Corregir permisos |
| `data_policy_violation` | No | Bloquear campaña |
| `locked_violation` | No | Invalidar campaña |
| `empty_result_expected` | No | Resultado negativo válido |
| `empty_result_unexpected` | No | Fallo técnico |
| `user_cancelled` | No | Conservar parciales |

## 37. Política

- Máximo de reintentos definido por clase.
- Backoff exponencial con jitter.
- Reintento sólo de operación idempotente.
- El contador persiste.
- Tras agotar reintentos: `FAILED_TECHNICAL` o `BLOCKED_EXTERNAL`.
- Nunca crear un bucle infinito.

## 38. Recuperación selectiva

Generar:

```text
resume_manifest.json
missing_shards.csv
failed_shards.csv
completed_shards.csv
```

Un workflow `resume` acepta exactamente los IDs pendientes.

Cada reintento conserva el mismo `unit_key`, incrementa `attempt_number` y genera
un `attempt_id` nuevo. Sólo un intento que supere hash, schema y políticas puede
ser elegido. Los intentos descartados se conservan en el audit y no se mezclan.

## 39. Merge-only

Si falla merge:

- no repetir datos;
- no repetir búsqueda;
- usar artifacts del run original;
- fijar `source_run_id`;
- verificar hashes;
- producir un nuevo artifact final con procedencia.

---

# PARTE XII. MONITORIZACIÓN Y OPERACIÓN

## 40. Registro inicial

| Campo | Valor |
|---|---|
| Run ID | |
| URL | |
| Workflow ID | |
| Rama | |
| SHA | |
| Actor | |
| Hora UTC | |
| Inputs | |

## 41. Estado real

No mirar sólo el estado global. Contar:

- queued;
- waiting;
- in progress;
- completed success;
- failed;
- cancelled;
- skipped;
- artifacts;
- shards verificados;
- filas;
- ola;
- ETA.

## 42. Paralelismo

Calcular con intervalos `started_at/completed_at` de jobs:

- solicitado;
- pico observado;
- promedio observado;
- distribución por tiempo.

No inferirlo desde el orden de artifacts.

## 43. Watchdog

Alertas:

- data falla;
- un job verde no produce artifact;
- cero progreso durante 10 minutos;
- p95 supera piloto en 50%;
- RAM/disco críticos;
- error rate supera umbral;
- cola impide deadline;
- aparecen duplicados;
- partial cambia a true;
- merge sin progreso;
- estado de GitHub degradado;
- presupuesto agotándose;
- policy audit cambia.

El watchdog informa, pero no relanza indiscriminadamente.

## 44. GitHub o proveedor caído

1. Consultar estado oficial.
2. No modificar código para “arreglar” una caída externa.
3. Marcar `BLOCKED_EXTERNAL`.
4. Conservar state.
5. Reanudar cuando se recupere.

## 45. Debug

Activar debug sólo cuando sea necesario:

- logs del runner;
- logs del step;
- rerun del job fallido;
- descarga del archivo completo de logs.

No dejar debug permanente si puede exponer datos sensibles.

---

# PARTE XIII. CANCELACIÓN

## 46. Cancelación solicitada

1. Marcar `PAUSING`.
2. Impedir nuevas olas.
3. Permitir sólo checkpoint y subida de parciales.
4. Cancelar jobs.
5. Forzar cancelación si `always()` la bloquea.
6. Inventariar artifacts conservados.
7. Escribir `CANCELLED_BY_USER`.
8. Indicar cómo reanudar.

Nunca confundir cancelación solicitada con fallo técnico.

## 47. Apagado inesperado

El PC local no forma parte del run. El estado reside en GitHub/artifacts/storage. Ningún encadenamiento nocturno depende de Codex abierto.

---

# PARTE XIV. ESCENARIOS POR TIPO DE RUN

## 48. Búsqueda u optimización

- Presupuesto igual entre métodos.
- Mismos datos, features, fechas y costes.
- Contar evaluadas y únicas.
- `candidate_id` independiente de wave/shard.
- Semillas independientes y registradas.
- `n_trials` global, no sólo por shard.
- El cap de candidatas no puede terminar jobs prematuramente sin estar declarado.
- Validación no retroalimenta siguientes olas.
- No repetir familias disfrazadas de nuevas.

## 49. Backtest

- Señal y ejecución separadas.
- Lag causal.
- Posición exacta por fecha.
- Retornos ajustados/no ajustados coherentes.
- Costes y slippage.
- NAV nunca oculto.
- Métricas verificadas contra una implementación de referencia.
- Periodos y subperiodos.
- Benchmark con misma frecuencia.
- Locked separado.
- Definición exacta de señal, hora de decisión y primera ejecución posible.
- Purga y embargo cuando etiquetas, posiciones o retornos objetivo se solapan.
- Política explícita para dividendos, splits, delistings, FX, cash y borrow.
- Métricas contrastadas con una implementación de referencia independiente.

## 49.1 Contrato de métricas

Antes de producción se congelan fórmula, unidad y casos límite de cada métrica:

- tipo de retorno: simple o logarítmico;
- retorno total o retorno de precio;
- frecuencia y factor de anualización;
- tasa libre de riesgo y su alineación temporal;
- Sharpe y tratamiento de volatilidad cero;
- CAGR y periodos incompletos;
- max drawdown y convención pico-valle;
- Calmar y ventana;
- profit factor y definición de operación;
- win rate por trade, día, semana, mes o año;
- exposición y tiempo en mercado;
- costes, slippage, financiación, FX y borrow;
- nulos, infinitos, muestras insuficientes y métricas no definidas.

El archivo `metric_contract.json` contiene las fórmulas/versiones. Cambiar una
definición crea una nueva versión de campaña.

## 49.2 Purga, embargo y selección

- La duración máxima de la etiqueta o posición determina la purga mínima.
- El embargo se declara en sesiones o tiempo natural.
- Ningún fold puede compartir información futura o retornos solapados con otro.
- La política de selección, desempates y filtros se congela en
  `selection_policy.json` antes de calcular validación.
- Validación sólo genera diagnóstico y no puede modificar esa política.
- El audit publica intervalos purgados, embargo aplicado y cualquier exclusión.

## 50. Robustez

- Misma serie de retornos que el backtest.
- `n_trials` global.
- Bootstrap con semilla.
- Bloques adecuados a frecuencia.
- P-values y corrección múltiple.
- Resultados no disponibles se marcan, no se dan por fallidos automáticamente.
- Rerun sólo de candidatos/shards faltantes.

## 50.1 Contrato estadístico

Toda búsqueda, optimización o comparación múltiple declara antes del fan-out:

- familia de hipótesis;
- hipótesis nula y alternativa;
- `n_trials` global real;
- pruebas funcionalmente duplicadas;
- nivel alfa;
- corrección múltiple elegida;
- método y número de muestras bootstrap;
- longitud y construcción de bloques;
- semillas estadísticas;
- Deflated Sharpe, Probabilistic Sharpe y PBO cuando sean aplicables;
- política para resultados no disponibles;
- tamaño mínimo de muestra;
- intervalos de confianza;
- criterio de robustez blando y duro.

`n_trials` nunca se calcula sólo con el shard ni sólo con los supervivientes. El
archivo `statistical_contract.json` queda congelado antes de ver validación.

## 51. Literatura/PDF

- DOI, study_id y URL deduplicados.
- Validar PDF real.
- Límite de tamaño y timeout.
- Paywall separado de fallo técnico.
- PDF temporal borrado tras extracción.
- OCR separado.
- Texto y claims con evidencia.
- No subir material licenciado a artifacts públicos.
- Réplica exacta sólo con campos mínimos.
- Paper no operable queda unsupported.

## 52. Descarga masiva

- Reanudable.
- Catálogo de progreso.
- Rate limit.
- Hash por archivo.
- Raw inmutable.
- Clean versionado.
- No sobrescribir una descarga previa sin versión.
- Validación por lotes.
- Sync privado.
- Presupuesto de disco.

## 53. Campaña nocturna

- Deadline en zona `Europe/Madrid` y UTC.
- Considerar horario de verano.
- No iniciar ronda que no pueda terminar antes del cierre.
- State tras cada ronda.
- Merge final con tiempo reservado.
- Una ronda fallida no bloquea las demás si son independientes.
- Encadenamiento probado antes.
- No depender de heartbeat local.

## 54. Locked

Locked no forma parte de un run normal.

Requiere:

- orden explícita del usuario;
- workflow manual separado;
- ledger de selección previa;
- lista cerrada de candidatos;
- SHA y snapshot congelados;
- una única ceremonia;
- prohibición de ajustar después de verlo.

---

# PARTE XV. MATRIZ DE ESCENARIOS

## 55. Infraestructura

| Escenario | Detección | Respuesta |
|---|---|---|
| GitHub Actions degradado | GitHub Status/API | Pausar y reanudar |
| Runner no asignado | Job queued sin start | Recalcular ETA, no tocar código |
| Runner perdido | Job failure específico | Relanzar shard |
| Límite de concurrencia | Intervalos de jobs | Redimensionar |
| Billing bloqueado | Mensaje de billing | Bloquear y avisar |
| Minutos agotados | Usage API | Bloquear y avisar |
| Storage agotado | Usage/artifact error | Limpiar según retención |
| Job timeout | Conclusion timed_out | Checkpoint y shard más pequeño |
| Cancelación no termina | Jobs siguen por conditions | Force cancel |
| API rate limit | Headers/API | Backoff |
| Default branch incorrecta | Workflow no visible | Registrar YAML |
| Workflow deshabilitado | API workflow state | Habilitar explícitamente |
| Repo/owner renombrado | 404/redirección | Actualizar referencias |

## 56. Código y entorno

| Escenario | Detección | Respuesta |
|---|---|---|
| Script ausente | Preflight | No lanzar |
| Config ausente | Preflight | No lanzar |
| Import roto | Compile/import test | No lanzar |
| Python distinto | Runtime audit | Fijar versión |
| SO distinto | Runtime audit | Fijar imagen |
| Dependencia nueva | Lock hash | Nueva versión |
| Paquete retirado | Install failure | Mirror/versión aprobada |
| Acción mutada | SHA distinto | Bloquear |
| Ruta Windows en Linux | Static check | Corregir runtime_paths |
| Trabajo local accidental | Guard | Bloquear |
| Árbol/branch incorrecto | SHA audit | Bloquear |

## 57. Datos

| Escenario | Detección | Respuesta |
|---|---|---|
| Dataset vacío | Row count | Fallar |
| Huecos | Coverage | Rechazar o declarar |
| Duplicados | Unique key | Fallar |
| Fecha futura | Max date | Fallar |
| Zona horaria errónea | Calendar audit | Corregir |
| Schema cambiado | Schema hash | Versionar |
| Revisiones históricas | Snapshot hash | Nuevo snapshot |
| Survivorship | Universe audit | Fallar |
| Ajustes incoherentes | Split audit | Fallar |
| Provider truncado | Expected count/hash | Reintentar |
| Datos sin licencia | Source audit | Bloquear |

## 58. Shards y merge

| Escenario | Detección | Respuesta |
|---|---|---|
| Job verde sin archivo | Verify output | Fallar job |
| Artifact vacío | Size/parser | Fallar |
| Artifact corrupto | Hash/parser | Relanzar shard |
| Artifact duplicado | unit_key | Deduplicar y avisar |
| Nombre colisiona | Manifest | Fallar |
| Descarga incompleta | Expected/found | Parcial |
| Merge OOM | Telemetría | Merge incremental |
| Merge timeout | Progreso/ETA | Checkpoint y merge-only |
| Cero filas | Contract | Fallar o negativo declarado |
| Parcial falso | Manifest | Fallar |
| Schema mezclado | Schema version | Bloquear |
| SHAs mezclados | Provenance | Bloquear |
| Estado sin reconciliar | Ledger contractual | Bloquear |
| Censurado tratado como salida | Audit de estados | Invalidar |

## 59. Seguridad

| Escenario | Detección | Respuesta |
|---|---|---|
| Secreto en log | Secret scan | Cancelar y rotar |
| Token con exceso de permisos | Permissions audit | Reducir |
| Acción de tercero comprometida | SHA/allowlist | Bloquear |
| Input inyectable | Static check | Sanitizar |
| Código externo móvil | Ref audit | Fijar SHA |
| Artifact público sensible | Content/license audit | Mover a privado |
| Checkout conserva token | Workflow audit | persist false |
| Fork no confiable | Event audit | Sin secretos |

## 60. Metodología

| Escenario | Detección | Respuesta |
|---|---|---|
| Validación selecciona | Policy audit | Invalidar |
| Locked leído | Ledger | Invalidar |
| Lookahead | Lag audit | Invalidar |
| Proxy débil | Correlation audit | Rechazar |
| Costes cero no autorizados | Config audit | Rechazar |
| Parámetro elegido tras ver OOS | Lineage audit | Invalidar |
| Paper proxy vendido como exacto | Fidelity audit | Reclasificar |
| Método recibe menos presupuesto | Fairness audit | Invalidar comparación |

---

# PARTE XVI. CHECKLIST DE AUTORIZACIÓN

El fan-out completo sólo se autoriza si todos son `PASS`.

## Identidad

- [ ] Campaign ID único.
- [ ] SHA congelado.
- [ ] Spec hash calculado.
- [ ] Workflow visible.
- [ ] Rama correcta.

## Gobierno

- [ ] Main protegido.
- [ ] Actions por SHA.
- [ ] Permisos mínimos.
- [ ] Sin triggers de push pesados.
- [ ] Concurrency revisada.

## Política

- [ ] Locked cerrado.
- [ ] Cero filas locked.
- [ ] Validación report-only.
- [ ] Lag causal.
- [ ] Proxies auditados.

## Datos

- [ ] Snapshot inmutable.
- [ ] Hash.
- [ ] Coverage.
- [ ] Schema.
- [ ] Calidad.
- [ ] Survivorship.
- [ ] Licencia.

## Entorno

- [ ] Python fijo.
- [ ] Dependencias locked.
- [ ] Runner fijado.
- [ ] Rutas portables.
- [ ] Sin ejecución local.

## Diseño

- [ ] Matrices menores o iguales a 256.
- [ ] Duración con p95.
- [ ] RAM y disco proyectados.
- [ ] Artifact proyectado.
- [ ] Coste dentro de presupuesto.

## Eficiencia

- [ ] Capacidad GitHub real comprobada.
- [ ] Datos y features comunes preparados una sola vez.
- [ ] Plan de shards equilibrado por coste.
- [ ] Tiempo de setup dentro del umbral.
- [ ] Threads adaptados a la CPU real.
- [ ] Compresión elegida mediante piloto.
- [ ] Sin lecturas completas repetidas evitables.
- [ ] Merge jerárquico dimensionado.
- [ ] Ruta crítica y paralelismo medidos.
- [ ] Bottleneck report generado.

## Recuperación

- [ ] Idempotencia.
- [ ] State durable.
- [ ] Missing IDs.
- [ ] Resume workflow.
- [ ] Merge-only.
- [ ] Cancelación limpia.

## Pruebas

- [ ] Preflight PASS.
- [ ] Smoke PASS.
- [ ] Piloto PASS.
- [ ] Fallo simulado recuperado.
- [ ] Artifact final del smoke verificado.
- [ ] Ledger terminal reconciliado.
- [ ] Purga y embargo comprobados cuando aplican.
- [ ] Métricas contrastadas contra referencia independiente.
- [ ] Manifest final y verifier comprobados.
- [ ] Matriz requisito-evidencia completa.

## Ejecución

- [ ] No hay run duplicado.
- [ ] Run ID registrado.
- [ ] Primer shard produce archivo válido.
- [ ] Paralelismo real medido.
- [ ] Watchdog activo.

## Cierre

- [ ] Todos los shards contabilizados.
- [ ] Partial false.
- [ ] Complete true.
- [ ] Cero fallos técnicos.
- [ ] Summary legible.
- [ ] Artifact final verificado.
- [ ] Monitores temporales eliminados.
- [ ] Performance contract aprobado.
- [ ] Ruta crítica y minutos facturables registrados.
- [ ] Cuello de botella final explicado.

---

# PARTE XVII. PLANTILLA DE ESPECIFICACIÓN

```yaml
schema_version: "3.0"

identity:
  campaign_id: ""
  run_type: ""
  repo: "trading-optimizer-lab-org/aurora"
  code_ref: ""
  code_sha: ""
  workflow: ""
  workflow_sha256: ""
  deadline_utc: ""

objective:
  description: ""
  success_criteria: []
  negative_result_criteria: []
  technical_failure_criteria: []

policy:
  policy_hash: ""
  train_start: ""
  train_end: ""
  validation_start: ""
  validation_end: ""
  locked_start: ""
  locked_opened: false
  locked_rows_allowed: 0
  validation_used_for_selection: false
  causal_lag_minimum: 1
  decision_timezone: ""
  decision_timestamp_rule: ""
  execution_timestamp_rule: ""
  market_calendar: ""
  purging_periods: 0
  embargo_periods: 0

data:
  manifest: ""
  manifest_sha256: ""
  snapshot_hash: ""
  schema_version: ""
  max_date: ""
  required_datasets: []
  total_return_policy: ""
  corporate_actions_policy: ""
  delisting_policy: ""
  fx_policy: ""
  cash_yield_policy: ""

execution:
  github_only: true
  execution_location: "github_actions"
  local_runs_allowed: false
  requires_explicit_user_local_permission: true
  waves: 1
  jobs_per_wave: 1
  matrices_per_wave: 1
  max_matrix_jobs: 256
  requested_parallelism: 1
  conservative_parallelism: 1
  internal_minutes_per_job: 1
  job_timeout_minutes: 2
  merge_timeout_minutes: 15
  fail_fast: false
  global_seed: 0
  shard_seed_formula: ""
  timezone: "UTC"
  locale: "C.UTF-8"
  python_version: ""
  dependency_lock_sha256: ""
  runner_image: ""

resources:
  max_billable_minutes: 0
  max_cost: 0
  max_artifact_gb: 0
  min_free_disk_gb: 5
  max_memory_pct: 80
  max_peak_temporary_disk_gb: 0
  atomic_rewrite_multiplier: 1.0

performance:
  optimize_for: "wall_clock"
  capacity_profile_path: "config/github_capacity_profile.json"
  confirmed_standard_concurrency: 360
  concurrency_confirmation_source: "github_support"
  reserve_concurrency: 0
  capacity_probe_required: false
  planner_selects_job_count: true
  planner_min_jobs: 1
  planner_max_jobs: 360
  planner_job_count_search: "adaptive_exact"
  planner_large_unit_threshold: 50000
  planner_exact_lpt_candidates_max: 3
  matrix_max_jobs: 256
  auto_split_matrices: true
  runner_label: "ubuntu-24.04"
  detect_runner_resources: true
  record_runner_image_metadata: true

  reuse_valid_gates: true
  prepare_data_once: true
  precompute_common_features_once: true
  distribute_only_required_partitions: true
  transport_mode: "auto"
  artifact_granularity: "coarse_partition"
  forbid_partial_download_claim_for_monolithic_artifact: true

  shard_planning: "weighted_lpt"
  work_unit_manifest_format: "parquet"
  shard_assignment_format: "parquet"
  matrix_descriptors_only: true
  max_github_output_kb: 256
  target_setup_fraction_max: 0.10
  target_checkpoint_fraction_max: 0.03
  target_straggler_ratio_max: 1.50
  adaptive_batch_size: true
  adaptive_threads: true
  adaptive_shard_size: true
  forbid_nested_process_pools: true
  pin_numeric_library_threads: true

  parquet_projection: true
  parquet_predicate_pushdown: true
  forbid_repeated_full_scans: true
  forbid_large_csv_intermediates: true

  artifact_compression_precompressed: 0
  artifact_compression_text: 1
  cache_single_writer: true

  hierarchical_merge: true
  merge_fan_in: 30
  merge_incremental: true
  preserve_partial_merges: true

  larger_runners_allowed: false
  native_acceleration_allowed_after_profile: true
  native_hot_path_min_fraction: 0.10
  native_projected_end_to_end_gain_min: 0.05
  native_python_fallback_required: true

  engine_candidates:
    - "python_reference"
    - "numpy"
    - "numba"
    - "pyarrow"
    - "duckdb"
    - "threads"
    - "processes"
  require_engine_equivalence_before_timing: true

  record_queue_time: true
  record_parallelism_timeline: true
  record_phase_breakdown: true
  generate_bottleneck_report: true

retries:
  transient_network: 3
  github_5xx: 3
  provider_429: 5
  artifact_upload: 3
  runner_lost: 2

artifacts:
  shard_format: "parquet"
  final_name: ""
  retention_days_shards: 7
  retention_days_final: 30
  if_no_files_found: "error"
  require_final_artifact_manifest: true
  require_requirement_traceability: true
  require_final_verification_report: true

security:
  default_permissions: "contents:read"
  actions_pinned_by_sha: true
  checkout_persist_credentials: false
  external_code_allowlist: []
  pinned_actions:
    checkout: ""
    setup_python: ""
    upload_artifact: ""
    download_artifact: ""

statistics:
  hypothesis_family: ""
  null_hypothesis: ""
  alternative_hypothesis: ""
  n_trials_global: 0
  alpha: 0.05
  multiple_testing_correction: ""
  bootstrap_method: ""
  bootstrap_samples: 0
  bootstrap_block_length: 0
  statistical_seed: 0
  minimum_sample_size: 0

metrics:
  contract_path: ""
  contract_sha256: ""
  return_type: ""
  return_basis: ""
  annualization_rule: ""
  risk_free_source: ""
  undefined_metric_policy: ""

reconciliation:
  required_terminal_states:
    - completed
    - right_censored
    - unsupported
    - failed_technical
  require_expected_equals_terminal_sum: true
  forbid_silent_row_drops: true

gates:
  require_preflight: true
  require_smoke: true
  require_pilot: true
  require_complete_merge: true
  require_policy_audit: true
  require_reconciliation: true
  require_independent_metric_reference: true
  require_final_verifier: true
  require_traceability_matrix: true
```

Los campos derivados del runtime pueden quedar vacíos en esta plantilla
rellenable. GitHub genera primero `requested_run_spec.yaml`, verifica el commit
y el workflow reales, prepara entorno y datos una sola vez, y congela
`resolved_run_spec.json` antes del smoke. Desde ese momento, todos los shards,
reintentos y merges usan exactamente su mismo hash.

---

# PARTE XVIII. BLOQUE PARA PEDIR UN RUN

```text
Diseña y ejecuta este trabajo exclusivamente en GitHub Actions usando:

C:\Users\HP\Desktop\PLANTILLA_MAESTRA_RUN_GITHUB_AURORA.md

OBJETIVO:


REQUISITOS ESPECÍFICOS:


DATOS Y PERIODOS:


PRESUPUESTO Y DEADLINE:


No lances producción directamente.

Orden obligatorio:
1. completar spec;
2. validar estáticamente;
3. smoke GitHub;
4. piloto GitHub;
5. generar el plan de rendimiento con p95 y paralelismo observado;
6. recalcular presupuesto y ruta crítica;
7. producción con fan-out equilibrado;
8. recuperación selectiva;
9. merge jerárquico completo;
10. auditoría final de resultados y rendimiento.

No declares éxito si hay cero filas inesperadas, artifacts ausentes, partial=true,
locked abierto, validación usada para seleccionar o cualquier fallo técnico sin resolver.
```

---

# PARTE XIX. INFORME DE INCIDENTE

```text
INCIDENT_ID:
CAMPAIGN_ID:
RUN_ID:
WORKFLOW:
SHA:
FECHA UTC:

SÍNTOMA:

IMPACTO:

CLASE DE ERROR:

CAUSA INMEDIATA:

CAUSA RAÍZ:

QUÉ NO FUE LA CAUSA:

TRABAJO CONSERVADO:

TRABAJO PERDIDO:

SOLUCIÓN:

RELANZAMIENTO:

RESULTADO:

CONTROL PREVENTIVO:

TEST AÑADIDO:

EVIDENCIA:
```

La incidencia no se cierra hasta añadir una prevención comprobable.

---

# PARTE XX. FUENTES Y REVISIÓN

Revisado el 25 de julio de 2026.

Fuentes oficiales que deben volver a comprobarse cuando cambien los límites:

- [GitHub Actions limits](https://docs.github.com/actions/reference/limits)
- [Workflow syntax](https://docs.github.com/actions/reference/workflows-and-actions/workflow-syntax)
- [Concurrency](https://docs.github.com/actions/concepts/workflows-and-actions/concurrency)
- [Troubleshooting workflows](https://docs.github.com/actions/how-tos/troubleshoot-workflows)
- [Secure use reference](https://docs.github.com/actions/reference/security/secure-use)
- [Workflow artifacts](https://docs.github.com/actions/concepts/workflows-and-actions/workflow-artifacts)
- [Store and share workflow artifacts](https://docs.github.com/actions/configuring-and-managing-workflows/persisting-workflow-data-using-artifacts)
- [Re-running workflows and jobs](https://docs.github.com/actions/how-tos/manage-workflow-runs/re-run-workflows-and-jobs)
- [Enabling debug logging](https://docs.github.com/actions/how-tos/monitor-workflows/enable-debug-logging)
- [GitHub-hosted runners reference](https://docs.github.com/actions/reference/runners/github-hosted-runners)
- [Dependency caching reference](https://docs.github.com/actions/reference/workflows-and-actions/dependency-caching)
- [Larger runners](https://docs.github.com/actions/concepts/runners/larger-runners)
- [Upload artifact performance and compression](https://github.com/actions/upload-artifact)

---

# PARTE XXI. REPRODUCIBILIDAD Y CIERRE PROBATORIO

## 61. Determinismo completo

El manifest congela:

- semilla global;
- fórmula de semilla por unidad;
- semillas de Python, NumPy, ML, bootstrap y optimizador;
- versión exacta de Python;
- hash del lockfile o constraints;
- imagen del runner;
- sistema operativo y arquitectura;
- locale y zona horaria;
- variables de threading;
- número de threads BLAS/OpenMP;
- versiones de librerías numéricas;
- orden estable de inputs;
- política de timestamps y metadatos no deterministas.

Los datos científicos y los metadatos temporales se guardan separados. Dos
ejecuciones con el mismo contrato deben producir los mismos hashes científicos.
Si una dependencia no garantiza determinismo, se declara y se mide la tolerancia
permitida antes de producción.

## 62. Manifest final y verificador independiente

El artifact final incluye `final_artifact_manifest.json` con una entrada por
archivo:

```json
{
  "relative_path": "",
  "sha256": "",
  "bytes": 0,
  "rows": 0,
  "columns": [],
  "schema_version": "",
  "content_role": ""
}
```

También incluye:

- `final_verification_report.json`;
- SHA del código que generó resultados;
- SHA del verificador;
- run ID y job ID;
- source run ID para recuperaciones;
- artifact ID, nombre, digest y expiración;
- número de tests y resultado;
- reconciliación completa;
- lista explícita de limitaciones.

El verificador:

- se ejecuta después de construir el artifact y antes de subirlo;
- lee los archivos reales, no sólo el summary;
- comprueba hashes, tamaños, schemas, filas, claves y estados;
- verifica locked, validación, causalidad y reconciliación;
- no comparte la misma función que genera aquello que valida cuando exista una
  implementación de referencia razonable;
- termina con código distinto de cero ante cualquier incumplimiento.

Un workflow verde sin `final_verification_report.verdict=pass` no se considera
campaña completada.

## 63. Matriz requisito-evidencia

Cada campaña genera `requirements_traceability.csv` con:

| Campo | Significado |
|---|---|
| `requirement_id` | ID único del requisito |
| `requirement_text` | Regla comprobada |
| `mandatory` | Si bloquea el cierre |
| `verdict` | `pass`, `fail`, `not_applicable` |
| `evidence_file` | Archivo que lo demuestra |
| `evidence_field` | Campo, columna o test |
| `evidence_value` | Valor observado |
| `verifier_check` | Comprobación ejecutada |
| `notes` | Limitación o explicación |

Reglas:

- Todo requisito obligatorio aparece una vez.
- `not_applicable` exige justificación.
- Una evidencia no encontrada equivale a `fail`.
- La matriz se genera desde el spec congelado, no desde una lista manual posterior.
- El verificador exige que todos los requisitos obligatorios terminen en `pass`.

## 64. Cierre formal de campaña

Una campaña sólo llega a `COMPLETED` cuando:

1. todos los tests contractuales han pasado;
2. el ledger reconcilia;
3. todos los shards están contabilizados;
4. el manifest final coincide con los archivos;
5. el verifier termina en `pass`;
6. la matriz requisito-evidencia no tiene fallos obligatorios;
7. `partial=false` y `complete=true`;
8. locked y validación cumplen la política;
9. presupuesto planificado y real quedan registrados;
10. artifact final y review artifact existen y tienen digest;
11. el review artifact se descarga y se inspecciona;
12. se registra una conclusión científica o un resultado negativo válido;
13. se eliminan monitores y autostarts temporales.

El cierre produce `campaign_closure.json`:

```json
{
  "campaign_id": "",
  "final_state": "COMPLETED",
  "run_ids": [],
  "code_sha": "",
  "spec_hash": "",
  "data_snapshot_hash": "",
  "final_artifact_id": "",
  "final_artifact_digest": "",
  "review_artifact_id": "",
  "verifier_verdict": "pass",
  "mandatory_requirements_passed": 0,
  "mandatory_requirements_failed": 0,
  "expected_units": 0,
  "terminal_units": 0,
  "partial": false,
  "complete": true,
  "locked_opened": false,
  "locked_rows_accessed": 0,
  "validation_used_for_selection": false,
  "planned_cost": 0,
  "actual_cost": 0,
  "closed_at": ""
}
```

No se declara éxito sólo porque GitHub muestre un check verde.

---

# PARTE XXII. EFICIENCIA Y VELOCIDAD EN GITHUB ACTIONS

## 65. Alcance

Toda carga de trabajo se ejecuta en GitHub Actions. Las decisiones de rendimiento
se toman con mediciones obtenidas en GitHub, nunca con benchmarks del PC local.

La optimización de rendimiento no puede:

- reducir cobertura sin declararlo;
- eliminar auditorías;
- saltarse puertas;
- perder filas o censurados;
- capar candidatas silenciosamente;
- cambiar la metodología cuantitativa;
- usar validación para adaptar la búsqueda;
- relajar locked, causalidad, hashes o reconciliación.

Primero se demuestra que el resultado es válido. Después se minimiza su ruta
crítica sin cambiar el significado científico.

## 66. Objetivo de rendimiento

Cada campaña elige una prioridad:

```text
wall_clock
billable_minutes
balanced
```

Por defecto Aurora usa `wall_clock` con runners estándar. El contrato registra:

- deadline;
- coste máximo;
- tiempo máximo de pared;
- minutos facturables máximos;
- capacidad reservada para otros workflows;
- criterio para aceptar una alternativa más cara.

La métrica principal es:

```text
scientific_units_completed / critical_path_minute
```

También se mide:

```text
scientific_units_completed / billable_minute
```

## 67. Perfil de capacidad real

GitHub no ofrece a cada workflow una API fiable que indique cuántos slots
estándar de la organización estarán libres al iniciar el fan-out. El preflight no
puede fingir que conoce ese dato.

El sistema usa `github_capacity_profile.json`, que registra:

- plan y visibilidad del repositorio;
- concurrencia estándar concedida por soporte;
- fecha y evidencia de esa concesión;
- capacidad nominal del runner;
- límite de matriz;
- presupuesto de cache y artifacts;
- límites oficiales vigentes;
- última prueba explícita de capacidad;
- paralelismo máximo observado en campañas recientes.

Para esta organización, la referencia es 360 jobs estándar concurrentes,
confirmados por GitHub Support. El valor es un techo, no una obligación.

```text
requested_parallelism =
  min(profile_concurrency_ceiling, planner_optimal_jobs)
  - reserved_concurrency
```

Un capacity probe separado actualiza el perfil cuando GitHub Support, el plan o
la configuración cambian. No se lanzan 360 jobs vacíos antes de cada campaña.

Durante el run se registra cola y paralelismo observado. Una menor concurrencia
observada puede ser contención temporal y no demuestra por sí sola que GitHub
haya reducido el límite.

## 68. Arquitectura de la ruta crítica

```text
preflight reutilizable
→ prepare_data_once
→ smoke
→ piloto representativo
→ performance planner
→ fan-out equilibrado
→ merge jerárquico
→ verifier
→ artifacts finales
```

El planner produce un DAG y calcula su ruta crítica. Las etapas independientes se
ejecutan en paralelo. Las dependencias artificiales se consideran un fallo de
diseño.

Preflight, smoke y piloto pueden reutilizarse únicamente si coinciden:

- code SHA;
- spec hash;
- snapshot hash;
- workflow hash;
- lockfile hash;
- runner contract;
- policy hash.

## 69. Datos preparados una sola vez

Un único trabajo prepara:

- descarga;
- normalización;
- calendario;
- features comunes;
- particiones;
- snapshot;
- hashes;
- manifest.

Cada shard recibe sólo:

- columnas requeridas;
- símbolos requeridos;
- fechas requeridas;
- particiones requeridas.

Prohibido:

- descargar el dataset completo en cada job si puede particionarse;
- recalcular features comunes por candidata;
- guardar el mismo snapshot dentro de cada artifact;
- usar el cache como única copia del snapshot.

Para datasets grandes se usa almacenamiento privado con objetos inmutables y
descarga por partición o rango. Artifacts se reservan para resultados y handoffs
de tamaño razonable.

GitHub descarga un artifact completo: no permite pedir sólo un fichero o rango
interno. Por tanto, el transporte se decide así:

- input pequeño: un artifact inmutable;
- input mediano: pocos artifacts de partición, cada uno con varios ficheros;
- input grande: backend de snapshots u object storage ya configurado;
- sin backend externo: bloquear o rediseñar particiones antes del fan-out.

Nunca declarar “descarga selectiva” desde un artifact monolítico.

## 70. Entorno de ejecución

El piloto compara cuando sea pertinente:

- instalación normal con lockfile;
- caché del gestor de paquetes;
- wheelhouse congelado;
- contenedor o imagen preconstruida autorizada.

Se elige la opción con menor ruta crítica que conserve reproducibilidad.

Reglas:

- checkout del SHA exacto;
- etiqueta estable de Ubuntu, no `ubuntu-latest`;
- registrar `ImageOS`, `ImageVersion`, arquitectura, CPU, RAM y disco reales;
- historial mínimo;
- sparse checkout cuando el job no necesita todo el repo;
- sólo dependencias necesarias para ese tipo de job;
- versiones congeladas;
- ninguna instalación repetida dentro del mismo job;
- import y carga de modelos/datos comunes una sola vez por proceso.

En el repositorio público actual, la referencia oficial del runner Ubuntu
estándar es 4 vCPU, 16 GB RAM y 14 GB SSD. Se detecta de nuevo en cada run porque
GitHub puede cambiarla.

## 71. Caché sin estampida

El cache acelera dependencias e intermedios regenerables.

- Un único job puede escribir cada clave.
- Los jobs del fan-out restauran en modo lectura.
- La clave incluye SO, arquitectura, Python y lockfile.
- Un cache miss no invalida el run.
- No crear una clave distinta por shard sin necesidad.
- No guardar datasets finales, secretos ni material licenciado.
- Medir restauración frente a descarga directa.
- Evitar cache thrashing y ráfagas de cientos de escrituras.

El preflight vuelve a comprobar los límites oficiales de operaciones de caché.

## 72. Planificador de matrices

Las matrices se generan desde `balanced_shard_plan.json`.

Las unidades completas nunca se incrustan en el JSON de la matriz. Se guardan
en `work_units.parquet` y su asignación en
`balanced_unit_assignments.parquet`. El output de GitHub contiene sólo un
descriptor pequeño por shard con ID, referencia, hash, número de unidades,
coste estimado y grupo de merge. El total de outputs dinámicos del planner se
limita a 256 KiB.

Con 360 slots utilizables y límite 256 por matriz:

```text
matrix_0 = 256 jobs
matrix_1 = 104 jobs
total = 360 jobs
```

El reparto se recalcula automáticamente si cambia la capacidad. No se mantienen
listas manuales A/B.

Si el planner decide 256 jobs o menos, se crea una sola matriz. Nunca se envía
una matriz vacía. Cada matriz usa `fail-fast: false`; salvage, reconciliación y
merge se ejecutan con `if: always()` para conservar shards válidos.

Los runs pesados futuros se disparan mediante `workflow_dispatch` o
`workflow_call`. Un push o pull request ordinario sólo ejecuta validación estática
ligera, nunca una campaña masiva.

Si otros workflows comparten la organización, `reserved_concurrency` evita ocupar
slots necesarios. En una campaña exclusiva puede ser cero.

## 73. Tamaño óptimo de shard

El piloto mide:

- setup fijo;
- tiempo por unidad;
- varianza del coste;
- RAM por unidad;
- bytes por unidad;
- tiempo de checkpoint;
- tiempo de upload.

El planner prueba cantidades viables desde 1 hasta el techo confirmado y
minimiza:

```text
predicted_wall_time =
  queue_and_startup
  + slowest_balanced_shard
  + data_transfer
  + checkpoint_and_upload
  + hierarchical_merge
  + verification
```

No se crea un job cuando su compute útil esperado es demasiado pequeño frente a
su setup y transferencia. Usar 360 por costumbre puede ser más lento.

Se elige un tamaño que cumpla:

```text
setup_time / job_time <= target_setup_fraction
checkpoint_time / job_time <= target_checkpoint_fraction
job_p95 < timeout - shutdown_margin
peak_memory < memory_limit
peak_disk < disk_limit
```

Los umbrales por defecto son 10% para setup y 3% para checkpoint, pero el piloto
puede endurecerlos. Nunca se reducen para ocultar una mala proyección.

## 74. Balanceo por coste

No se reparten únicamente filas. Cada unidad recibe un peso estimado basado en:

- observaciones;
- símbolos;
- horizonte;
- número de features;
- complejidad del modelo;
- coste histórico;
- bytes esperados.

Se aplica una asignación determinista tipo longest-processing-time-first
(`weighted_lpt`). El objetivo es minimizar:

```text
straggler_ratio = shard_duration_p95 / shard_duration_median
```

El valor objetivo inicial es menor o igual a 1,50. Si el piloto lo supera, se
reparten de nuevo los bundles antes de producción.

## 75. Olas y paralelismo

Una única ola maximiza velocidad cuando todo el trabajo es independiente y cabe
en la recuperación diseñada.

Se usan varias olas sólo si:

- una depende científicamente de la anterior;
- existe adaptación operativa permitida;
- el coste de repetir una ola completa es inaceptable;
- el volumen exige checkpoints entre bloques;
- una restricción externa lo obliga.

No serializar olas para trabajo independiente. Cuando hay varias olas, la
siguiente puede adaptar tamaño de shard, batch, threads, compresión y fan-in, pero
nunca reglas, parámetros científicos o selección basándose en validación.

## 76. Uso de CPU y memoria

Cada job detecta CPU y RAM reales.

- Threads numéricos no superan CPUs disponibles.
- Evitar oversubscription de BLAS/OpenMP.
- Fijar explícitamente `OMP_NUM_THREADS`, `MKL_NUM_THREADS`,
  `OPENBLAS_NUM_THREADS` y `NUMEXPR_NUM_THREADS`.
- Prohibido anidar un pool de procesos dentro de otro pool.
- Batch size se adapta a memoria del piloto.
- Reutilizar matrices de features.
- Preferir operaciones vectorizadas y librerías columnar.
- Evitar copias completas de DataFrames.
- Liberar intermedios grandes antes de serializar.
- Registrar CPU útil, memoria pico e I/O wait.

Una utilización baja sostenida obliga a clasificar el cuello de botella antes de
aumentar paralelismo.

## 77. Lectura y escritura

- Parquet como formato científico tabular.
- Proyección estricta de columnas.
- Predicate pushdown por símbolo, fecha, periodo y shard.
- Row groups dimensionados mediante piloto.
- Escritura por batches.
- Schemas congelados antes de escribir.
- Particiones alineadas con los filtros más usados.
- No convertir a pandas todo el dataset si Arrow, Polars o DuckDB pueden operar
  incrementalmente.

Toda lectura completa se registra. Una segunda lectura del mismo ledger necesita
justificación en `performance_plan.json`.

## 78. Salidas en una sola pasada

Cuando varias salidas proceden del mismo ledger, una misma pasada alimenta:

- métricas;
- reconciliación;
- hashes parciales;
- particiones;
- auditorías;
- tablas resumidas.

Si técnicamente no puede hacerse en una pasada, el piloto estima el coste y el
planner documenta la razón.

## 79. Compresión

La compresión se decide con datos reales del piloto:

| Contenido | Nivel inicial |
|---|---:|
| Parquet, ZIP, Zstandard u otro precomprimido | 0 |
| Texto/CSV/JSONL temporal | 1 |
| Informe final pequeño | 6 |
| Nivel 9 | Sólo con justificación |

Se compara:

- segundos de CPU;
- bytes ahorrados;
- tiempo de red;
- coste de almacenamiento;
- impacto en la ruta crítica.

No recomprimir un archivo que ya está comprimido.

## 80. Artifacts y red

Cada shard sube sólo:

- resultado;
- manifest;
- errores;
- telemetría.

Reglas:

- agrupar muchos archivos pequeños;
- evitar duplicar inputs;
- `if-no-files-found: error`;
- nombres únicos por run, shard, intento y schema;
- no intentar que varios jobs escriban en el mismo artifact;
- verificar digest tras cada descarga;
- registrar artifact ID, digest, tamaño y tiempo de upload;
- compresión 0 para Parquet y archivos ya comprimidos;
- descarga selectiva por artifact o partición;
- backoff ante límites;
- retención mínima suficiente para merge y recuperación.

Las versiones actuales de `upload-artifact` crean artifacts inmutables. Las
acciones externas se fijan por commit inmutable, no sólo por una etiqueta que
pueda moverse.

El tamaño total proyectado debe caber en storage y en el disco temporal de los
jobs que lo descargan.

## 81. Checkpoints

El intervalo se calcula para que su coste permanezca bajo el umbral.

Cada job reserva `shutdown_margin` para:

- cerrar writers;
- terminar row groups;
- generar manifest;
- calcular hash;
- subir checkpoint;
- registrar estado.

El checkpoint nunca obliga a releer todo lo ya procesado. Reanudar comienza en la
primera unidad no confirmada.

## 82. Merge jerárquico

El piloto produce `merge_plan.json` con:

- fan-in;
- niveles;
- columnas requeridas;
- disco por nivel;
- memoria por nivel;
- tiempo p95;
- estrategia de deduplicado.

Ejemplo para 360 shards:

```text
360 shards
→ 12 merges parciales de 30
→ 3 merges intermedios de 4
→ 1 merge final
```

El ejemplo no es una constante. El planner elige el fan-in óptimo.

Todos los merges:

- leen incrementalmente;
- verifican hashes antes de consumir;
- conservan outputs parciales;
- son idempotentes;
- permiten `merge-only`;
- no necesitan descargar el corpus completo en un único disco si supera el
  presupuesto.

## 83. Métricas de rendimiento

`runtime_breakdown.parquet` registra por job:

- queue_seconds;
- provision_seconds;
- checkout_seconds;
- environment_seconds;
- data_download_seconds;
- compute_seconds;
- serialization_seconds;
- compression_seconds;
- upload_seconds;
- merge_seconds;
- verify_seconds;
- units_processed;
- bytes_read;
- bytes_written;
- peak_memory_mb;
- peak_disk_mb;
- cpu_utilization;
- io_wait;

El cierre calcula:

- unidades por minuto de ruta crítica;
- unidades por minuto facturable;
- coste por millón de unidades;
- p50, p95 y p99 de jobs;
- pico y promedio de paralelismo;
- setup fraction;
- checkpoint fraction;
- upload fraction;
- straggler ratio;
- tiempo total de cada etapa.

## 84. Paralelismo observado

`parallelism_timeline.csv` se calcula a partir de intervalos reales
`started_at/completed_at`.

Debe informar:

- solicitado;
- permitido;
- observado máximo;
- observado medio;
- tiempo hasta alcanzar el pico;
- porcentaje de tiempo por nivel de concurrencia;
- jobs bloqueados en cola.

No inferir paralelismo por el número de artifacts ni por el orden visual de
GitHub.

## 85. Detección del cuello de botella

`bottleneck_report.json` clasifica:

```text
queue_bound
setup_bound
network_bound
cpu_bound
memory_bound
disk_bound
serialization_bound
compression_bound
merge_bound
provider_bound
balanced
```

Cada clasificación incluye evidencia y una recomendación para la siguiente ola.
No aumentar jobs si el cuello de botella es proveedor, merge, disco o red.

## 86. Adaptación permitida

Entre olas pueden cambiar:

- tamaño de shard;
- batch size;
- número de threads;
- particionado físico;
- nivel de compresión;
- frecuencia de checkpoint;
- fan-in del merge;
- paralelismo hasta el límite confirmado.

No pueden cambiar:

- señal;
- features científicas;
- universo;
- parámetros de estrategia;
- filtros de aceptación;
- definición de métricas;
- periodos;
- selección;
- size;
- política locked.

Todo cambio operativo genera una nueva versión de `performance_plan.json`.

## 87. Sólo runners estándar

Los futuros workflows cubiertos por esta plantilla usan exclusivamente runners
estándar. La capacidad real se registra al inicio porque depende del tipo y
visibilidad del repositorio.

Larger runners, GPU runners y runners de pago quedan prohibidos para este
sistema. Si algún día el usuario pide expresamente otro sistema, será otra
campaña, otro contrato y otra versión de plantilla; nunca una activación
silenciosa de ésta.

## 88. Outputs obligatorios de rendimiento

Cada campaña genera:

```text
performance_contract.json
performance_pilot.json
performance_plan.json
environment_manifest.json
resolved_run_spec.json
execution_plan.json
balanced_shard_plan.json
work_units.parquet
balanced_unit_assignments.parquet
runtime_breakdown.parquet
parallelism_timeline.csv
bottleneck_report.json
recovery_plan.json
checkpoint_audit.parquet
shard_attempt_manifest.parquet
unit_attempt_manifest.parquet
merge_plan.json
performance_final.json
```

`performance_final.json` contiene:

```json
{
  "optimize_for": "wall_clock",
  "confirmed_concurrency": 360,
  "requested_parallelism": 0,
  "max_parallel_observed": 0,
  "average_parallel_observed": 0,
  "critical_path_seconds": 0,
  "billable_minutes": 0,
  "scientific_units_completed": 0,
  "units_per_critical_path_minute": 0,
  "units_per_billable_minute": 0,
  "setup_fraction": 0,
  "checkpoint_fraction": 0,
  "upload_fraction": 0,
  "straggler_ratio": 0,
  "bottleneck": "",
  "larger_runner_used": false,
  "performance_contract_passed": false
}
```

El verifier exige `performance_contract_passed=true`, salvo que el spec declare
la campaña como diagnóstico de infraestructura.

## 89. Integración con Aurora

El sistema no crea contratos paralelos:

- `ProtocolPolicy` conserva `policy_hash`;
- `SnapshotStore` y `SnapshotBackend` conservan snapshots;
- `FeatureStore` conserva causalidad point-in-time;
- `WitnessRecorder` conserva evidencia de inputs y outputs;
- `ExperimentTracker` conserva linaje;
- `monitoring.telemetry` conserva telemetría base;
- `runtime_paths` resuelve todos los paths.

La capa GitHub añade planificación y agregación, pero no sustituye estas piezas.
El guard GitHub-only se centraliza en `core/execution_policy.py`; los nuevos
scripts no vuelven a copiarlo.

## 90. Planner universal de motores

Cada workload declara:

```text
describe_contract
prepare_shared_inputs
enumerate_units
estimate_unit_cost
execute_unit
verify_unit
merge_outputs
```

El piloto puede comparar Python de referencia, NumPy, Numba, Arrow, DuckDB,
threads y procesos. Sólo se cronometra una alternativa después de demostrar que
produce el mismo resultado con los mismos datos, seeds, batches y presupuesto de
threads.

El tiempo de compilación y warm-up cuenta si afecta al run real. Un
microbenchmark nunca puede sustituir la medición end-to-end.

## 91. Reutilización exacta

El planner construye el DAG:

```text
datos → features → señales → posiciones → retornos → métricas → robustez
```

Cada nodo tiene hash de contenido. Cálculos exactamente iguales se hacen una vez.
No se eliminan candidatas por “parecerse”. Si dos candidatas son funcionalmente
idénticas, pueden compartir cálculo sólo tras demostrar equivalencia exacta y
manteniendo ambas identidades en los outputs.

La adaptación entre olas sólo puede leer telemetría operativa. Prohibido usar
calidad de candidatas, métricas, validación o locked.

## 92. Aceleración nativa

Orden obligatorio:

```text
mejor algoritmo
→ cálculo compartido
→ vectorización
→ NumPy/Arrow/DuckDB
→ Numba
→ Rust
```

Rust se usa sólo si el hot path supone al menos 10% del tiempo medido y proyecta
al menos 5% de mejora end-to-end. Se mantiene referencia Python, tests
diferenciales, tolerancia explícita y fallback automático.

Se construye una sola wheel PyO3/maturin por SHA, Python, SO, arquitectura y
toolchain. Los 360 jobs verifican y reutilizan esa wheel; nunca la compilan cada
uno.

## 93. Guard de workflows futuros

Los workflows existentes quedan en una allowlist versionada. Todo workflow
pesado nuevo debe usar el framework.

El guard rechaza:

- referencias a reusable workflows o acciones locales inexistentes;
- matrices superiores a 256;
- acciones externas sin commit inmutable;
- triggers automáticos que lancen cargas masivas;
- nombres de artifact incompatibles con inmutabilidad;
- dependencias no declaradas;
- ausencia de política GitHub-only;
- ausencia de contrato, telemetría, reconciliación o verifier.

Aurora declara paquetes explícitamente en `pyproject.toml`. Todo subpaquete nuevo,
config anidada o dependencia opcional debe registrarse; no basta con crear la
carpeta.

---

# REGLA FINAL

El objetivo no es que nada falle. El objetivo es que ningún fallo pueda:

- contaminar resultados;
- fingir éxito;
- perder trabajo válido;
- obligar a repetir todo;
- abrir locked;
- usar validación para seleccionar;
- exponer secretos;
- superar presupuesto sin aviso;
- quedarse toda la noche parado sin dejar estado recuperable.

Si una comprobación no puede demostrarse, se considera no cumplida.
