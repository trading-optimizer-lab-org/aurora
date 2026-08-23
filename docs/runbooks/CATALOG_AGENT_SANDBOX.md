# Aislamiento obligatorio de la IA que pide runs de catálogo

## Regla principal

No basta con ejecutar un comando secundario como `AURORAAgent`. El proceso de
Codex que lee el mensaje del usuario debe ejecutarse entero bajo esa cuenta y no
debe poder volver a la cuenta de HP, al navegador del usuario ni a credenciales
guardadas.

Mientras Codex siga ejecutándose con la cuenta actual y pueda usar la sesión
administradora de GitHub, el resultado correcto es:

```text
BLOCKED_AGENT_SANDBOX_NOT_ENFORCEABLE
AGENT_ADMIN_CREDENTIAL_EXPOSED
```

## Qué prepara el instalador

La simulación se puede ejecutar siempre y no cambia el equipo:

```powershell
& scripts/install_catalog_agent_sandbox.ps1
```

Debe devolver JSON con `mode=dry_run`, `mutation_performed=false` y
`production_enabled=false`.

La creación explícita usa únicamente:

```powershell
& scripts/install_catalog_agent_sandbox.ps1 `
  -Apply `
  -Confirm AURORA_CATALOG_AGENT_SANDBOX_V1
```

El instalador crea solo `AURORAAgent`, comprueba que no sea administrador y
prepara una raíz aislada. No crea `AURORARequester`, no instala una clave y no
habilita producción.

Después, el instalador separado del intermediario concede a esa cuenta solo el
cliente inmutable, las configuraciones públicas, lectura de estados/tickets/
recibos y creación de archivos nuevos en la bandeja. El binario del
intermediario, su entorno, la clave y el procesamiento conservan acceso
denegado. Estas ACL no acreditan por sí solas que Codex esté aislado.

## Lo que debe probar una sesión nueva antes de usarse

Todas estas comprobaciones se hacen desde el proceso real de Codex, no desde un
proceso hijo:

- Identidad exacta `AURORAAgent` y SID igual al recibo de instalación.
- Integridad media o inferior.
- Ningún SID de administrador habilitado.
- Sin privilegios para depurar, apropiarse de archivos o elevarse.
- Sin contraseña guardada, tarea elevada o ejecutable elevado modificable.
- Sin acceso a `gh`, PAT, cookies, almacén de credenciales o sesión de GitHub del
  usuario.
- Sin acceso a la extensión de navegador ni a perfiles de Brave/Chrome del
  usuario.
- Solo lectura del cliente inmutable y de sus entradas públicas.
- Solo creación de archivos nuevos en la bandeja del intermediario.
- Solo lectura de tickets, estado y recibos.
- Acceso denegado a claves, procesamiento, binario del intermediario, entorno
  del intermediario, definición de la tarea y ACL.

Si una sola comprobación falla, no se intenta arreglar desde la IA. Se conserva
`CATALOG_CONTROLLER_ENABLED=false`, no se crea ninguna petición y se registra el
bloqueo exacto.

## Fin del bootstrap

Después de reiniciar Codex bajo `AURORAAgent`, una sesión administradora separada
hace la auditoría final, habilita el controlador, crea el sello local y sale.
La sesión de la IA solo recibe el recibo sin secretos. Si la sesión
administradora continúa accesible, el bootstrap no está terminado.

El relanzador cerrado es `scripts/launch_catalog_codex_secure.ps1`. No acepta
parámetros. Comprueba la familia y el editor del paquete oficial, rechaza
cualquier proceso ChatGPT/Codex todavía perteneciente a HP, elimina variables
de GitHub heredadas y fija `CODEX_HOME` en el perfil aislado. Ese perfil
desactiva navegador, Chrome, control del equipo, conectores, MCP, avisos y
subprocesos de agentes. La contraseña aleatoria de `AURORAAgent` solo se
conserva cifrada mediante DPAPI en una carpeta legible por SYSTEM y
Administradores; no se guarda como texto ni variable de entorno.
