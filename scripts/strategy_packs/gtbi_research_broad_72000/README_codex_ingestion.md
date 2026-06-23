# Aurora GTBI research-broad strategy pack

Pack diseñado para probar estrategias técnicas long/cash por acción en GitHub Actions sin tocar locked.

## Tamaño exacto

- Total de estrategias: 72,000
- Shards para jobs paralelos: 360
- Estrategias por shard: 200
- Conceptos de entrada: 30
- Market overlays: 8
- Microfamilias concepto × overlay: 240
- Variantes por microfamilia: 300
- Variantes por concepto: 2,400
- Variantes por market overlay: 9,000
- Trend profiles: 5
- RS profiles: 5
- Exit profiles: 4
- Aggression profiles: 3

## Estructura determinista

Cada estrategia es una combinación discreta de `concept_id`, `market_overlay_id`, `trend_profile_id`, `rs_profile_id`, `exit_profile_id` y `aggression_id`. No es generación aleatoria: es una taxonomía amplia de setups técnicos documentados, con parámetros concretos y auditables.

## Archivos principales

- `shards/shard_000.jsonl` ... `shards/shard_359.jsonl`: 360 shards exactos de 200 estrategias.
- `codex_360jobs_matrix.csv`: mapping shard_id -> fichero shard.
- `strategy_family_catalog_240.csv`: catálogo de 240 microfamilias.
- `research_source_map.csv`: mapa de fuentes e ideas usadas.
- `strategy_counts_by_*.csv`: controles de distribución.
- `preview_first_500_strategies.csv`: muestra rápida para inspección.
- `omitted_monolithic_files.json`: lista los dos ficheros monolíticos del ZIP que se omitieron porque superan el límite normal de GitHub de 100 MB.

Los monolitos `aurora_gtbi_research_broad_strategies_72000.jsonl` y
`aurora_gtbi_research_broad_strategies_72000.csv` existen en el ZIP original,
pero el workflow usa los shards. No se pierde ninguna estrategia: los 360 shards
contienen las 72,000 estrategias completas.

## Guardrails incluidos en cada estrategia

- `daily_ohlcv_only`
- `signal_at_close_t_entry_next_session_open_if_exists`
- `long_cash_only`
- `no_short`
- `no_leverage`
- `no_portfolio_weights`
- `do_not_load_or_use_data_on_or_after_2021_01_01`
- `train_end = 2010-12-31`
- `validation_start = 2011-01-01`
- `validation_end = 2020-12-31`
- `min_market_cap_usd = 2000000000`

## Uso recomendado

1. Subir el pack como artifact o copiarlo temporalmente al repo.
2. Lanzar 360 jobs en paralelo, uno por `shard_id`.
3. Cada job lee `shards/shard_{shard_id}.jsonl`.
4. El backtester ejecuta cada línea como una estrategia concreta.
5. Fusionar resultados y aplicar filtros duros por validación y train sanity.
6. Hacer seeded neighbourhood solo sobre near-misses robustos.

## Nota

El pack no valida ninguna estrategia por sí mismo. Proporciona candidatos concretos, explicables y trazables para que Aurora los pruebe con sus filtros duros.
