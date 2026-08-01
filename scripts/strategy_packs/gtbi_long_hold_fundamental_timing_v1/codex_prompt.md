Quiero que integres y pruebes el pack adjunto `gtbi_long_hold_fundamental_timing_v1` en el repositorio `trading-optimizer-lab-org/aurora`.

Objetivo del nuevo pack:
- El full GTBI V5 anterior terminó completo, pero encontró 0 estrategias válidas y 0 near-misses reales.
- El problema principal fue que las mejores señales cerraban demasiado pronto, tenían mediana de trade 0, dependían de cola derecha y sufrían drawdowns enormes.
- Este nuevo pack debe probar señales de compra/salida con duración media claramente más alta.
- El usuario usará el indicador después de seleccionar compañías por fundamentales. Por tanto, esto es un timing overlay, no una cartera ni un selector fundamental.

Reglas absolutas:
- No tocar locked: `locked_start=2021-01-01`.
- No usar datos posteriores a `2020-12-31`.
- No relajar filtros finales sin aprobación explícita.
- Long/cash solamente.
- Sin short.
- Sin apalancamiento.
- No cartera.
- Ejecución de entrada: next-session open.
- Datos diarios OHLCV.
- GitHub Actions solamente para backtests pesados.
- No full hasta que el smoke sea válido.

Contenido esperado del zip:
- `strategy_pack_long_hold_v1.jsonl`: 72.000 estrategias.
- `strategy_pack_long_hold_v1.csv`.
- `strategy_pack_long_hold_v1_shards/`: 360 shards con 200 estrategias cada uno.
- `concept_catalog.csv`.
- `run_config.json`.

Tarea 1 — Copiar pack al repo:
- Crear carpeta:
  `scripts/strategy_packs/gtbi_long_hold_fundamental_timing_v1`
- Copiar allí los JSONL/shards y metadatos.
- No modifiques el pack salvo para adaptar formato técnico necesario.
- Si el loader actual requiere nombres concretos, crea symlinks/copias compatibles.

Tarea 2 — Soporte de mapeo:
- Revisa si el loader externo soporta el schema `gtbi_external_strategy_long_hold_v1`.
- Si faltan reglas, implementa mapping explícito.
- No ignores reglas silenciosamente.
- Si una regla no se puede soportar, debe ir a `unsupported_strategies.csv` con motivo claro.
- Mantén trazabilidad: strategy_id, family, concept, entry_profile, exit_profile.

Tarea 3 — Mantener duración media alta:
- Añade diagnostics obligatorios:
  - validation_avg_holding_days
  - train_avg_holding_days
  - holding_days_p50
  - holding_days_p75
  - holding_days_p90
  - percent_exits_under_5_days
  - percent_exits_under_10_days
- Penaliza en análisis cualquier candidato con validation_avg_holding_days < 25.
- Reporta aparte candidatos con validation_avg_holding_days >= 30.
- No cambies filtros finales estrictos, pero añade un ranking secundario `long_hold_quality_score`.

Tarea 4 — Scoring secundario específico de este pack:
Crear `long_hold_quality_score` para análisis, sin reemplazar los filtros finales:
- Premiar mediana trade positiva.
- Premiar PF anual estable.
- Premiar validation_positive_years.
- Premiar validation_avg_holding_days entre 30 y 90 días.
- Penalizar drawdown extremo.
- Penalizar mediana 0 o negativa.
- Penalizar percent_exits_under_10_days alto.
- Penalizar profit concentration.

Tarea 5 — Tests locales ligeros:
Ejecuta:
`C:/Python314/python.exe -m pytest tests/test_global_technical_buy_indicator.py -q`

Ejecuta py_compile:
`C:/Python314/python.exe -m py_compile scripts/global_technical_buy_indicator.py scripts/reevaluate_global_technical_buy_indicator_results.py scripts/run_global_technical_buy_indicator_stage.py scripts/merge_global_technical_buy_indicator_results.py scripts/run_global_technical_buy_indicator_external_pack_shard.py scripts/merge_global_technical_buy_indicator_external_pack.py scripts/build_global_technical_buy_indicator_pack.py`

Verifica YAML si tocas workflows.
Verifica que no hay `C:\`, `self-hosted`, ni `runner.temp` inválido.

Tarea 6 — Smoke GitHub, no full:
Lanza solo smoke:
- workflow: `global-technical-buy-indicator-external-pack-360jobs.yml`
- ref: `codex/gtbi-github-only-external-pack-72000`
- `external_strategy_pack_path=scripts/strategy_packs/gtbi_long_hold_fundamental_timing_v1`
- `optimized_evaluation_mode=optimized_evaluation_v5_event_first`
- `candidate_count_per_job=10`
- `candidate_timeout_seconds=300`
- `job_wall_clock_seconds=300`
- `test_mode=true`
- `test_max_jobs=100`
- same data lake: `data_run_id=27936694743`, `data_artifact_name=free-global-yahoo-daily-data-lake`
- dates:
  - `train_end=2010-12-31`
  - `validation_start=2011-01-01`
  - `validation_end=2020-12-31`
  - `locked_start=2021-01-01`

Tarea 7 — Smoke success criteria:
El smoke debe reportar:
- loaded >= 4000
- timed_out = 0
- slow_deferred = 0
- runtime_errors = 0
- unsupported = 0 o justificado
- leaderboard rows = total_strategies_evaluated
- best_candidate_id existe en leaderboard si leaderboard no está vacío
- holding diagnostics presentes
- al menos 60% de las estrategias evaluadas completas deben tener validation_avg_holding_days >= 25, salvo que no haya suficientes evaluadas.

Tarea 8 — Informe final:
Devuelve:
1. Commit SHA.
2. Archivos tocados.
3. Tests ejecutados.
4. Smoke run id y URL.
5. Summary.json.
6. Conteos de filas reales:
   - leaderboard.csv
   - early_rejected_strategies.csv
   - timeout_strategies.csv
   - slow_deferred_strategies.csv
   - runtime_errors.csv
   - unsupported_strategies.csv
7. Holding diagnostics:
   - validation_avg_holding_days p50/p75/p90
   - percent_exits_under_5_days
   - percent_exits_under_10_days
8. Top 20 por long_hold_quality_score.
9. Top 20 por adjusted_return_time_risk con validation_avg_holding_days >= 25.
10. Si hay filtered candidates, tabla top 20.
11. Si no hay filtered candidates, near-misses con foco en mediana positiva, drawdown y holding days.
12. Recomendación: full sí/no.

No lances full hasta que el usuario lo apruebe.
