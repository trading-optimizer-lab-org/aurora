# Plan De Ejecucion: Open Asset Pricing Con YFinance Y SEC EDGAR

## 1. Objetivo

Construir una fuente de datos actual y reproducible para calcular el score Open Asset Pricing de acciones estadounidenses usando:

- YFinance para precios, volumen, acciones corporativas, metadatos actuales y datos de analistas disponibles.
- SEC EDGAR para fundamentales oficiales, fechas de publicacion, formularios y trazabilidad punto en el tiempo.

El resultado debe permitir calcular el mayor numero posible de los 185 predictores estrictos seleccionados, distinguir calculos exactos de proxies y no inventar los datos que ninguna de las dos fuentes ofrece.

Este trabajo prepara datos y calcula el score actual. No abre locked ni ejecuta backtests.

## 2. Estado Local Verificado

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
| Open Asset Pricing | Definiciones, signo, horizonte y evidencia de los 185 predictores |

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
   - horizonte predictivo;
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
3. Respetar el horizonte oficial.
4. Aplicar retrasos causales de publicacion.
5. No rellenar un dato ausente con cero.
6. Clasificar cada resultado:
   - `exact`;
   - `proxy`;
   - `unavailable`;
   - `stale`;
   - `insufficient_data`.
7. Guardar todas las entradas utilizadas para reproducir cada valor calculado.

Cobertura esperada con el mapa actual:

| Estado | Predictores |
|---|---:|
| Calculables directamente | 143 |
| Calculables mediante proxy documentado | 32 |
| No calculables estrictamente con estas dos fuentes | 10 |

Estas cantidades se recalcularan después de inspeccionar realmente todos los campos descargados. No se forzara el resultado para conservar estas cifras.

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
   - estabilidad;
   - costes y liquidez.
6. Limitar el peso máximo de una sola metrica y de una sola familia.
7. Generar scores separados por horizonte:
   - 1 mes;
   - 3 meses;
   - 6 meses;
   - 12 meses;
   - 36 meses.
8. Transformar cada score final a una escala de 0 a 100.
9. Generar un nivel de confianza separado. Un score de 90 no significa 90 por ciento de probabilidad de subida.

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
- el resultado final no conserva trazabilidad hasta sus entradas.

### Fase 10. Publicar La Fotografia Actual

Outputs finales:

- `openap_scores_current.parquet`;
- `openap_features_current.parquet`;
- `security_master.parquet`;
- `coverage_185.csv`;
- `proxy_audit.csv`;
- `unavailable_predictors.csv`;
- `data_quality.csv`;
- `execution_summary.json`;
- `openap_current.duckdb`.

Cada accion mostrara:

- score por horizonte;
- score agregado;
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

- Sin permiso local explícito: preparar y ejecutar mediante GitHub Actions.
- GitHub no puede reutilizar directamente el lago ya almacenado en `C:` y `E:`.
- Para evitar duplicar 20.981.768 filas, la opción más eficiente es una autorizacion expresa para esta ingesta local concreta y escribir directamente en `E:`.
- La autorizacion local, si se concede, sólo se aplicará a esta descarga y construcción del lago.
- Los backtests y optimizaciones seguiran sujetos a la politica GitHub-only.

No se inicia ninguna descarga con este documento.

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
12. Calcular scores por horizonte y confianza.
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
- exista score independiente por horizonte;
- exista nivel de confianza;
- los outputs puedan reconstruirse desde sus fuentes y hashes;
- no se haya usado información futura;
- la fecha de corte quede registrada;
- el informe final detalle cobertura, fallos y limitaciones.

## 10. Decisión Pendiente Antes De Ejecutar

Debe fijarse una de estas rutas:

### Ruta recomendada

Autorizar expresamente esta descarga local para reutilizar el lago existente y escribir directamente en `E:\AURORA_DATA\OPENAP_CURRENT`.

### Ruta GitHub-only

Descargar y construir el lago en GitHub Actions, guardarlo en almacenamiento privado y sincronizarlo después. Esta ruta repite datos que ya existen localmente y necesita almacenamiento cloud configurado.
