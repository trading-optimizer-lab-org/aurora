# Run Pendiente: SPY DEHB 500 1h No Long SPY Quality

Estado: pendiente. No lanzar hasta orden explicita del usuario.

## Diseno

- Metodo: `dehb_real`
- Jobs: 500
- Bloques: 2 bloques de 250
- Tiempo por job: 50 minutos
- Watchdog: merge parcial y cancelacion tras 1 hora
- Activo operable: solo `SPY`
- Exposicion permitida: cash o short SPY
- Exposicion prohibida: cualquier long SPY
- Features: momentum/trend/similares con historico suficiente desde 1995
- Crypto: prohibido
- Locked: cerrado
- Validacion: `report_only`

## Mejoras activas

- Deduplicacion durante busqueda por regla y retornos de train.
- Filtro duro de features desde 1995.
- Familias de features por stage.
- Pruning temprano con datos de train.
- Score train multi-metrica con penalizacion de complejidad.
- Robustez simple y blanda reportada.
- Duplicados y portfolio final en merge.

## Lanzamiento manual

```bash
gh workflow run weekly-spy-dehb-real-500-parallel-1h-momentum-trend-no-long-spy-quality.yml --ref <BRANCH>
```

## Merge bajo demanda

```bash
gh workflow run weekly-spy-dehb-real-500-parallel-1h-momentum-trend-no-long-spy-quality-merge-now.yml --ref <BRANCH> -f source_run_id=<RUN_ID>
```

## Stop

```bash
gh workflow run weekly-spy-dehb-real-500-parallel-1h-momentum-trend-no-long-spy-quality-stop.yml --ref <BRANCH> -f source_run_id=<RUN_ID>
```
