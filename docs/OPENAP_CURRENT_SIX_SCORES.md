# OpenAP Current: seis scores operativos

## Salidas

El sistema publica dos horizontes dentro de tres universos de calidad de datos:

| Score | Horizonte | Universo mínimo |
| --- | ---: | ---: |
| `openap_1m_c80` | 1 mes | 80 de 92 métricas disponibles |
| `openap_12m_c80` | 12 meses | 80 de 92 métricas disponibles |
| `openap_1m_c70` | 1 mes | 70 de 92 métricas disponibles |
| `openap_12m_c70` | 12 meses | 70 de 92 métricas disponibles |
| `openap_1m_c60` | 1 mes | 60 de 92 métricas disponibles |
| `openap_12m_c60` | 12 meses | 60 de 92 métricas disponibles |

Los umbrales 80, 70 y 60 cuentan disponibilidad sobre el registro común de 92 métricas. No exigen esa cantidad dentro de cada horizonte. El score 1M usa sólo señales cuyo horizonte oficial OpenAP es un mes; el score 12M usa sólo señales cuyo horizonte oficial es doce meses.

La fotografía auditada que fijó el contrato contenía 366 acciones en C80, 1.250 en C70 y 2.031 en C60. Cada ejecución recalcula y publica los conteos reales.

## Registro de señales

El registro canónico está en `config/openap_current_score_92_signals.txt`. Contiene las 92 métricas que superaban el 10% de cobertura transversal en la auditoría actual. Es un registro congelado para que el significado del score no cambie silenciosamente cuando una API deje de entregar un campo.

## Peso basado en evidencia real

Para cada horizonte se forma:

- un vector `t` con las t-stat de reproducción oficiales;
- una matriz `R` con todas las correlaciones históricas entre las carteras long-short oficiales, después de alinear la dirección de las señales.

Los pesos no negativos, que suman uno, maximizan:

```text
(w' t) / sqrt(w' R w)
```

No se usa un corte manual de correlación, un multiplicador arbitrario para proxies ni un límite manual por familia. Toda la matriz de correlaciones participa. La matriz se proyecta únicamente a una matriz de correlación numéricamente válida antes de resolver los pesos.

## Cálculo de cada score

Para cada universo C80, C70 o C60:

1. Se filtran las acciones por cantidad total de métricas disponibles.
2. Se recalcula el percentil transversal de cada métrica dentro de ese universo.
3. Se respeta el signo oficial OpenAP.
4. Se combinan los percentiles con los pesos de evidencia del horizonte.
5. Las métricas ausentes no se rellenan con cero; se renormaliza el peso disponible.

```text
Score(i,h,C) =
  suma(percentil(i,j,C) * peso(j,h), sólo j disponibles)
  / suma(peso(j,h), sólo j disponibles)
```

El resultado queda entre 0 y 100. Es atractivo relativo frente a las demás acciones de ese universo, no probabilidad de subida.

## Auditoría publicada

Cada fila incluye:

- `total_metrics_available`;
- `metrics_used` dentro del horizonte;
- `exact_metrics_used`;
- `proxy_metrics_used`;
- `weight_coverage_pct`;
- `universe_size`;
- `minimum_total_metrics`;
- `score_id`.

Los artifacts publican además el registro de 92 señales, los pesos por horizonte, la matriz de correlaciones, los seis scores en formato largo y ancho, y los tamaños efectivos de los seis rankings.
