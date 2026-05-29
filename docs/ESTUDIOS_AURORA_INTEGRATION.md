# ESTUDIOS Aurora Integration

## Objetivo

Aurora puede usar el proyecto local ESTUDIOS como fuente de papers para generar ideas de
features y reglas. Esta integracion es evidencia auxiliar, no una promocion automatica de
estrategias.

## Configuracion

Variables soportadas:

| Variable | Uso |
|---|---|
| `AURORA_ESTUDIOS_ROOT` | Ruta al checkout de ESTUDIOS. |
| `AURORA_ESTUDIOS_PYTHON` | Python concreto para ejecutar `python -m estudios`. |

Si no se define `AURORA_ESTUDIOS_ROOT`, Aurora prueba el candidato local
`C:\Users\HP\ESTUDIOS`. Si no existe, el puente queda como no disponible y lo registra.

## Comandos afectados

| Zona | Comportamiento sin ESTUDIOS |
|---|---|
| `research.agent_loop.estudios_bridge` | Devuelve reporte vacio con `estudios_available=false`. |
| `research sp500-route-tournament` | La ruta de papers sigue viva, pero sin ideas si ESTUDIOS falla. |
| `research sp500-literature-build` | Falla de forma explicita porque su objetivo es crear corpus desde ESTUDIOS. |

## Papel en la busqueda

La literatura solo se usa como `train_feature_prior`: orienta grupos de features en train.

No debe:

- abrir locked;
- optimizar validacion;
- usar datos futuros;
- promover una estrategia por si sola.

Los reportes escriben:

- `estudios_available`;
- `estudios_root`;
- `availability_reason`;
- `literature_role`;
- `validation_role`;
- `locked_opened`.

## GitHub

GitHub no tiene `C:\Users\HP\ESTUDIOS`. Para usar esta integracion en CI hay que:

1. clonar o instalar ESTUDIOS en el runner;
2. definir `AURORA_ESTUDIOS_ROOT`;
3. definir `AURORA_ESTUDIOS_PYTHON` si no se usa el Python del sistema.

Si no se hace, los workflows que solo usan el puente deben degradar de forma controlada.
El comando `sp500-literature-build` debe fallar rapido y explicar que falta ESTUDIOS.

## Entorno local QuantForge

Este equipo tambien tiene `trading-lab` instalado en editable y ese proyecto contiene otro
paquete llamado `aurora`. Para que `C:/Python314/python.exe` importe este checkout de
QuantForge, existe el shim local:

```text
C:\Users\HP\AppData\Roaming\Python\Python314\site-packages\000_quantforge_aurora_prefer_editable.pth
```

Ese shim da prioridad al finder editable de QuantForge. Sin el shim, Python puede cargar
`trading-lab\src\aurora` y fallar tests de QuantForge aunque el codigo sea correcto.

## Desactivar evidencia de literatura

En torneo:

```powershell
aurora research sp500-route-tournament --run-id test --feature-mode all --no-costs --no-locked --no-literature-evidence
```

Esto mantiene la ruta, pero no llama a ESTUDIOS ni mezcla ideas externas.
