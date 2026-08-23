# Intermediario aislado para nuevos runs de catálogo

## Resultado que se busca

La IA no puede lanzar Actions, modificar código, cancelar procesos ni usar una
cuenta administradora. Solo puede depositar una petición cerrada en una bandeja
local. El intermediario `AURORARequester`, separado de la IA, firma esa petición
y crea exactamente un issue con una GitHub App limitada a Issues.

Este sistema permanece desactivado mientras falte una sola prueba de separación.
No se debe sustituir una prueba por una explicación o una captura de pantalla.

## Límites que no se pueden cambiar

- Repositorio: `trading-optimizer-lab-org/aurora`.
- API: `https://api.github.com`.
- Permisos de la App solicitante: únicamente Metadata read e Issues write.
- Raíz local: `C:\ProgramData\AURORA\CatalogRequester`.
- Cuenta del servicio: `AURORARequester`, sin permisos de administrador.
- Tarea programada: `AURORA Catalog Requester Broker`.
- Cliente normal: `catalog-requester-client.pyz`.
- Intermediario: `catalog-requester-broker.pyz`.
- Enlace de la App: `secrets\requester-app-binding-v1.json`, legible solo por
  `AURORARequester`, SYSTEM y Administradores.
- La IA no puede leer la clave privada, el intermediario, su carpeta de trabajo
  ni la credencial de la tarea. Tampoco puede leer los identificadores usados
  por el intermediario para obtener el token de la App.

## Preparación que siempre se ejecuta primero

Desde un checkout limpio del commit protegido y antes de crear cuentas o copiar
claves:

```powershell
python -m pytest -q `
  tests/test_submit_catalog_run_request.py `
  tests/test_catalog_requester_broker.py `
  tests/test_catalog_requester_packaging.py `
  tests/test_catalog_run_request.py `
  tests/test_catalog_authority_ledger.py `
  tests/test_catalog_github_controls.py

python scripts/build_catalog_requester_apps.py `
  --source-root C:\RUTA\AL\CHECKOUT\PROTEGIDO `
  --output-dir C:\ProgramData\AURORA\BootstrapStaging\requester-apps `
  --expected-commit-sha SHA_PROTEGIDO_DE_40_CARACTERES
```

La construcción se repite en una segunda carpeta vacía. Los cuatro archivos de
las dos construcciones deben ser idénticos byte por byte. Cada manifiesto debe
validar el commit, todos los archivos de entrada y el hash final de su `.pyz`.
Un cambio en cualquier archivo versionado bloquea la construcción. Un archivo
no versionado y ajeno a las listas cerradas se conserva y se ignora, porque no
puede entrar en ninguna de las dos aplicaciones.

La clave privada de la App solicitante se coloca, sin abrirla ni imprimirla, en:

```text
C:\ProgramData\AURORA\BootstrapStaging\requester-private-key.pem
```

La clave pública correspondiente, nunca la privada, debe estar versionada en
`config/catalog_requester_public_key_v1.pem` y su huella debe coincidir con la
configuración protegida.

## Instalación: primero simulación, después aplicación única

La simulación no cambia nada:

```powershell
& scripts/install_catalog_requester_broker.ps1
```

Se revisa el JSON. Debe decir `mode=dry_run`,
`mutation_performed=false` y `production_enabled=false`.

Solo una sesión administradora de bootstrap, sin reutilizarla para operar la IA,
puede aplicar:

```powershell
& scripts/install_catalog_requester_broker.ps1 `
  -Apply `
  -Confirm AURORA_CATALOG_REQUESTER_BROKER_V1
```

La aplicación se bloquea antes de crear nada si el checkout está sucio, el
repositorio no es el exacto, falta una aplicación construida, falta la clave o
faltan los identificadores de la GitHub App. Nunca se corrige un bloqueo
ampliando permisos.

Los identificadores de la App se aceptan como variables de máquina solo durante
esta sesión administradora de instalación. El instalador los valida, los guarda
en el enlace privado del servicio y elimina inmediatamente las variables de
máquina. Una reinstalación reutiliza ese enlace privado; si alguien intenta
cambiar sus identificadores, se bloquea para evitar una rotación accidental.
El intermediario rechaza arrancar si vuelve a aparecer cualquier credencial o
identificador del solicitante en su entorno general.

## Comprobaciones posteriores obligatorias

1. `AURORARequester` existe y no pertenece a Administradores.
2. La tarea está oculta, usa una sola instancia y ejecuta únicamente Python 3.14
   con `-I -s -E` y el `.pyz` fijo. Recupera un inicio perdido, puede arrancar
   con batería y no se detiene al pasar a batería.
3. El entorno del cliente y el del intermediario son distintos.
4. El cliente no contiene `requests`, `cryptography`, GitHub ni la clave.
5. La IA puede crear un archivo nuevo en `inbox`, pero no leer, cambiar o borrar
   peticiones ajenas.
6. La IA puede leer recibos, estados y tickets; no puede escribirlos.
7. La IA recibe Acceso denegado al intentar leer `secrets`, `processing`, el
   entorno del intermediario o la definición de la tarea.
8. La App observada pertenece solo al repositorio exacto y no tiene ningún
   permiso adicional.
9. No queda ninguna variable de máquina con el identificador, instalación o
   ruta de clave de la App solicitante; el enlace privado tiene ACL cerrada.
   La lectura posterior comprueba además que las identidades de solo lectura no
   tengan derechos de escritura, borrado, cambio de permisos o toma de posesión.
10. Antes del sello solo existe un ticket de cualificación y ninguno de
   producción. Su cierre terminal no crea una segunda generación de
   cualificación.
11. Un reinicio conserva el mismo ticket, la misma firma y el mismo estado; no
    crea un segundo issue.

## Operación normal

La única orden permitida es:

```text
C:/ProgramData/AURORA/CatalogRequester/client-venv/Scripts/python.exe
  -I -s -E C:/ProgramData/AURORA/CatalogRequester/bin/catalog-requester-client.pyz
  --campaign-key CLAVE_REGISTRADA
