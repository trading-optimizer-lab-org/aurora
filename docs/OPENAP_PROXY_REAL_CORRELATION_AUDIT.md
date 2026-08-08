# Auditor OpenAP: proxies frente a señal oficial

## Objetivo

Medir, para cada proxy de Aurora, si conserva la misma información que la señal oficial de Open Asset Pricing. El resultado principal será la correlación de rangos por empresa y mes, porque el score trabaja con la posición relativa de cada empresa.

## Qué se compara

- Oficial: características firm-level de OpenAP, firmadas según `SignalDoc.csv`, con identificador `PERMNO`.
- Proxy: panel histórico de Aurora con el mismo `PERMNO`, mes y nombre de señal.
- No se comparan sólo medias, medias por decil ni scores finales.

El universo conceptual de OpenAP es de 212 predictores: 209 características
firm-level más Price, Size y STreversal de CRSP. El archivo público de
características no sustituye automáticamente esos tres campos ni convierte el
snapshot actual de Aurora en histórico. El resumen separará `official_212`
de `official_stock_panel_columns` para que una cobertura incompleta no parezca
una correlación calculada.

## Métricas calculadas

1. Pearson agrupado: relación lineal usando todas las observaciones alineadas.
2. Spearman agrupado: relación de rangos usando todas las observaciones; es la métrica principal.
3. Pearson mensual: relación dentro de cada mes.
4. Spearman mensual: relación dentro de cada mes.
5. Media y mediana de Spearman mensual.
6. Número de filas, empresas y meses comunes.

Una proxy sólo pasa el umbral operativo si tiene al menos 60 filas, 12 meses comunes y `spearman_pooled >= 0,95`. El umbral está en YAML y no se confunde con el t-stat de OpenAP.

## Requisito crítico

El snapshot actual de Aurora está indexado por ticker y fecha actual. La descarga oficial de OpenAP está indexada por `PERMNO` y mes histórico. Por eso hacen falta dos entradas adicionales:

- panel histórico de la proxy;
- puente histórico ticker↔PERMNO, con fecha de vigencia.

Sin ambas entradas, el auditor genera un informe `not_computable` y no fabrica correlaciones. Un cruce por orden de filas, nombre, market cap o ticker actual introduciría errores de identidad y survivorship bias.

## Outputs

- `proxy_real_correlation.csv`
- `proxy_real_monthly_correlation.csv`
- `proxy_real_summary.json`
- `proxy_real_failures.csv`
- `proxy_real_manifest.json`

## Estado de la primera ejecución

El contrato declara 44 proxies. Sin embargo, el snapshot actual de Aurora
contiene 62 nombres con `status=proxy`. Esa diferencia no se resuelve
recortando la lista: el informe debe conservar las 62 observadas y marcar
`proxy_count_mismatch=true`. Primero hay que reconciliar el registro de
señales y decidir cuáles son las 44 oficiales de esta auditoría.

El snapshot actual tampoco es un panel histórico: está indexado por ticker y
fecha de actualización. Por tanto no produce correlaciones históricas por sí
solo.

La ejecución debe distinguir entre:

- `complete`: correlaciones calculadas y auditadas;
- `blocked`: falta el panel histórico proxy o el puente de identificadores;
- `fail_threshold`: hay datos alineados, pero no alcanzan 0,95.

`locked_opened` y `validation_used_for_selection` siempre deben ser `false`; esta tarea es una auditoría de datos, no una optimización.
