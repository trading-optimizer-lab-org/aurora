# Recibo de bootstrap del controlador autónomo de catálogo

## Estado actual

```text
result=BLOCKED
production_enabled=false
production_run_created=false
controller_enabled_readback=false
live_audit_utc=2026-08-23T11:59:09Z
```

Este archivo no acredita una instalación terminada. Es el registro honesto de
lo que falta. Solo se cambia a `READY` después de que todas las pruebas se hayan
obtenido de las identidades, archivos y controles reales.

## Implementación local

```text
repository=trading-optimizer-lab-org/aurora
implementation_branch=codex/sp500-search-method-benchmark-short
implementation_commit=30d90d941ee62c5c81b027fa58609744307c5e78
implementation_merged=false
github_lint_run_id=32637970710
github_lint_passed=true
catalog_actionlint_files_passed=20
github_catalog_workflow_definition_error_fixed=true
requester_client_built=false
requester_broker_built=false
requester_apps_installed=false
requester_app_bound=false
auditor_app_bound=false
authority_anchor_bound=false
agent_sandbox_active=false
broker_service_active=false
production_seal_present=false
github_app_installations_observed=0
catalog_production_environment_present=false
catalog_auditor_secret_present=false
requester_public_key_present=false
agent_account_present=false
requester_account_present=false
broker_task_present=false
current_ai_os_identity=DESKTOP-4LEK540\HP
current_ai_has_admin_os_token=false
current_ai_has_admin_github_credential=true
local_requester_tests_passed=true
bounded_reconcile_hint_implemented=true
terminal_backoff_and_rate_limit_implemented=true
signed_history_reconstruction_implemented=true
self_hash_and_acl_drift_checks_implemented=true
malformed_spool_quarantine_implemented=true
transient_network_retry_without_duplicate_post_implemented=true
single_use_qualification_terminal_binding_implemented=true
closed_runtime_application_manifest_mirror_implemented=true
github_second_precision_window_implemented=true
final_bootstrap_receipt_hash_binding_implemented=true
dedicated_agent_client_identity_gate_implemented=true
service_only_requester_app_binding_implemented=true
provider_retry_after_honored=true
bootstrap_ready_value_enforced=true
read_only_acl_rights_enforced=true
incoming_spool_capacity_accounted=true
```

## Bloqueos vigentes

```text
AGENT_ADMIN_CREDENTIAL_EXPOSED
REQUESTER_APP_IDENTITY_UNBOUND
AUDITOR_APP_IDENTITY_UNBOUND
AUTHORITY_ANCHOR_UNBOUND
AGENT_SANDBOX_NOT_ENFORCEABLE_IN_CURRENT_CODEX_PROCESS
BROKER_IDENTITY_UNINSTALLED
CATALOG_PRODUCTION_ENVIRONMENT_UNBOUND
CURRENT_ARTIFACT_STORAGE_HEADROOM_UNPROVEN
```

El 23 de agosto de 2026 GitHub devolvió cero instalaciones de Apps para la
organización, no mostró el entorno `catalog-production` ni el secreto auditor,
y confirmó `CATALOG_CONTROLLER_ENABLED=false`. El token de GitHub disponible
en el contexto actual conserva permisos administrativos, por lo que este mismo
proceso no puede acreditar la separación final exigida para producción.

La auditoría de almacenamiento observó una media del periodo muy superior a la
asignación gratuita configurada, pero GitHub no proporcionó una lectura exacta
del uso actual. No se transforma esa media en una cifra de uso instantáneo y no
se borran artifacts para forzar un resultado.

## Acción humana imprescindible para desbloquear el bootstrap

Esta intervención no puede hacerla la IA actual sin invalidar la separación de
credenciales que el controlador debe garantizar:

1. Cerrar Codex y cualquier otra IA con acceso al equipo.
2. Entrar en una sesión de Windows administradora separada y autenticarse en
   GitHub como propietario de `trading-optimizer-lab-org`.
