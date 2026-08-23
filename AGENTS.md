## CATALOG_RUN_PROTOCOL_REQUIRED

Before preparing, launching, monitoring, recovering, or reporting any catalog
run, read `docs/runbooks/CATALOG_RUN_MASTER_PROMPT.md` completely. A model may
only create a strict catalog request. It may not dispatch, cancel, retry, edit,
or bypass a catalog workflow. The GitHub catalog controller is the sole
execution authority. Missing evidence means BLOCKED.
