# Plan Y Registro De Ejecucion: Open Asset Pricing Con YFinance Y SEC EDGAR

## 1. Objetivo

Construir una fuente de datos actual y reproducible para calcular el score Open Asset Pricing de acciones estadounidenses usando:

- YFinance para precios, volumen, acciones corporativas, metadatos actuales y datos de analistas disponibles.
- SEC EDGAR para fundamentales oficiales, fechas de publicacion, formularios y trazabilidad punto en el tiempo.

El resultado debe permitir calcular el mayor numero posible de los 185 predictores estrictos seleccionados, distinguir calculos exactos de proxies y no inventar los datos que ninguna de las dos fuentes ofrece.

Este trabajo prepara datos y calcula el score actual. No abre locked ni ejecuta backtests.

## 2. Estado Local Previo Verificado

### YFinance historico

- Ruta principal: `C:\Users\HP\AppData\Local\aurora\prices\free_us_daily`.
- Catalogo DuckDB: `exports\free_us_daily.duckdb`.
- Valores catalogados: 4.693.
- Descargas correctas: 4.400.
- Filas diarias: 20.981.768.
- Ultimo dato del lago principal: 2026-06-18.
- Incluye OHLC, cierre ajustado, volumen, dividendos y splits.
- Incluye metadatos de empresa, sector, industria, bolsa, market cap, acciones, pais y tipo de cotizacion.

### Datos recientes auxiliares

- Ruta: `E:\AURORA_DATA\MRB_EPS_2026`.
- Filas de precios recientes: 4.932.799.
- Simbolos distintos: 15.311.
- Cobertura: 2024-11-01 a 2026-07-24.
- Se usaran para contrastar cobertura y detectar simbolos nuevos, no como universo maestro sin filtrar.

### SEC EDGAR existente

- Objetivos con CIK: 3.674.
- CIK con cache: 3.413.
- CIK descargados adicionalmente: 261.
- Hechos almacenados: 338.942.
- Fallos registrados: 0.
- El contenido actual se centra en acciones en circulacion y metadatos.
- Falta el corpus completo de `companyfacts` y `submissions`.

### Capacidad de almacenamiento

- El disco `C:` no debe recibir el nuevo lago porque tiene poco espacio libre.
- El destino sera `E:\AURORA_DATA\OPENAP_CURRENT`.

## 3. Fuentes Y Responsabilidad

| Fuente | Responsabilidad principal |
|---|---|
| SEC EDGAR | Fundamentales oficiales y fecha real en la que cada dato fue conocido |
| YFinance | Precios, volumen, dividendos, splits y fotografia actual del mercado |
| Open Asset Pricing | Definiciones, signo, periodo oficial de cartera y evidencia de los 185 predictores |

Si Yahoo y SEC discrepan en un fundamental, prevalece SEC. Yahoo no sustituira un dato SEC ausente salvo que el predictor quede marcado expresamente como proxy.

## 4. Estructura De Almacenamiento

```text
E:\AURORA_DATA\OPENAP_CURRENT
|-- raw
|   |-- yfinance
|   `-- sec
|       |-- companyfacts.zip
|       |-- submissions.zip
|       `-- ticker_cik_map.json
|-- lake
|   |-- security_master
|   |-- prices_daily
|   |-- corporate_actions
|   |-- yahoo_current_snapshots
|   |-- yahoo_analyst_snapshots
|   |-- sec_companyfacts
|   |-- sec_submissions
|   |-- openap_features_current
|   `-- openap_scores_current
|-- catalog
|   `-- openap_current.duckdb
|-- manifests
|-- logs
`-- reports
    |-- coverage_185.csv
    |-- data_quality.csv
    |-- proxy_audit.csv
    |-- unavailable_predictors.csv
    `-- execution_summary.json
```

Los datos voluminosos se guardaran en Parquet. DuckDB actuara como catalogo y motor de consulta. Los ZIP originales de SEC se conservaran con hash SHA-256 para garantizar trazabilidad.