3. Crear e instalar, solo en `trading-optimizer-lab-org/aurora`, estas dos Apps
   privadas de la organización, con webhook desactivado:
   - `AURORA Catalog Requester`: Metadata de lectura e Issues de lectura y
     escritura; ningún otro permiso.
   - `AURORA Catalog Controls Auditor`: Metadata, Actions, Administration,
     Contents, Environments, Issues, Packages y Variables de solo lectura;
     Administration de organización de solo lectura; ningún permiso de
     escritura.
4. Generar una clave distinta para cada App. Sin abrirlas ni imprimirlas,
   moverlas inmediatamente desde Descargas a dos ubicaciones distintas bajo
   `C:\ProgramData\AURORA\BootstrapStaging`, con herencia desactivada y acceso
   solo para SYSTEM y Administradores. La clave solicitante debe terminar como
   `requester-private-key.pem`. La clave auditora no se entrega a Codex.
5. Anotar únicamente, para cada App: App ID, Installation ID, login exacto
   `<slug>[bot]`, permisos observados, repositorio instalado y huella SHA-256 de
   la clave pública. No anotar ni enviar ninguna clave privada, JWT o token.
6. Reanudar esta tarea solo con esos datos no secretos. La siguiente fase ligará
   las identidades públicas, repetirá las pruebas, fusionará el cambio protegido
   y dejará preparados los dos instaladores. Su aplicación requerirá después
   una consola administradora separada y estos comandos exactos:

   ```powershell
   & scripts/install_catalog_agent_sandbox.ps1 `
     -Apply `
     -Confirm AURORA_CATALOG_AGENT_SANDBOX_V1

   & scripts/install_catalog_requester_broker.ps1 `
     -Apply `
     -Confirm AURORA_CATALOG_REQUESTER_BROKER_V1
   ```

7. Codex deberá reiniciarse finalmente bajo la cuenta no administradora
   `AURORAAgent`. El controlador permanecerá desactivado hasta que esa sesión y
   la sesión administradora separada superen todas las comprobaciones finales.

Si GitHub pide login, CAPTCHA, 2FA o confirmación de identidad, el resultado
sigue siendo `BLOCKED_GITHUB_APP_IDENTITY_CONFIRMATION_REQUIRED`. No se debe
entregar una clave a esta IA para acelerar el proceso.

## Campos que debe rellenar la sesión de bootstrap real

```text
default_branch=
merged_controller_commit_sha=
master_prompt_sha256=
policy_sha256=
registry_sha256=
actor_config_sha256=
authority_anchor_config_sha256=
github_controls_config_sha256=
workflow_topology_sha256=
campaign_definition_manifest_hashes=
terminal_label_readback_hash=
requester_app_id=
requester_app_login=
requester_app_permissions=
requester_public_key_fingerprint=
requester_app_binding_hash=
auditor_app_id=
auditor_app_login=
auditor_app_permissions=
auditor_public_key_fingerprint=
authority_issue_number=
authority_issue_node_id=
broker_account_sid=
agent_account_sid=
broker_task_definition_hash=
client_lock_hash=
broker_lock_hash=
client_application_hash=
broker_application_hash=
broker_acl_negative_test_hash=
agent_process_tree_audit_hash=
github_controls_live_audit_hash=
qualification_run_ids=
qualification_receipt_hashes=
bootstrap_request_issue_number=
bootstrap_duplicate_call_proof_hash=
controller_enabled_readback=
production_seal_hash=
installed_bootstrap_receipt_path=receipts/controller-bootstrap-v1.receipt.json
installed_bootstrap_receipt_sha256=
final_result=
```

## Condiciones para escribir `READY`

- Los dos GitHub Apps reales están ligados con permisos exactos y claves
  separadas.
- La IA no puede acceder a credenciales administradoras, de solicitante ni de
  auditor.
- Codex se ejecuta realmente bajo `AURORAAgent`.
- El intermediario se ejecuta realmente bajo `AURORARequester`.
- Todos los controles de GitHub y presupuestos gratuitos tienen lectura actual
  válida.
- La cualificación se ha repetido con resultados equivalentes.
- La única petición de bootstrap termina sin autoridad ni cálculo.
- Repetirla no crea otro issue.
- No se ha creado ninguna petición de producción.

Hasta entonces, el estado sigue siendo `BLOCKED` aunque todo el código local
pase sus pruebas.
