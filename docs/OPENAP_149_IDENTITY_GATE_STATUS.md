# OpenAP 149: decision de la puerta de identidad

Estado autoritativo: **`blocked_identity`**.

No se autoriza el piloto de 10 senales ni la incorporacion de ninguna de las
149 senales al score estricto. El bloqueo no significa que las formulas sean
incalculables: significa que, con las fuentes gratuitas y autorizadas
comprobadas, no existe un puente historico amplio, por clase de accion y con
intervalos de vigencia que permita enlazar de forma independiente las empresas
con los PERMNO del panel oficial.

## Evidencia de GitHub Actions

- Run: [31878893909](https://github.com/trading-optimizer-lab-org/aurora/actions/runs/31878893909)
- Evento: `workflow_dispatch`
- Rama: `codex/openap-proxy44-validation`
- HEAD ejecutado: `02f7bdd82e92037cd25675087977a2ef5837d611`
- Resultado del workflow: `success`
- Job `validate`: `success`
- Job `identity_feasibility`: `success`
- Job pesado heredado `audit`: `skipped`
- Artefacto: `openap-149-identity-feasibility-results`
- ID del artefacto: `9245508928`
- Digest del artefacto: `sha256:4df2ae98f23ea99d6536eca9e50f3745d151bbb6f3ae3a0ab44dc57396e14443`
- Tamano descargado declarado: `82645` bytes
- Creado: `2026-08-15T10:13:15Z`
- Caduca: `2026-09-14T10:13:14Z`

El workflow termino verde porque produjo y reconcilio correctamente un no-go
cientifico. `success` no significa que la identidad haya superado la puerta.

## Decision y conciliacion

- Senales objetivo: **149**
- Senales unicas en el registro: **149**
- `unproved`: **142**
- `blocked_source`: **6**
- `not_evaluable_reference`: **1**
- Aprobadas estrictamente: **0**
- Calculadas anteriormente, pero no estrictas: **115**
- Rutas de identidad examinadas: **7**
- Rutas que cumplen todos los requisitos: **0**
- Filas del puente PERMNO: **0**
- Piloto autorizado: **no**
- OOS abierto: **no**
- Valores OpenAP usados para seleccionar identidad: **no**
- Motivo de maquina: `no_authorized_zero_cost_historical_permno_bridge`

## Resultado por ruta gratuita examinada

| Ruta | Por que no supera la puerta |
|---|---|
| SEC company tickers/exchange | No aporta PERMNO, intervalos historicos ni resolucion completa por clase de accion. |
| SEC 13F | No aporta PERMNO y no cubre por si sola el universo amplio requerido. |
| OpenFIGI | No aporta PERMNO ni intervalos historicos PERMNO. |
| Panel stock de OpenAP | Es la fuente objetivo y usarla para construir el enlace seria circular; ademas no aporta identificador publico. |
| CRSP10 | Tiene identidad util, pero no es una ruta publica, gratuita y autorizada para este uso. |
| Field-Ritter IPO | Es gratuito y contiene PERMNO, pero no aporta intervalos historicos ni cobertura amplia. |
| KPSS patent-CRSP | Es gratuito y contiene PERMNO parcial, pero carece de identificador publico enlazable, intervalos y cobertura amplia. |

## Verificacion del artefacto descargado

La inspeccion posterior al workflow confirmo el esquema y los recuentos. El
Parquet vacio conserva las 11 columnas exigidas y su hash coincide con el
manifest.

| Archivo | Bytes | SHA-256 |
|---|---:|---|
| `openap_149_feasibility_register.csv` | 72461 | `ca99e5f44370e8957d93574e9272483aa089a65fd927cf2ed1d288e8fb3635de` |
| `openap_149_feasibility_summary.json` | 281 | `68792ef675eb33db0a04218290a38ab453165f0977c86beb927ac68dfa86e534` |
| `openap_149_feasibility_summary.md` | 359 | `4d1e31131d7f091f5559c6a27f23e7e009d13e5a2e389134e0032ba779c4ebfe` |
| `openap_149_identity_source_audit.csv` | 1610 | `221fe4dcd71e5d0c718be6f141085a3fc001d253a7ef9e7f6199271e018180f2` |
| `openap_identity_gate_decision.json` | 704 | `7bdf3e4ba6439109b659136fdc5ddadf85426e412e8d3e32c6a001917f88dc2a` |
| `openap_permno_bridge_audit.csv` | 46 | `9e8efcd9b44d13483dc0804735ffb56aee1f7dc921c3d455f6c53ac1f5c76439` |
| `openap_permno_bridge_manifest.json` | 190 | `868c996923273ab7ad6b8fa0f7847cfdaee946897cc10c4185bcb5535ef1e695` |
| `openap_permno_bridge.parquet` | 5706 | `46aedf11835bfced73b35b202fc2c36a7ea16b1f2f1a5612dfe13036ecdc73bf` |

## Condicion exacta para reabrir la puerta

Solo se reabre si aparece una fuente nueva, independiente de OpenAP y
autorizada para investigacion que proporcione un historial por clase de accion
entre un identificador publico estable y PERMNO. Tambien valdria acceso
institucional ya licenciado a CRSP/WRDS sin coste marginal para el usuario.

El puente candidato se congelaria antes de leer la referencia y tendria que
alcanzar al menos 70 % de cobertura en **cada mes** de 2023-01 a 2024-12, sin
enlaces ambiguos. Solo despues se podria ejecutar el piloto y exigir, para cada
senal, Spearman mensual fuera de muestra >= 0,90 con cobertura suficiente. Sin
esa identidad no existe una comparacion fiable y no se debe fabricar una cifra
de correlacion.

## Cierre de fase

Se aplica el Outcome A del diseno aprobado: bloqueo demostrado y reproducible.
No se construyen calculadores del piloto, no se lanza otro run y no se integra
ninguna senal en el score estricto.
