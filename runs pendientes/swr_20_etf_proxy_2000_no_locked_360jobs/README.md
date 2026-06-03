# Run pendiente: SWR 20 ETF/proxy 2000 no locked 360 jobs

Estado: preparado, no lanzado automaticamente.

## Objetivo

Buscar 20 estrategias ETF/proxy distintas que intenten sobrevivir a:

- cartera inicial: 100000;
- retirada nominal: 2000 al mes;
- retirada al inicio de cada mes;
- peor mes de inicio posible;
- max drawdown despues de retiradas mejor que -50%;
- train 1995-01-01 a 2010-12-31;
- validacion 2011-01-01 a 2019-12-31;
- locked desde 2020-01-01 totalmente cerrado.

## Archivos

- Config: `config/swr_20_etf_proxy_2000_no_locked_360jobs.yaml`
- Runner: `scripts/run_swr_20_etf_proxy_2000_no_locked.py`
- Workflow: `.github/workflows/swr-20-etf-proxy-2000-no-locked-360jobs.yml`
- Outputs: `outputs/swr_20_etf_proxy_2000_no_locked_360jobs/`

## Diseno GitHub

- 20 familias.
- 18 shards por familia.
- 360 jobs totales.
- 200 configuraciones por shard.
- 72000 configuraciones totales.
- `max-parallel: 360`.
- Sin trigger por push.
- Solo `workflow_dispatch`.

## Guardrails

El run falla si:

- cualquier fecha de datos es `>= 2020-01-01`;
- aparece una accion concreta;
- aparece crypto;
- falta documentacion del proxy;
- se abre locked.

`locked_access_audit.csv` debe marcar:

- `locked_opened=false`;
- `locked_rows_accessed=0`;
- `max_data_date<=2019-12-31`.

## Smoke local

```powershell
python scripts/run_swr_20_etf_proxy_2000_no_locked.py --smoke --output-dir outputs/swr_20_etf_proxy_2000_no_locked_360jobs_smoke
```

## Lanzamiento manual

Desde GitHub Actions, ejecutar:

`SWR 20 ETF Proxy 2000 No Locked 360 Jobs`

Input:

- `smoke=false`

## Nota

El objetivo de 2000 al mes sobre 100000 equivale a 24% anual nominal. Es agresivo de narices. Si `accepted_count=0`, el resultado correcto es decirlo, no maquillarlo.
