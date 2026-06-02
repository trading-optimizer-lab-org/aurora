# Run Pendiente: Weekly SPY DEHB Real 500 Parallel 1h Momentum Trend

Estado: `pendiente_no_lanzar`.

No se ejecuta hasta orden explicita del usuario.

## Diseno

| Parametro | Valor |
|---|---:|
| Metodo | `dehb_real` |
| Olas logicas | 1 |
| Jobs | 500 |
| Bloques tecnicos | 2 de 250 |
| Paralelo solicitado | 500 |
| Tiempo por job | 50 min |
| Stop automatico | 60 min tras preparar datos |
| Activo operable | `SPY` |
| Features | momentum/trend/similares |
| Crypto | prohibido |
| Locked | cerrado |

## Workflows

- Principal: `Weekly SPY DEHB Real 500 Parallel 1h Momentum Trend`
- Merge: `Weekly SPY DEHB Real 500 Parallel 1h Momentum Trend Merge Now`
- Stop: `Weekly SPY DEHB Real 500 Parallel 1h Momentum Trend Stop`

## Regla de busqueda

Optimiza solo train:

- ganar de media cuando SPY baja;
- ganar en semanas crash de SPY;
- maximizar porcentaje de semanas bajistas ganadas;
- no perder de media cuando SPY sube;
- penalizar drawdown y complejidad.

Validacion solo reporta. Locked no se abre.

## Comando de lanzamiento previsto

```text
gh workflow run weekly-spy-dehb-real-500-parallel-1h-momentum-trend.yml --ref codex/universal-robustness
```

## Merge bajo demanda

```text
gh workflow run weekly-spy-dehb-real-500-parallel-1h-momentum-trend-merge-now.yml --ref codex/universal-robustness -f source_run_id=<RUN_ID>
```

## Stop manual

```text
gh workflow run weekly-spy-dehb-real-500-parallel-1h-momentum-trend-stop.yml --ref codex/universal-robustness -f source_run_id=<RUN_ID>
```