## 5. Fases De Ejecucion

### Fase 1. Congelar la especificacion OpenAP

1. Cargar la lista estricta de 185 predictores.
2. Registrar para cada predictor:
   - nombre oficial;
   - formula oficial;
   - direccion economica;
   - periodo oficial de mantenimiento de cartera, sin presentarlo como horizonte predictivo validado;
   - t-stat de reproduccion;
   - t-stat del estudio, si existe;
   - datos necesarios;
   - retraso de publicacion;
   - filtros de universo;
   - coste y dificultad de construccion.
3. Asignar un identificador estable a cada definicion.
4. Guardar el hash de la especificacion usada.

### Fase 2. Construir el universo maestro

1. Descargar el mapa oficial ticker-CIK de SEC.
2. Cruzarlo con el universo Yahoo ya guardado.
3. Resolver cambios de ticker, duplicados y varias clases de acciones.
4. Clasificar cada valor por tipo de instrumento.
5. Mantener como universo de puntuacion acciones comunes operativas de Estados Unidos.
6. Separar ETF, fondos, ADR extranjeros, SPAC, preferred shares y warrants.
7. Guardar exclusiones y motivo en una tabla auditable.

Salida principal: `security_master.parquet`.

### Fase 3. Actualizar YFinance

1. Reutilizar las 20.981.768 filas existentes.
2. Detectar la ultima fecha válida por simbolo.
3. Descargar solamente fechas posteriores.
4. Actualizar dividendos y splits que Yahoo haya corregido.
5. Actualizar metadatos actuales:
   - precio;
   - market cap;
   - acciones en circulacion;
   - sector;
   - industria;
   - bolsa;
   - pais;
   - tipo de cotizacion.
6. Obtener fotografias actuales de:
   - recomendaciones;
   - mejoras y rebajas;
   - objetivos de precio;
   - estimaciones de beneficios;
   - revisiones de EPS;
   - crecimiento esperado;
   - tenedores institucionales disponibles.
7. Guardar fecha y hora de descarga en cada snapshot.
8. Marcar expresamente que los datos de analistas de Yahoo son una fotografia actual y no un historico punto en el tiempo.

No se descargara de nuevo todo el historico salvo que una auditoria detecte corrupcion o huecos no reparables.

### Fase 4. Completar SEC EDGAR

1. Descargar una vez los archivos oficiales `companyfacts.zip` y `submissions.zip`.
2. Calcular y registrar SHA-256, tamaño y fecha de descarga.
3. Extraer todos los CIK presentes en el universo maestro.
4. Conservar por hecho:
   - CIK;
   - taxonomia;
   - etiqueta XBRL;
   - unidad;
   - valor;
   - inicio y fin del periodo;
   - ejercicio fiscal;
   - trimestre fiscal;
   - formulario;
   - accession number;
   - fecha de presentacion;
   - fecha y hora de aceptacion;
   - documento fuente.
5. Normalizar unidades monetarias, acciones y ratios sin modificar el dato raw.
6. Resolver duplicados, enmiendas y formularios posteriores.
7. Conservar el dato original y una vista limpia separada.
8. Generar `available_at` a partir de la aceptacion real del filing.

Un fundamental no podra utilizarse antes de `available_at`.

### Fase 5. Crear conceptos fundamentales canonicos

1. Mapear etiquetas US-GAAP equivalentes a conceptos comunes.
2. Construir, entre otros:
   - activos y pasivos;
   - caja y deuda;
   - ingresos;
   - beneficio neto;
   - flujo operativo;
   - capex;
   - inventarios;
   - cuentas por cobrar;
   - propiedad, planta y equipo;
   - I+D;
   - acciones emitidas y recompradas;
   - dividendos;
   - patrimonio;
   - devengos.
3. Documentar exactamente qué etiquetas alimentan cada concepto.
4. Rechazar mezclas de unidades incompatibles.
5. Marcar empresas con conceptos insuficientes.

### Fase 6. Calcular los 185 predictores

Para cada accion elegible:

