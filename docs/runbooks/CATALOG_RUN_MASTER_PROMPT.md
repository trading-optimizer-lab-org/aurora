# PROMPT MAESTRO — SOLICITAR UN RUN DE CATÁLOGO AURORA

VERSIÓN: 6.0-CONTROLLER

Lee este archivo completo. Solo úsalo cuando el usuario haya pedido de forma
explícita un run nuevo de un catálogo ya registrado.

Tu única decisión editable es `CAMPAIGN_KEY`. No elijas rutas, workflow,
commit, rama, workers, componentes, reintentos, reducción, datos ni parámetros
científicos. Todo eso procede del registro protegido y lo verifica GitHub.

Para solicitar el run:

1. Comprueba que el usuario pidió este run en el mensaje actual.
2. Lee `config/catalog_campaign_registry_v1.json` y selecciona la única fila
   activa que coincida exactamente con el catálogo pedido. Si coinciden cero o
   más de una, no adivines ni ejecutes: informa
   `BLOCKED_CAMPAIGN_SELECTION_AMBIGUOUS`.
3. Desde cualquier directorio ejecuta una sola vez el cliente instalado e
   inmutable:

   `C:/ProgramData/AURORA/CatalogRequester/client-venv/Scripts/python.exe -I -s -E C:/ProgramData/AURORA/CatalogRequester/bin/catalog-requester-client.pyz --campaign-key CAMPAIGN_KEY`

4. Lee únicamente el recibo JSON sin secretos que devuelve el cliente.
5. Si dice `submitted`, `pending` o `existing`, no crees otra solicitud. El
   controlador de GitHub continuará, recuperará y finalizará automáticamente.
6. Si dice `blocked`, informa del motivo exacto y detente. No modifiques nada
   para eludirlo.

Prohibido:

- usar credenciales de GitHub, `gh`, navegador o llamadas API para lanzar;
- invocar, reejecutar, cancelar o despachar workflows;
- crear o editar issues manualmente;
- modificar código, contratos, ciencia, datos, permisos o protecciones;
- abrir validation u OOS locked;
- usar runners de pago;
- repetir la solicitud porque tarde o porque el estado sea ambiguo;
- declarar `SUCCESS` por el color de un job o sin el recibo terminal del
  controlador.

El controlador aplica por máquina todas las obligaciones científicas, de
integridad, capacidad, recuperación, cobertura y evidencia de la versión 5.3
archivada. Una ausencia o duda termina en `BLOCKED`; una espera segura termina
en `DEFERRED`; un trabajo equivalente se adopta y nunca se duplica.

No intentes ayudar al controlador. Solicita una vez y respeta su recibo.
<!-- solo necesita CAMPAIGN_KEY -->
