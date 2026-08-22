# Cualificación del controlador autónomo de catálogo

## Resultado

La implementación local completó tres rondas adversariales consecutivas sin
problemas materiales. Esto no habilita producción: el requester aislado, las
GitHub Apps, el sandbox del agente, la calibración operativa y varios controles
externos siguen pendientes o bloqueados.

No se lanzó ningún run de catálogo de producción. Las únicas ejecuciones
científicas locales fueron fixtures sintéticos cerrados y dos pequeñas pruebas
de referencia autorizadas para esta tarea.

## Criterios obligatorios de cada ronda

1. Intentar alcanzar cómputo pesado sin autoridad válida.
2. Seguir receta y componente hasta el resultado final y verificar hashes.
3. Recorrer fallos transitorios, deterministas, operativos y de integridad.
4. Buscar trabajo repetido, descargas amplias, retries globales y mala reducción.
5. Verificar que una IA futura solo pueda elegir `campaign_key`.

Un problema material cambia corrección, seguridad, automatización,
recuperabilidad, tiempo/coste significativo o probabilidad de error.

## Bytes exactos revisados

Las tres rondas revisaron los mismos 278 archivos. El conjunto ordenado procede
de `.github/actions/aurora-recovery-plan`, `.github/workflows`, `config`,
`infra/github_performance`, `infra/sp500_megarun`, `schemas`, `scripts`,
`tests`, `docs/runbooks` y `requirements`, filtrado por `catalog`,
`github_performance` o `aurora-recovery-plan`. Se excluyen los documentos de
plan/diseño y este documento para evitar autorreferencia.

Cada entrada canónica contiene ruta con `/`, tamaño y SHA-256 de sus bytes.

- Archivos: 278
- Manifiesto SHA-256:
  `34f647453f72fb465a8fe26df973a3aba16d4d1be98267d6db5763d74437e568`
- `HEAD` base común:
  `c44c47fbf0e050e75479765a7ccc26aa51a2820f`

El manifiesto, no el `HEAD` por sí solo, cubre también los bytes aún no
confirmados que fueron revisados.

## Reinicios honestos del contador

Una ronda descartada detectó dos fixtures que atribuían el índice reutilizable
al controlador. El productor real es
`.github/workflows/catalog-optimized-run.yml`. Se corrigieron y pasaron sus 13
pruebas; el contador volvió a cero.

Después, `git diff --cached --check` encontró tres líneas finales vacías en
archivos de prueba. Aunque era un cambio cosmético, alteraba los bytes. Se
eliminaron, se recalculó el manifiesto y el contador volvió a cero. Solo las
tres rondas siguientes cuentan.

## Ronda limpia 1

- Acceso: los 12 workflows detectados como pesados son `workflow_call`; la
  llamada al motor exige admisión, reserva y `RUNNING` releídos y verificados.
- Corrección: trazado completo de receta, componente, planificación, worker,
  reducción, verificador y evidencia final.
- Fallos: transient, determinista, OOM/disco, artefacto ausente, manipulación,
  entrega incierta, checkpoint y finalizador interrumpido.
- Eficiencia: preparación única, reutilización cálida, afinidad, recuperación
  solo de lo faltante y reducción central/jerárquica.
- Operador: el prompt v6 solo expone `campaign_key`.
- Pruebas: 250 pasaron sobre los bytes definitivos.
- Problemas materiales: ninguno.
- Cambios: ninguno.
- Consecutivas: 1.
- Recibo: `60c991c49858beb19a86855ead8331625f05dce0f97f67d48a1d3e0edafbe67d`.

## Ronda limpia 2

- Acceso: routing, admisión, autoridad, procedencia, reconciliación y eventos;
  ningún texto no confiable se convierte en orden de shell.
- Corrección: request, campaña, índice reutilizable, ciencia terminal y recibos.
- Fallos: carreras, mirrors huérfanos, POST incierto, manipulación, JSON inválido,
  evidencia incompleta y fallos de workers.
- Eficiencia: paginación acotada, promoción cálida ligada al contenido, retries
  selectivos y ausencia de duplicados.
