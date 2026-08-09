# Estado de adquisicion de las 149 senales OpenAP

Primera extraccion fail-closed de artefactos ya verificados. No incorpora ninguna
senal al score estricto y no se presenta como resultado final actualizado al 9 de
agosto: la fecha maxima de formacion del lote fuente es el 5 de agosto de 2026.

- Senales objetivo: 149
- Senales con datos adquiridos por ruta gratuita aprobada: 21
- Senales con valor calculado: 16
- Senales aptas para el score estricto: 0
- Reconstruidas pero no estrictas: 11
- Bloqueadas o pendientes: 133
- Filas empresa-senal conservadas: 19117
- Fecha maxima de formacion: `2026-08-05T00:00:00+00:00`

## Recuento por estado

- `blocked_coverage`: 5
- `blocked_fidelity`: 36
- `blocked_source_failure`: 92
- `current_signal_computed`: 16

## Evidencia reproducible

- Run de extraccion: `31333187227`
- Revision exacta: `fee5dc1ce7058e35d7bb52b1393f1817720f0f40`
- Artefacto: `openap-149-acquisition-extract-results` (`9043548042`)
- SHA-256 del artefacto: `a28254d19aee09a4a27511bfd4f7b7088526c192590733aefb0c00ebc3898b73`
- Run fuente de valores: `30995267332`
- Run fuente de formulas: `31331835149`
- SHA-256 de valores fuente: `3cd6da303c0bdff3ba94e776889c6d76e749e988cac3a2e74bf77a62b1b718a6`
- SHA-256 del inventario de formulas: `44de0c0563baace9b4d31118a13ae8a06ea55a87c19ca0ab75841e266efe064d`

La matriz adjunta registra las fuentes permitidas, hashes de formulas oficiales,
fechas point-in-time, cobertura y bloqueo pendiente por senal. La siguiente fase
es refrescar y ampliar las rutas oficiales sin clave, empezando por SEC; hasta
entonces, estos 16 calculos son evidencia intermedia, no el score actual completo.