```

Una respuesta `pending` o `existing` nunca se repite con otro identificador. El
intermediario conserva los bytes firmados antes de hablar con GitHub. Si se
pierde la respuesta al POST, busca esos mismos bytes en todos los issues del
intervalo, siguiendo páginas válidas del mismo origen. Hasta demostrar si el
issue existe, no hace un segundo POST.

Los fallos temporales de red y una solicitud todavía no visible se reintentan
sin salir del proceso con esperas de 60, 120, 240, 480 y hasta 900 segundos. El
bloqueo local se libera antes de reiniciar el ciclo. Los errores de identidad,
permisos, integridad o configuración no entran en este reintento.
Si GitHub ordena una espera mayor mediante `Retry-After` o el reinicio de cuota,
prevalece esa espera completa; el límite local de 900 segundos nunca provoca un
intento prematuro.
Un `403` solo se considera temporal si GitHub aporta una prueba explícita de
límite de uso (`Retry-After` o cuota restante igual a cero); un `403` de
permisos sigue bloqueando. Los límites de hora se ajustan a la precisión de un
segundo de GitHub para que una petición válida del mismo segundo no se rechace
por sus microsegundos locales.

Cuando ya existe una petición activa, el cliente no crea otra. Si la última
comprobación tiene al menos 60 segundos, puede dejar un único aviso cerrado de
reconciliación. El intermediario comprueba exactamente ese issue, nunca una URL
indicada por el cliente. Las comprobaciones usan ETag, espera creciente de 60 a
900 segundos y un máximo global de 30 consultas por minuto. El sondeo local de
dos segundos no se transforma en sondeo de GitHub.

Solo un cierre con el actor, etiqueta, motivo, título, cuerpo, firma y número
exactos permite publicar el ticket de la generación siguiente. Un cierre
manual, incompleto o alterado conserva la campaña sin ticket nuevo.

Si falta o está dañado el registro local de una campaña, no se presupone que sea
su primera ejecución. El intermediario recorre todas las páginas del historial,
verifica cada petición firmada y exige una única cadena consecutiva. Un hueco,
una bifurcación, una página parcial o una firma no verificable bloquean sin POST.
Un historial abierto restaura el estado activo; un historial terminal permite
exactamente la generación siguiente.

Los archivos locales no válidos se apartan en la zona privada del servicio y
dejan de entrar en el bucle de reintento. Nunca se borran para ocultar el fallo.

## Verificación propia antes de operar

Cliente e intermediario verifican el hash de su `.pyz`, su manifiesto externo,
el manifiesto incluido dentro de la aplicación, la lista cerrada de código y
todos los archivos públicos. El intermediario vuelve a verificar las dos
aplicaciones al arrancar. El cliente solo funciona bajo la cuenta no
administradora `AURORAAgent` y se bloquea si detecta una credencial o sesión de
GitHub CLI.
Si existe el sello de producción, sus hashes deben coincidir con ambas
aplicaciones instaladas. El sello previo de cualificación debe coincidir además
con el único recibo, solicitud firmada, ticket consumido, estado y archivo
terminal reales de la generación 1; un sello aislado o incoherente no habilita
tickets de producción.

El sello de producción debe señalar exactamente el SHA-256 del recibo global
copiado en `receipts/controller-bootstrap-v1.receipt.json`. Cliente,
intermediario y autoauditoría rechazan un recibo ausente, cambiado, enlazado o
con una huella distinta. También exigen JSON canónico, versión 1 y
`result=READY`: hacer coincidir el sello con un recibo `BLOCKED` no habilita
producción. La fecha del sello de producción tampoco puede ser anterior al
cierre permanente de la cualificación.

El instalador guarda una lectura exacta de las ACL de los directorios, binarios,
manifiestos y clave. El intermediario compara esa lectura al arrancar y antes de
cada ciclo que pueda reclamar trabajo. Cualquier cambio produce
`REQUESTER_BROKER_ACL_DRIFT`. Su recibo de autoauditoría solo puede decir
`qualification_only` o `production_sealed`; nunca sustituye el recibo global
`READY`.

## Prohibiciones permanentes

- No ejecutar `scripts/run_catalog_requester_broker.py` desde la IA.
- No usar `gh` como alternativa.
- No entregar a la IA la clave, JWT, token o credencial de la tarea.
- No aceptar repositorio, URL, workflow, commit, ruta, workers o parámetros por
  línea de comandos.
- No editar, comentar ni borrar el issue desde el intermediario.
- No habilitar producción con un bloqueo pendiente.
- No crear un run real durante el bootstrap.
- No volver a crear una generación 1 porque falte un archivo local.
- No consultar GitHub cada dos segundos ni saltarse el límite mediante avisos.

## Respuesta ante problemas

- Duda sobre si GitHub aceptó el POST: mantener `pending`; no repetir.
- Cola llena o no verificable: `REQUEST_BROKER_CAPACITY_UNPROVEN` o
  `REQUEST_BROKER_CAPACITY_EXCEEDED`; cero POST.
- Permisos adicionales: `REQUESTER_APP_OVERPRIVILEGED`; cero POST.
- Clave o cuenta accesible por la IA: `AGENT_REQUESTER_CREDENTIAL_EXPOSED` y
  producción desactivada.
- Cuenta administradora accesible por la IA: `AGENT_ADMIN_CREDENTIAL_EXPOSED` y
  producción desactivada.
