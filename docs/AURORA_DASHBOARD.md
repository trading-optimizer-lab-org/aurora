# Aurora Runs Dashboard

Panel web de solo lectura para consultar, desde cualquier ordenador, los
runs de GitHub Actions, sus jobs, artefactos y resultados normalizados de
backtests.

## Qué queda construido

- React/Vite servido por un Cloudflare Worker con Static Assets.
- D1 para el índice de workflows, runs, jobs, artefactos y métricas.
- R2 para conservar informes legibles y resultados seleccionados.
- Sin login en la página: el enlace contiene un secreto largo en
  `/s/<secreto>/`.
- La página no recibe ni el token de GitHub ni credenciales de Cloudflare.
- No hay controles para lanzar, cancelar, repetir ni modificar workflows.
- Se indexan también CI, tests, seguridad, documentación y workflows que no
  sean de backtest.
- La pestaña de artefactos consulta el inventario completo de GitHub bajo
  demanda y cruza los registros persistidos con el archivo local.
- El detalle de cada run muestra jobs, pasos, logs bajo demanda, artefactos,
  resultados reconocidos y enlaces de procedencia.
- La portada está pensada para lectura rápida: muestra qué está en marcha,
  el historial y los resultados sin exigir conocer GitHub Actions.
- Cada run expone `completion_at`: hora real para ejecuciones terminadas y
  hora estimada para ejecuciones activas. La estimación usa la duración media
  de al menos tres ejecuciones terminadas del mismo workflow; si no existe,
  usa la media histórica general y lo indica en pantalla.

La ausencia de login no convierte el enlace en público: cualquiera que lo
obtenga podrá leer el panel. Si se comparte, hay que rotarlo cambiando
`DASHBOARD_LINK_SECRET` y actualizando `AURORA_DASHBOARD_URL`.

## Coste y límite real

La configuración está diseñada para usar únicamente los niveles gratuitos de
Cloudflare. El archivo no habilita facturación ni crea recursos de pago. R2
usa una reserva interna de 7.516.192.768 bytes, inferior a 8 GB; al alcanzar
la reserva, el artefacto sigue indexado y conserva su enlace de origen, pero
no se copia a R2. Los binarios, duplicados, caducados y archivos que superan
la política también quedan como `source_only`, `quota_blocked`, `expired` o
`error` según corresponda.

“100% gratis” depende de mantenerse dentro de los límites gratuitos vigentes
de Cloudflare y GitHub. La aplicación tiene una barrera propia para que el
archivo no cruce deliberadamente su reserva. No se debe interpretar como
almacenamiento ilimitado.

## Despliegue inicial en Cloudflare

Hace falta entrar una vez en Cloudflare para crear los recursos. El acceso
posterior al panel no pide login.

Desde `C:\Users\HP\AURORA`:

```powershell
npm --prefix web ci
npm --prefix web run build
npm --prefix cloudflare ci
npx --prefix cloudflare wrangler login
npx --prefix cloudflare wrangler d1 create aurora-dashboard
npx --prefix cloudflare wrangler r2 bucket create aurora-dashboard-archive
```

Copiar el `database_id` que devuelve D1 dentro de
`cloudflare/wrangler.toml`, sustituyendo el UUID de ceros. El nombre del
bucket debe coincidir con `aurora-dashboard-archive`. No cambiar el límite de
archivo sin revisar antes la cuota gratuita disponible.

Crear dos secretos distintos para el Worker:

```powershell
$rng = [Security.Cryptography.RandomNumberGenerator]::Create()
function New-Secret {
  $bytes = New-Object byte[] 32
  $rng.GetBytes($bytes)
  return ([Convert]::ToBase64String($bytes).TrimEnd("=").Replace("+", "-").Replace("/", "_"))
}
$linkSecret = New-Secret
$syncSecret = New-Secret
$linkSecret | npx --prefix cloudflare wrangler secret put DASHBOARD_LINK_SECRET --config cloudflare/wrangler.toml
$syncSecret | npx --prefix cloudflare wrangler secret put DASHBOARD_SYNC_TOKEN --config cloudflare/wrangler.toml
$rng.Dispose()
npx --prefix cloudflare wrangler d1 migrations apply DB --remote --config cloudflare/wrangler.toml
npx --prefix cloudflare wrangler deploy --config cloudflare/wrangler.toml
```

Para un secreto generado con PowerShell se puede eliminar `+`, `/` y `=` si
se quiere una URL más corta; nunca reutilizar el token de sincronización como
secreto del enlace.