- Operador: sin launcher directo ni parámetros internos mutables.
- Pruebas: 188 pasaron sobre los bytes definitivos.
- Problemas materiales: ninguno.
- Cambios: ninguno.
- Consecutivas: 2.
- Recibo: `d5b52ffb4b5e07dd56aea222fc999f24953118c6cfd8226a7d7214418844bbdc`.

## Ronda limpia 3

- Acceso: topología reenumerada sin trigger pesado público ni fallback.
- Corrección: ciencia, component store, reducción, terminal y Q-001..Q-078.
- Fallos: recuperación acotada, evidencia ausente/corrupta, deriva de controles,
  manipulación y cierre idempotente.
- Eficiencia: frío/cálido, inputs, componentes, checkpoints, afinidad, cola y
  reducción jerárquica.
- Operador: CAT-001..CAT-025 pasan sin `xfail`, `skip`, excepción temporal ni
  implementación pendiente.
- Pruebas: 259 pasaron; Ruff y `git diff --cached --check` pasaron.
- Definición de campaña:
  `b8a9435cc2588646baa98fb2e00d0f1be32aac419ba26fa22c72a8a093f13b47`.
- Problemas materiales: ninguno.
- Cambios: ninguno.
- Consecutivas: 3.
- Recibo: `0f45bdc2d6c18bc3a897590dbb7a267621be655dcdcaa64cb4690255d17dcc8a`.

## Identidades canónicas de los recibos

Cada recibo es SHA-256 del JSON UTF-8 siguiente, con claves ordenadas y
separadores `,` y `:`, sin incluir el propio hash.

