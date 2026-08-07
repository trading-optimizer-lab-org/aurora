# Uso futuro de las cinco señales OpenAP

Este documento explica cómo usar `DivSeason`, `AnnouncementReturn`,
`EarningsStreak`, `IndRetBig` y `DelNetFin` con datos actuales sin confundir
un cálculo causal con una señal ya validada.

## Dos modos separados

### `strict`

Es el modo por defecto y el único que debe usarse para el score principal.

Una señal entra en el score sólo si su reconstrucción independiente supera
todas estas pruebas en la validación histórica congelada:

- Pearson >= 0,80.
- Spearman >= 0,80.
- Coincidencia de signo >= 75%.
- Al menos 60 meses comparables.
- `locked_opened=false`.
- `validation_used_for_selection=false`.
- Todos los datos disponibles antes de la fecha de formación.

Si falla una sola prueba, su peso estricto es cero. Que exista un valor para
hoy no cambia esta decisión.

### `advisory`

Permite consultar señales actuales que se han calculado de forma causal y que
tienen la misma variante de fórmula que fue congelada históricamente, aunque
la reconstrucción no haya alcanzado el umbral de certificación.

No es una certificación. Sirve para monitorización, investigación y para un
score separado claramente etiquetado como advisory.

Una fila advisory sólo es utilizable si:

- tiene un valor finito para el símbolo y la fecha solicitada;
- sus datos estaban disponibles antes de la fecha de formación;
- existe un certificado histórico de la misma señal y variante;
- el certificado no viola la política temporal;
- la señal no está marcada como sin datos.

## Peso advisory exacto

El peso se calcula por señal, no por intuición:

```text
correlation_floor = max(0, min(Pearson, Spearman))
sign_factor = min(1, max(0, sign_agreement))
coverage_factor = min(common_months / 60, 1)

advisory_weight = correlation_floor * sign_factor * coverage_factor
```

Ejemplo: Pearson 0,70, Spearman 0,60, signo 0,80 y 48 meses comunes:

```text
min(0,70, 0,60) * 0,80 * (48 / 60) = 0,384
```

La señal puede mostrarse, pero aporta sólo un 38,4% de su peso base en el
score advisory. Una correlación negativa o la falta de meses comparables deja
el peso en cero.

## Cómo ejecutarlo

La ejecución pesada es siempre en GitHub Actions. El workflow es:

```text
OpenAP Five Forward Proxies
```

Para generar el modo estricto:

```text
forward_proxy_mode = strict
```

Para generar también el score advisory actual:

```text
forward_proxy_mode = advisory
```

El workflow publica ambos resultados independientemente del modo solicitado:

- `forward_proxy_score_strict_current.csv`
- `forward_proxy_score_advisory_current.csv`
- `forward_proxy_advisory_current.csv`
- `forward_proxy_validation_metrics.csv`
- `forward_proxy_certificates.jsonl`
- `forward_proxy_source_audit.csv`

## Lectura correcta de los resultados

Para cada señal hay que mirar estas columnas antes de usarla:

- `current_usable`: pasa el modo estricto.
- `forward_advisory_usable`: puede aparecer en modo advisory.
- `forward_advisory_score_weight`: peso histórico reducido.
- `forward_historical_pearson` y `forward_historical_spearman`.
- `forward_historical_sign_agreement`.
- `forward_historical_common_months`.
- `forward_selected_variant`.
- `forward_advisory_reason`.
- `available_at` y `formation_at`.

Interpretación:

| Estado | Uso permitido |
|---|---|
| `certified` | Score principal |
| `advisory_unvalidated` | Sólo score advisory/monitorización |
| `missing_certificate` | No usar |
| `failed_validation_gate` sin valor actual | No usar |
| `invalid_certificate_policy` | No usar |

Nunca se debe interpretar el score como probabilidad de que una acción suba.
Es una puntuación relativa entre acciones elegibles y depende del horizonte
natural de cada señal.

## Qué significa “reconstrucción independiente”

Aurora no copia los valores de OpenAP. Calcula cada fórmula desde fuentes
públicas, conserva hashes y fechas de disponibilidad, y después compara la
cartera reconstruida con la cartera oficial. La correlación histórica mide
si ambas contienen aproximadamente la misma información, no si los números
son visualmente parecidos.

Si la correlación no supera los gates, la señal no se llama fiable. El modo
advisory permite observarla con un peso explícitamente reducido; no convierte
una proxy débil en una réplica exacta.

## Invariantes

- No se usa información posterior a la fecha de formación.
- No se usa validación para escoger reglas, variantes o pesos.
- No se abre locked.
- No se hacen backtests en esta fase.
- Si faltan datos centrales, la señal queda ausente, no se rellena con un
  proxy inventado.
- Al cambiar fórmula, alias, precedencia de fuente o gates hay que repetir la
  validación histórica antes de volver a usar el modo estricto.