El despliegue muestra una URL `workers.dev`. El enlace final tendrá este
formato:

```text
https://<worker>.<subdominio>.workers.dev/s/<DASHBOARD_LINK_SECRET>/
```

Guardar ese enlace; no se almacena en el navegador ni en el código.

## Secretos de GitHub Actions

En `Settings → Secrets and variables → Actions` del repositorio, crear:

| Secreto | Valor |
|---|---|
| `AURORA_DASHBOARD_URL` | URL completa hasta `/s/<secreto>` |
| `AURORA_DASHBOARD_SYNC_TOKEN` | El mismo valor de `DASHBOARD_SYNC_TOKEN` |
| `CLOUDFLARE_API_TOKEN` | Token de Cloudflare con permiso de despliegue del Worker/D1/R2 |
| `CLOUDFLARE_ACCOUNT_ID` | ID de la cuenta Cloudflare |

`GITHUB_TOKEN` lo proporciona automáticamente GitHub y solo se usa con
permisos `contents: read` y `actions: read`.

## Sincronización

En producción, el Cron Trigger del Worker se ejecuta cada 15 minutos para
refrescar la cola reciente sin exponer credenciales. El workflow
`.github/workflows/aurora-dashboard-sync.yml` también se puede lanzar
manualmente cuando está habilitado en la rama de despliegue. Cada ejecución
indexa una página de hasta 100 runs; el campo `page` permite continuar un
backfill histórico. Los registros son idempotentes por los IDs estables de
GitHub.

El sincronizador usa reintentos acotados, no ejecuta backtests locales y no
realiza ninguna operación de escritura sobre GitHub. Cada ejecución mantiene
la página actual y avanza también un checkpoint histórico, por lo que el
backfill progresa automáticamente sin dejar de actualizar la primera página.
Si GitHub falla, el panel conserva los datos anteriores y muestra el estado
desactualizado junto con el último error registrado.

Para probar sin red ni escritura:

```powershell
& "C:/Python314/python.exe" scripts/aurora_dashboard_sync.py --fixture ruta/al/lote.json
& "C:/Python314/python.exe" scripts/aurora_dashboard_sync.py --dry-run --page 1 --max-runs 2
```

## Desarrollo local de la interfaz

```powershell
$env:VITE_DEMO_MODE = "true"
npm --prefix web run dev
```

El modo demo usa fixtures sin datos reales y permite revisar la navegación,
los filtros, el detalle del run y los estados `Solo fuente`. En producción
`VITE_DEMO_MODE` no debe estar activado: los errores de la API se muestran en
la interfaz.

## Verificación antes de publicar

```powershell
npm --prefix web run typecheck
npm --prefix web run test:run
npm --prefix web run build
npm --prefix cloudflare run typecheck
npm --prefix cloudflare run test:run
& "C:/Python314/python.exe" -m pytest tests/test_aurora_dashboard_parsers.py tests/test_aurora_dashboard_archive.py tests/test_aurora_dashboard_workflows.py tests/test_aurora_dashboard_sync.py tests/test_dashboard.py -q
npx --yes wrangler deploy --dry-run --config cloudflare/wrangler.toml
```

El despliegue no se considera publicado hasta que la URL real responda a
`/s/<secreto>/api/health` y el panel muestre una sincronización correcta.

## Verificación de producción realizada el 20/08/2026

La URL publicada respondió correctamente después de desplegar el Worker:

- el enlace con y sin barra final carga el HTML y redirige de forma segura a la
  variante canónica;
- CSS y JavaScript se sirven dentro de `/s/<secreto>/assets/` y responden 200;
- `/api/health` responde `ok=true` y `stale=false`;
- el índice real mostró 19.766 runs, 203 workflows, 2 activos y 359.009
  artefactos; estas cifras cambian con nuevas ejecuciones;
- el detalle de un run fallido devolvió sus jobs, `/api/jobs/:id` devolvió el
  job y `/api/jobs/:id/logs` devolvió logs reales sin enviar el token al cliente;
- el inventario de artefactos pagina con cursores sin duplicar registros;
- el archivo CSV archivado respondió 200 desde R2;
- las suites actuales pasan: 6 tests de interfaz, 7 del Worker y 27 tests
  Python del dashboard, con un test Python omitido por condición del entorno.

El secreto del enlace no se guarda en este documento ni en el repositorio.