1. Usar la formula oficial de OpenAP.
2. Aplicar el signo oficial para que un valor alto tenga la misma interpretacion economica.
3. Respetar el periodo oficial de mantenimiento y no reinterpretarlo como horizonte predictivo.
4. Aplicar retrasos causales de publicacion.
5. No rellenar un dato ausente con cero.
6. Clasificar cada resultado:
   - `exact`;
   - `proxy`;
   - `unavailable`;
   - `stale`;
   - `insufficient_data`.
7. Guardar todas las entradas utilizadas para reproducir cada valor calculado.

Estimacion previa a la descarga:

| Estado | Predictores |
|---|---:|
| Calculables directamente | 143 |
| Calculables mediante proxy documentado | 32 |
| No calculables estrictamente con estas dos fuentes | 10 |

Estas cantidades eran una estimacion y no un criterio de aceptación. La ejecución real dio 75 predictores exactos, 23 proxies documentados y 87 no disponibles. La diferencia procede de exigir que cada formula disponga realmente de todas sus entradas y de no sustituir ausencias por cero.

### Fase 7. Agrupar predictores redundantes

1. Igualar primero la direccion de todas las señales.
2. Detectar formulas practicamente iguales.
3. Calcular similitud historica cuando haya datos suficientes.
4. Detectar tambien señales espejo con correlacion negativa alta.
5. Crear grupos economicos y estadisticos.
6. Dar un solo voto total a cada grupo.
7. Dentro del grupo, usar promedio ponderado:
   - mayor peso para la reproduccion mas fuerte;
   - mayor peso para mejor calidad de datos;
   - mayor peso para mayor estabilidad;
   - menor peso para proxies;
   - peso cero para no calculables.
8. Impedir que varias ventanas de una misma idea multipliquen artificialmente su influencia.

Ejemplo:

```text
Grupo baja negociacion
- zerotrade1M
- zerotrade6M
- zerotrade12M
```

El grupo aporta un voto, no tres.

### Fase 8. Calcular el score actual

1. Comparar cada accion con las demás acciones elegibles en la misma fecha.
2. Convertir cada predictor en un percentil transversal.
3. Agregar primero dentro de grupos redundantes.
4. Agregar después los grupos independientes.
5. Ponderar por:
   - t-stat de reproduccion;
   - evidencia del estudio original;
   - calidad de los datos;
   - disponibilidad exacta o proxy;
   - calidad de la fuente y fidelidad de la formula.
   La estabilidad historica y los costes no se inventan en una fotografia
   actual: quedan como auditorias separadas hasta disponer de validacion
   temporal causal.
6. Limitar el peso máximo de una sola metrica y de una sola familia.
7. Mantener los periodos oficiales 1, 3, 6, 12 y 36 como diagnostico del
   periodo de mantenimiento de cartera de OpenAP. No llamarlos horizontes
   predictivos validados.
8. Calcular un score operativo conjunto con los 185 predictores y convertirlo
   en percentil transversal real de 0 a 100. Con mas de una accion elegible,
   el peor valor es 0 y el mejor 100.
9. Generar un nivel de confianza separado. Un score de 90 no significa 90 por ciento de probabilidad de subida.
10. Conservar tambien `raw_score`, el desglose de contribuciones por predictor,
    grupo redundante y familia, y una vista operable separada por liquidez.

### Fase 9. Auditoria Y Control De Calidad

Se comprobara:

- duplicados de precio y fundamentales;
- fechas futuras;
- huecos de cotizacion;
- splits incoherentes;
- ticker-CIK ambiguo;
- unidades XBRL incompatibles;
- filings enmendados;
- datos obsoletos;
- valores extremos;
- cobertura por predictor;
- cobertura por accion;
- proxies usados;
- predictores imposibles;
- hashes de archivos;
- fecha máxima utilizada.

El proceso fallara si:

