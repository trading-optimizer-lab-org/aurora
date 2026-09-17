# PROMPT MAESTRO — SOLICITAR UN RUN DE CATÁLOGO AURORA

VERSIÓN: 8.0-CLOUD-ENTRY

Este protocolo solo es operativo después de aceptar el origen remoto, la
custodia protegida y el retiro del emisor anterior. Su presencia en el
repositorio no demuestra READY. OFF significa que no se admiten runs nuevos.

Lee este archivo completo. Solo úsalo cuando el usuario haya pedido de forma
explícita un run nuevo de un catálogo ya registrado.

Tu única decisión editable es `CAMPAIGN_KEY`. No elijas rutas, workflow,
commit, rama, workers, componentes, reintentos, reducción, datos ni parámetros
científicos. Todo eso procede del registro protegido y lo verifica GitHub.

Para solicitar el run:

1. Comprueba que el usuario pidió este run en el mensaje actual.
2. Lee `config/catalog_campaign_registry_v1.json` del main protegido de
   `trading-optimizer-lab-org/aurora`
   y selecciona la única fila
   activa que coincida exactamente con el catálogo pedido. Si coinciden cero o
   más de una, no adivines ni ejecutes: informa
   `BLOCKED_CAMPAIGN_SELECTION_AMBIGUOUS`.
3. Crea un UUIDv4 para esta intención y consérvalo antes de enviar. Recupera
   el mismo ID si se interrumpe la conversación; nunca inventes otro para
   reintentar una solicitud ambigua. Usa únicamente la capacidad del chat/API
   ya acreditada para este repositorio e incidencias. Si su aislamiento no
   está acreditado, informa `BLOCKED_ORIGIN_SCOPE_UNPROVEN`. No sustituyas esa
   capacidad por la sesión administrativa de mantenimiento.
4. Crea UNA incidencia de intención con título exacto
   `[AURORA CATALOG INTENT] INTENT_ID` y cuerpo de JSON puro, sin fences:

   {"schema_version":"1","campaign_key":"CAMPAIGN_KEY","intent_id":"INTENT_ID"}

   Conserva su número/URL. No añadas parámetros, comandos, rutas ni campos.
   Esta incidencia NO es la solicitud científica firmada. El workflow
   protegido autentica el origen y conserva el ticket; solo la App existente
   firma y publica la solicitud científica.
5. Observa esa misma intención y su enlace verificado a la solicitud
   científica. Firmada, publicación incierta y publicada son estados de
   transporte: ninguno equivale a éxito científico. Si se pierde la respuesta
   de creación, busca la intención exacta por ID y autor; no repitas el POST.
   Una ausencia o ambigüedad no autoriza otra intención ni otro ticket.
6. Para reanudar una emisión ya registrada, usa como máximo un comentario
   exacto en la incidencia original: `AURORA_REANUDAR_INTENCION INTENT_ID`.
   No edites título ni cuerpo. La reanudación solo recupera los mismos bytes;
   no vuelve a firmar ni a publicar una solicitud incierta. Una intención
   desconocida no puede originar una emisión mediante ese comentario.
7. Si está bloqueada, informa de la causa observable y detente sin eludirla.
   Para otro run, exige una nueva petición explícita del usuario y un terminal
   verificado del anterior; no avances generaciones por tu cuenta.

Prohibido:

- usar credenciales administrativas, secretos, PEM, tokens de mantenimiento,
  Windows, spool local o UAC para un lanzamiento ordinario;
- invocar, reejecutar, cancelar o despachar workflows;
- crear directamente la incidencia científica firmada, editar intenciones o
  crear incidencias fuera del contrato de intención anterior;
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
