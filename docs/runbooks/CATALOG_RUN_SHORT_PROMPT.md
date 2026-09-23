# AURORA — pedir un catálogo

Úsalo solo después de una orden explícita del usuario para un run nuevo.
Lee y aplica íntegramente `docs/runbooks/CATALOG_RUN_MASTER_PROMPT.md` del `main`
protegido de `trading-optimizer-lab-org/aurora`; esta plantilla no lo sustituye.

1. Resuelve una única campaña activa en `config/catalog_campaign_registry_v1.json`.
   Si no es inequívoca, informa del bloqueo; no adivines parámetros ni campaña.
2. Crea y conserva un UUIDv4 `INTENT_ID` para esta orden antes de enviar nada.
   Ante interrupción o respuesta ambigua, recupera ese mismo identificador.
3. Usa la conexión GitHub ordinaria para crear UNA intención con este título:
   `[AURORA CATALOG INTENT] INTENT_ID`
   Cuerpo: `{"schema_version":"1","campaign_key":"CAMPAIGN_KEY","intent_id":"INTENT_ID"}`.
   Conserva su URL. La App limitada publica la solicitud científica firmada.
4. Consulta esa misma intención y su enlace a la solicitud. Si el envío es incierto,
   busca el ID exacto y su autor; no repitas el POST ni generes otro UUID.
5. Si hace falta reanudar una intención registrada, sigue el comentario exacto del
   protocolo maestro; no edites la intención ni crees otra solicitud.
6. Espera su terminal auténtico. Reabre la publicación y verifica identidad,
   cobertura exacta sin duplicados, recibos y comparador científico.
   Un job verde o una solicitud publicada no bastan para declarar SUCCESS.
7. Entrega resultado, URL y recibo, o la causa concreta del bloqueo sin eludirla.

No cambies ciencia, datos, seeds, periodos, selección, workers, permisos o contratos.
No uses Windows, UAC, secretos, PRs ni despacho manual de workflows científicos.
No uses recursos de pago, no recalcules resultados válidos ni canceles por lentitud.
No avances generaciones: autoridad, ticket, firma y PREPARED se resuelven en GitHub.
No afirmes aislamiento técnico del conector; la ejecución se protege en GitHub/AURORA.
No se requiere ChatGPT Business/Enterprise. OFF no admite runs nuevos.

Ejemplo de orden: «Ejecuta un nuevo catálogo SP500 registrado en AURORA y entrégame
el resultado verificado; usa la ruta cloud ordinaria y conserva la misma intención».
