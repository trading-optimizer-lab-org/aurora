# PROMPT MAESTRO — SOLICITAR UN RUN DE CATÁLOGO AURORA

VERSIÓN: 7.1-CHAT-ENTRY

Este protocolo solo es operativo después de instalar y aceptar la entrada
protegida de esta versión. Su presencia en el repositorio no demuestra READY.

Lee este archivo completo. Solo úsalo cuando el usuario haya pedido de forma
explícita un run nuevo de un catálogo ya registrado.

Tu única decisión editable es `CAMPAIGN_KEY`. No elijas rutas, workflow,
commit, rama, workers, componentes, reintentos, reducción, datos ni parámetros
científicos. Todo eso procede del registro protegido y lo verifica GitHub.

Para solicitar el run:

1. Comprueba que el usuario pidió este run en el mensaje actual.
2. Lee la copia pública instalada en
   `C:/ProgramData/AURORA/CatalogChatSender/catalog_campaign_registry_v1.json`
   y selecciona la única fila
   activa que coincida exactamente con el catálogo pedido. Si coinciden cero o
   más de una, no adivines ni ejecutes: informa
   `BLOCKED_CAMPAIGN_SELECTION_AMBIGUOUS`.
3. Crea un UUIDv4 para esta intención y consérvalo antes de enviar. Recupera
   el mismo ID si se interrumpe la conversación; nunca inventes otro para
   reintentar una solicitud ambigua. Desde HP ejecuta una sola vez el emisor
   público instalado, sin activar un entorno de desarrollo:

   `C:/Python314/python.exe -I -S C:/ProgramData/AURORA/CatalogChatSender/submit_catalog_chat_intent.py --campaign-key CAMPAIGN_KEY --intent-id INTENT_ID`

   Si falta el emisor, el intérprete o el registro, informa
   `BLOCKED_CHAT_ENTRY_NOT_INSTALLED`. No uses el cliente AURORAAgent desde HP,
   no uses el checkout como sustituto y no instales ni pidas UAC para lanzar.
4. Lee la respuesta JSON sin secretos. `pending` solo confirma que se publicó
   la intención local, no que GitHub la aceptó. Si el proceso falla, informa
   de su causa observable y detente; no repitas el envío.
5. Consulta exclusivamente la respuesta del mismo ID en
   `C:/ProgramData/AURORA/CatalogRequester/chat-replies/INTENT_ID.delivery.json`.
   Una respuesta pendiente o todavía ausente nunca autoriza otro envío.
   Si dice `submitted`, `pending` o `existing`, no crees otra solicitud. La
   puerta rápida de GitHub comprobará el recibo `PREPARED`, reservará la
   campaña y arrancará el motor ya preparado.
6. Si dice `blocked`, informa de `reason_code` y detente. No modifiques nada
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

La preparación automática construye datos, entorno, componentes y plan fuera
del run solicitado. La puerta normal solo admite un recibo `PREPARED` vigente,
evita duplicados y arranca el motor optimizado. Los únicos estados públicos son
`PREPARING`, `PREPARED`, `QUEUED`, `RUNNING`, `RECOVERING`, `SUCCESS` y
`BLOCKED`. Una ausencia o duda termina en `BLOCKED`; nunca se duplica trabajo.

No intentes reparar al controlador durante el lanzamiento. Solicita una vez,
observa sin reenviar y exige el recibo científico terminal para declarar éxito.
<!-- solo necesita CAMPAIGN_KEY -->