- falta el mapa ticker-CIK;
- los ZIP SEC no pasan validacion;
- se detectan datos posteriores a la fecha de corte;
- una formula usa información anterior a `available_at`;
- se etiqueta como exacto un proxy;
- una señal constante o casi constante conserva peso;
- una acción del ranking tiene menos de 60 predictores calculados, mas de 125
  ausentes, confianza inferior a 50 o inputs SEC de mas de 183 dias;
- las contribuciones no reconstruyen exactamente el `raw_score`;
- el score operativo no cubre realmente la escala transversal 0 a 100;
- el resultado final no conserva trazabilidad hasta sus entradas.

### Fase 10. Publicar La Fotografia Actual

Outputs finales:

- `openap_scores_current.parquet`;
- `openap_overall_scores_current.parquet`;
- `openap_score_contributions_current.parquet`;
- `openap_current_leaderboard.csv`;
- `openap_current_deployable_leaderboard.csv`;
- `openap_features_current.parquet`;
- `security_master.parquet`;
- `coverage_185.csv`;
- `proxy_audit.csv`;
- `unavailable_predictors.csv`;
- `data_quality.csv`;
- `execution_summary.json`;
- `openap_current.duckdb`.

Cada accion mostrara:

- score operativo conjunto en percentil 0-100;
- `raw_score` previo al ranking transversal;
- diagnosticos por periodo oficial de mantenimiento;
- confianza;
- predictores exactos disponibles;
- proxies utilizados;
- datos ausentes;
- fecha efectiva del score;
- fecha de la cotizacion;
- fecha del último filing utilizado.

## 6. Frecuencia De Actualizacion

| Componente | Frecuencia |
|---|---|
| Precios Yahoo | Diaria |
| Metadatos Yahoo | Semanal |
| Snapshots de analistas | Semanal |
| SEC Company Facts y Submissions | Diaria antes de calcular el score |
| Score OpenAP | Mensual, tras el último cierre bursátil y con datos ya publicados |

## 7. Politica De Ejecucion

La descarga masiva se considera un run pesado.

- La ingesta, el calculo y la validacion se ejecutaron integramente en GitHub Actions.
- Local sólo se utilizo para descargar e inspeccionar el artifact final en modo lectura.
- No se ejecutaron backtests, optimizaciones, smokes ni tests locales.
- Los backtests y optimizaciones siguen sujetos a la politica GitHub-only.

## 8. Orden De Implementacion

1. Congelar definiciones y cobertura esperada de los 185 predictores.
2. Crear estructura de carpetas y manifiestos.
3. Construir universo maestro ticker-CIK.
4. Implementar actualización incremental de Yahoo.
5. Completar descarga masiva SEC.
6. Normalizar Company Facts y Submissions.
7. Construir conceptos fundamentales canonicos.
8. Implementar predictores exactos.
9. Implementar proxies autorizados y auditados.
10. Marcar no calculables.
11. Agrupar señales redundantes y espejo.
12. Calcular score operativo, diagnosticos por periodo y confianza.
13. Ejecutar validaciones de calidad.
14. Publicar DuckDB, Parquet y reportes.

## 9. Criterios De Aceptacion

El trabajo se considerara completo cuando:

- el universo maestro tenga ticker y CIK auditados;
- Yahoo esté actualizado sin duplicar el historico existente;
- SEC Company Facts y Submissions estén completos para el universo;
- todos los hechos fundamentales tengan `available_at`;
- los 185 predictores tengan estado y motivo;
- ningún proxy figure como calculo exacto;
- los grupos redundantes aporten un solo voto;
- exista score operativo conjunto y los periodos oficiales queden etiquetados
  como diagnosticos, no como horizontes predictivos validados;
- exista nivel de confianza;
- los outputs puedan reconstruirse desde sus fuentes y hashes;
- no se haya usado información futura;
- la fecha de corte quede registrada;
- el informe final detalle cobertura, fallos y limitaciones.

## 10. Estado Historico Sustituido

La siguiente fotografia corresponde a una version anterior. Se conserva solo
como trazabilidad y no debe utilizarse como base del ranking actual. La
reconstruccion semantica v2 debe sustituir estas cifras cuando pase todos los
gates nuevos.