```json
{"changes_made":[],"checks":{"bypass":"Enumerated every workflow with the production topology parser; all 12 detected heavy catalog workflows are workflow_call-only and the sole engine call requires admission, reservation, and RUNNING read-back gates.","correctness":"Traced the synthetic recipe/component path and the real campaign definition through planning, component reuse, worker output, reduction, verifier, and final evidence hashes.","efficiency":"Verified one runtime/input preparation, warm component reuse, affinity partitioning, missing-work-only recovery, bounded artifact transport, and central-versus-hierarchical reduction selection.","failure":"Exercised transient, deterministic, OOM/disk replan, missing artifact, ledger tamper, uncertain delivery, checkpoint, and interrupted finalizer paths.","operator":"Verified the active v6 prompt exposes only campaign_key and forbids direct GitHub, workflow, issue, runner, path, retry, or science choices."},"commands":["pytest final-byte qualification/workflow/engine/recovery/terminal/prompt and changed adapter tests: 250 passed","python build_catalog_campaign_definition.py --campaign-key sp500-optimized-catalog-v1 --check: pass","static heavy-workflow inventory and event-to-shell review: pass"],"consecutive_clean_round_count":1,"head_sha":"c44c47fbf0e050e75479765a7ccc26aa51a2820f","material_problems_found":[],"remaining_risks":["Task 14 requester broker, GitHub Apps, OS sandbox, and one-time bootstrap are not yet installed; production remains disabled.","Operational capacity qualification has no promoted live calibration receipt.","Live GitHub evidence reports a current-period Actions-storage average of 521995722751 bytes versus the configured 53687091200-byte free allowance, while exact current artifact headroom remains unproven.","The present Codex context can read an administrator gh credential, so AGENT_ADMIN_CREDENTIAL_EXPOSED must continue to block production."],"reviewed_file_count":278,"reviewed_files_manifest_sha256":"34f647453f72fb465a8fe26df973a3aba16d4d1be98267d6db5763d74437e568","round_number":1}
{"changes_made":[],"checks":{"bypass":"Retested routing, admission, authority writer, provenance, request reconciliation, and issue/event boundaries; untrusted issue content never becomes a shell fragment.","correctness":"Rechecked request, campaign, store-index, terminal-science, and receipt bindings across every adapter boundary.","efficiency":"Rechecked bounded pagination, content-bound warm-store promotion, selective retries, and no duplicate request or store creation.","failure":"Rechecked duplicate races, orphaned mirror delivery, uncertain POST, tampered receipt, malformed JSON, incomplete evidence, and worker-failure recovery.","operator":"Rechecked active prompt policy and the absence of direct launcher instructions or mutable runtime choices."},"commands":["pytest final-byte routing/admission/mirror/recovery/terminal/performance/prompt and changed adapter tests: 188 passed","rg GitHub event interpolation across catalog workflows: only validated issue number crosses into an environment value","manual mirror-repair chain and exact writer-provenance trace: pass"],"consecutive_clean_round_count":2,"head_sha":"c44c47fbf0e050e75479765a7ccc26aa51a2820f","material_problems_found":[],"remaining_risks":["Task 14 requester broker, GitHub Apps, OS sandbox, and one-time bootstrap are not yet installed; production remains disabled.","Operational capacity qualification has no promoted live calibration receipt.","Live GitHub evidence reports a current-period Actions-storage average of 521995722751 bytes versus the configured 53687091200-byte free allowance, while exact current artifact headroom remains unproven.","The present Codex context can read an administrator gh credential, so AGENT_ADMIN_CREDENTIAL_EXPOSED must continue to block production."],"reviewed_file_count":278,"reviewed_files_manifest_sha256":"34f647453f72fb465a8fe26df973a3aba16d4d1be98267d6db5763d74437e568","round_number":2}
{"changes_made":[],"checks":{"bypass":"Re-enumerated controller workflow gates and confirmed no heavy public trigger or permissive fallback was introduced.","correctness":"Re-ran exact scientific, component-store, reduction, terminal, and Q-001 through Q-078 equivalence checks.","efficiency":"Re-ran cold/warm runtime, prepared-input, component, checkpoint, affinity, tail, and hierarchical-reduction checks.","failure":"Re-ran bounded recovery, missing/corrupt evidence, controls drift, tamper, and idempotent-finalizer cases.","operator":"Re-ran CAT-001 through CAT-025 and confirmed no xfail, skip, temporary, TODO, TBD, or pending implementation remains."},"commands":["pytest final-byte qualification/workflow/engine/recovery/terminal/performance/prompt and changed adapter tests: 259 passed","ruff check controller, performance, adapters, changed tests, and qualification: pass","git diff --cached --check: pass","pending-enforcement scan: no matches","campaign-definition check: b8a9435cc2588646baa98fb2e00d0f1be32aac419ba26fa22c72a8a093f13b47"],"consecutive_clean_round_count":3,"head_sha":"c44c47fbf0e050e75479765a7ccc26aa51a2820f","material_problems_found":[],"remaining_risks":["Task 14 requester broker, GitHub Apps, OS sandbox, and one-time bootstrap are not yet installed; production remains disabled.","Operational capacity qualification has no promoted live calibration receipt.","Live GitHub evidence reports a current-period Actions-storage average of 521995722751 bytes versus the configured 53687091200-byte free allowance, while exact current artifact headroom remains unproven.","The present Codex context can read an administrator gh credential, so AGENT_ADMIN_CREDENTIAL_EXPOSED must continue to block production."],"reviewed_file_count":278,"reviewed_files_manifest_sha256":"34f647453f72fb465a8fe26df973a3aba16d4d1be98267d6db5763d74437e568","round_number":3}
```

## Bloqueos externos actuales

- Falta implementar e instalar el broker/requester de la Task 14.
- Faltan la GitHub App requester y la App auditora de solo lectura.
- Falta ejecutar Codex bajo `AURORAAgent` y demostrar aislamiento real.
- La cualificación operativa carece de tres calibraciones reales promovidas.
- GitHub muestra 521.995.722.751 bytes de promedio de almacenamiento del periodo
  frente a 53.687.091.200 bytes configurados, sin demostrar el uso actual exacto.
- El contexto actual puede leer una credencial `gh` administradora.

Hasta resolver y verificar todo lo anterior, el resultado global correcto es
`BLOCKED`, aunque el código y la cualificación sintética local estén limpios.