Ejecucion final:

| Campo | Resultado |
|---|---|
| Workflow | `OpenAP Repair SEC Shards And Merge` |
| Run | [30747362913](https://github.com/trading-optimizer-lab-org/aurora/actions/runs/30747362913) |
| Estado | `success` |
| Revision exacta | `742ef71ae7c36f6771c08876b5ddeba3f3cc1680` |
| Fecha efectiva | 2026-08-02 |
| Artifact GitHub | `openap-yfinance-sec-current-score-results`, id `8834009196` |
| Copia local de lectura | `E:\AURORA_DATA\OPENAP_FINAL_30747362913` |
| Tamaño extraido | 1,489 GB |

Resultados:

| Control | Resultado |
|---|---:|
| Universo SEC/Yahoo examinado | 6.741 valores |
| Acciones comunes estadounidenses elegibles | 4.124 |
| Valores excluidos con motivo | 2.617 |
| Filas diarias de precios | 25.021.464 |
| Hechos SEC | 3.563.998 |
| Filas de submissions SEC | 5.575.173 |
| Entradas SEC conservadas por concepto | 424.771 |
| Predictores exactos con algun valor | 75 |
| Predictores proxy con algun valor | 23 |
| Predictores no disponibles | 87 |
| Features calculadas | 762.940 |
| Scores por horizonte | 20.620 |
| Scores agregados | 4.124 |
| Grupos redundantes finales | 150 |

Los 20.620 registros historicos eran cinco diagnosticos por accion asociados a
periodos de mantenimiento. No demostraban cinco horizontes predictivos
independientes.

## 11. Verificacion De Aceptacion

- `locked_opened=false`.
- `backtest_enabled=false`.
- `validation_used_for_selection=false`.
- `partial=false`.
- Cero precios posteriores a la fecha de corte.
- Cero duplicados de precio.
- Todos los hechos SEC y todas las entradas por concepto tienen `available_at`.
- Ninguna acción elegible tiene tipo distinto de `EQUITY`.
- Ninguna acción elegible tiene país Yahoo distinto de `United States`.
- Ninguna acción elegible carece de precio reciente.
- Los 17 archivos del manifiesto final coinciden en tamaño y SHA-256.
- Los manifiestos contienen 48 fragmentos Yahoo, 48 fragmentos SEC y los hashes de las tres fuentes base.
- `zerotrade1M`, `zerotrade6M` y `zerotrade12M` pertenecen al mismo grupo redundante y no reciben tres votos independientes.

## 12. Limitaciones De Uso

Este resultado es una fotografia transversal actual, no un backtest ni una recomendacion de inversion. Un score alto significa atractivo relativo frente al universo en la fecha de calculo; no significa probabilidad de subida.

La cobertura gratuita es incompleta. La fotografia historica anterior tenia una
confianza mediana de 8 sobre 100. La version v2 no permite entrar al ranking con
confianza inferior a 50, menos de 60 predictores calculados, mas de 125 ausentes
o inputs SEC de mas de 183 dias. Aun asi deben revisarse `coverage_185.csv`,
`proxy_audit.csv` y los campos `exact_features`, `proxy_features` y
`missing_features`.

## 13. Outputs Verificados

- `openap_current.duckdb` con 13 tablas consultables.
- `openap_features_current.parquet`.
- `openap_scores_current.parquet`.
- `openap_scores_aggregate_current.parquet`.
- `openap_score_contributions_current.parquet`.
- `openap_current_deployable_leaderboard.csv`.
- `sec_concept_inputs_current.parquet`.
- `security_master.parquet`.
- `security_universe_exclusions.csv`.
- `coverage_185.csv`.
- `proxy_audit.csv`.
- `unavailable_predictors.csv`.
- `data_quality.csv`.
- `source_manifest.csv`.
- `yfinance_source_manifest.csv`.
- `sec_source_manifest.csv`.
- `output_manifest.csv`.
- `execution_summary.json`.
