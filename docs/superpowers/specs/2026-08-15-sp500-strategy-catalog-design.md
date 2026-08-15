# Diseño del catálogo inicial de estrategias SP500

**Fecha:** 2026-08-15  
**Estado:** aprobado para especificación  
**Worktree autoritativo:** `C:\Users\HP\AURORA_sp500_search_method_benchmark_short`  
**Rama:** `codex/sp500-search-method-benchmark-short`

## 1. Objetivo

Crear un catálogo independiente, determinista y revisable de estrategias SP500
completamente definidas. El catálogo cubrirá los 240 carriles ejecutables del
contrato congelado y las 14 reglas de cruce ya aprobadas. Servirá como inventario
de estrategias candidatas; la decisión sobre cómo conectarlo a DEHB se tomará
después y queda expresamente fuera de este trabajo.

El catálogo no ejecutará backtests, no contendrá métricas de rendimiento y no
alterará ni detendrá la campaña continua que está funcionando. Su única fuente
científica será el contrato congelado hasta `2010-12-31`.

## 2. Límites innegociables

- `search_end=2010-12-31`.
- `validation_opened=false` y ninguna lectura o montaje de 2011-2020.
- `locked_opened=false` y ninguna lectura o montaje de 2021+.
- Sin subagentes ni horquillas.
- Sin costes, drawdown, Sharpe ni nuevos objetivos.
- Posición diaria binaria: comprado `+1` o vendido `-1` en SPY.
- Empates, ausencia de señal y valores no disponibles conservan la posición
  anterior; la posición inicial sigue el contrato vigente.
- Solo se utilizarán carriles, parámetros, prohibiciones y cruces presentes en
  `config/sp500_megarun_feature_contract_240.json`.
- No se añadirán datos, fórmulas ni familias. Las únicas semánticas nuevas del
  catálogo son las composiciones fijadas de forma exhaustiva en la sección 7.

## 3. Artefactos finales

El catálogo versionado vivirá en:

`config/sp500_megarun_strategy_catalog_v1/`

Contendrá:

1. `catalog.jsonl`: fuente de verdad canónica y legible por máquina; una
   estrategia por línea.
2. `catalog.csv`: vista humana plana con los parámetros complejos serializados
   como JSON canónico.
3. `manifest.json`: identidad del catálogo, hashes de entradas y salidas,
   recuentos, límites, rechazos y estado de aceptación.
4. `coverage.json`: prueba completa de cobertura por carril, parámetro, pareja
   de parámetros, regla de cruce, composición, aridad y pareja de carriles.
5. `README.md`: explicación breve de cómo interpretar el catálogo sin afirmar
   que sus estrategias sean rentables.

El generador y su validación se diseñarán como unidades separadas:

- `infra/sp500_megarun/strategy_catalog.py`: modelos, generación, cobertura,
  canonicalización y validación.
- `scripts/build_sp500_megarun_strategy_catalog.py`: interfaz de construcción.
- `tests/test_sp500_megarun_strategy_catalog.py`: aceptación reproducible.

## 4. Esquema de una estrategia

Cada fila de `catalog.jsonl` tendrá, como mínimo:

- `schema_version`;
- `strategy_id`, derivado de un hash de dominio y del contenido científico;
- `strategy_kind`: `single` o `cross`;
- `components`, en orden canónico;
- para cada componente: `lane_id`, configuración exacta y hash de configuración;
- `composition` y sus parámetros, o `identity` en estrategias individuales;
- `cross_rule_ids` que autorizan el cruce;
- `economic_rationale` copiada del contrato, nunca inventada por el generador;
- `feature_count` entre 1 y 5;
- `initial_fidelity=1` como recomendación declarativa, sin ejecutar nada;
- etiquetas de cobertura que justifiquen por qué existe la fila;
- hashes del contrato de features y de la receta científica;
- `search_end`, `validation_opened` y `locked_opened`;
- `performance_status="not_evaluated"`.

Dos filas con el mismo contenido científico deben tener el mismo
`strategy_id`. Un mismo identificador con contenidos distintos abortará la
construcción.

## 5. Catálogo de estrategias individuales

Para cada uno de los 240 carriles se cargará su `ConfigSpace` exacto, incluidas
las prohibiciones vigentes. El generador construirá todas las configuraciones
discretas candidatas del carril, rechazará las inválidas y seleccionará un
conjunto mínimo reproducible que cubra:

1. la configuración por defecto;
2. cada valor permitido de cada parámetro al menos una vez;
3. cada pareja compatible de valores pertenecientes a parámetros distintos al
   menos una vez;
4. los controles históricos congelados;
5. las direcciones, horizontes, umbrales y confirmaciones existentes en el
   contrato, sin añadir niveles nuevos.

La selección será un set-cover codicioso determinista:

1. se enumeran todos los requisitos de cobertura válidos;
2. se elige la configuración que cubre más requisitos pendientes;
3. los empates se resuelven por JSON canónico ascendente;
4. se repite hasta que no queda ningún requisito;
5. si un requisito válido queda sin cubrir, la construcción falla.

El espacio cartesiano individual bruto del contrato vigente suma 55.763
configuraciones antes de aplicar prohibiciones. Contiene 18.340 requisitos
brutos de parejas de valores. Estas cifras son límites de auditoría, no el
tamaño prometido del catálogo: el tamaño final será el mínimo producido por la
cobertura y las restricciones reales.

## 6. Catálogo de estrategias cruzadas

Solo se admitirán cruces autorizados por las 14 reglas `CR01`-`CR14`. Se
expandirán los rangos de carriles de cada regla y se eliminarán carriles
repetidos dentro de una estrategia.

### 6.1 Cobertura obligatoria

El catálogo cruzado cubrirá:

- cada regla;
- cada composición permitida por esa regla;
- cada aridad desde 2 hasta `max_features`;
- cada carril permitido en cada función que pueda ocupar;
- cada pareja compatible izquierda-derecha al menos una vez por composición;
- cada valor de parámetro de un componente al menos una vez dentro de algún
  cruce en el que ese carril participe;
- ablaciones estructurales: cada componente individual ya estará presente en
  la sección individual y cada cruce conservará su referencia a esos
  componentes.

El contrato vigente contiene 26.480 combinaciones brutas de regla, pareja
izquierda-derecha y composición antes de deduplicar solapamientos entre reglas.
Las aridades de 3 a 5 se generarán mediante cobertura por parejas, no mediante
el producto cartesiano total.

### 6.2 Selección para aridades de 3 a 5

Para cada regla y aridad se construirá una matriz de cobertura determinista:

1. al menos un componente procederá del lado izquierdo y otro del derecho;
2. ninguna estrategia repetirá un `lane_id`;
3. se respetará el máximo de componentes de la regla;
4. cada pareja izquierda-derecha autorizada por la regla aparecerá al menos
   una vez;
5. las configuraciones individuales de cada carril rotarán en orden canónico
   hasta cubrir todos sus valores de parámetros dentro del catálogo cruzado;
6. los empates se resolverán por la representación canónica completa.

No se formará el producto de todas las configuraciones de todos los
componentes. Esa expansión no aportaría una garantía de cobertura adicional y
crearía una cantidad inabarcable de variantes casi iguales.

## 7. Semántica declarativa de las composiciones

Todas las composiciones reciben decisiones componentes en
`{-1, 0, +1}`, donde `0` significa conservar la posición anterior.

- `and`: emite `+1` si los `N` componentes emiten `+1`, emite `-1` si los `N`
  componentes emiten `-1` y emite `0` en cualquier otro caso.
- `gate`: el primer componente es la señal base. Los demás deben confirmar la
  misma dirección no nula para dejarla pasar; si no, emite `0`.
- `override`: usa la señal base salvo cuando el componente de prioridad emite
  una señal no nula; en ese caso prevalece la señal de prioridad. La función de
  prioridad será el último componente y queda explícita en la fila.
- `vote`: `majority` emite una dirección solo cuando más de la mitad de los
  `N` componentes votan esa dirección; `unanimity` exige los `N` votos. Un
  empate o falta de quórum emite `0`.
- `weighted_score`: suma decisiones con pesos discretos del contrato, normaliza
  por la suma de valores absolutos y emite el signo del resultado. Un resultado
  exacto de cero emite `0`.

Los pesos se limitarán a `{-2, -1, -0.5, 0.5, 1, 2}`. Se canonicalizarán para
eliminar múltiplos equivalentes y se fijará el primer peso no nulo como positivo
cuando la inversión global ya esté representada por la dirección de los
componentes. La cobertura de pesos será por parejas y no por producto
cartesiano. No habrá pesos continuos libres.

## 8. Deduplicación

La construcción eliminará:

- JSON científicos idénticos;
- configuraciones prohibidas;
- repeticiones causadas por rangos solapados entre reglas;
- permutaciones equivalentes de composiciones conmutativas;
- pesos proporcionales equivalentes;
- cruces que, tras canonicalizar, sean iguales a una estrategia individual.

Cada eliminación conservará su procedencia en `manifest.json`. La equivalencia
de posiciones no puede demostrarse sin calcular señales sobre datos y, por
tanto, no se afirmará durante esta fase. Esa deduplicación queda para una futura
ejecución autorizada.

## 9. Flujo de construcción

1. Leer exclusivamente los contratos de configuración versionados.
2. Verificar hashes, 240 carriles ejecutables y límites cerrados.
3. Construir y validar los espacios individuales.
4. Generar el conjunto mínimo de cobertura individual.
5. Expandir y validar las 14 reglas de cruce.
6. Generar parejas y matrices de cobertura de aridad superior.
7. Canonicalizar y deduplicar.
8. Verificar cobertura completa.
9. Escribir primero en un directorio temporal.
10. Releer todos los artefactos, recalcular sus hashes y promoverlos de forma
    atómica al directorio final.

La salida se ordenará por `strategy_kind`, regla, aridad, carriles,
composición y `strategy_id`. Dos ejecuciones sobre el mismo commit producirán
exactamente los mismos bytes.

## 10. Fallos y cierre seguro

La construcción termina sin publicar catálogo si ocurre cualquiera de estos
casos:

- límites de datos abiertos o fecha posterior a 2010;
- contrato, carril, operador o composición desconocidos;
- configuración prohibida incluida;
- requisito de cobertura pendiente;
- estrategia con más de cinco componentes;
- cruce no autorizado por ninguna regla;
- colisión de identificador con contenidos diferentes;
- hash de salida distinto tras releer;
- orden o serialización no deterministas.

El informe de error podrá escribirse fuera del directorio final, pero nunca se
marcará el catálogo como aceptado parcialmente.

## 11. Pruebas de aceptación

1. Generación byte a byte reproducible entre procesos y reinicios.
2. Cobertura de los 240 carriles y de todos sus valores permitidos.
3. Cobertura de todas las parejas compatibles de parámetros individuales.
4. Rechazo de todas las parejas y tríos prohibidos del `ConfigSpace`.
5. Cobertura de las 14 reglas, cada composición y cada aridad autorizada.
6. Cobertura de cada pareja izquierda-derecha autorizada por composición.
7. Ausencia de identificadores o contenidos científicos duplicados.
8. Canonicalización correcta de permutaciones y pesos equivalentes.
9. Igualdad entre `catalog.jsonl`, `catalog.csv`, `coverage.json` y los
   recuentos del manifiesto.
10. Pruebas de fallo ante artefactos alterados o contratos incompatibles.
11. `search_end=2010-12-31`, `validation_opened=false` y
    `locked_opened=false` en todas las filas y artefactos.
12. Prueba que demuestre que el generador no importa ni abre datos de mercado.

## 12. Fuera de alcance

- decidir cómo introducir el catálogo en DEHB;
- modificar, cancelar o reiniciar la campaña actual;
- ejecutar estrategias o calcular rendimientos;
- deduplicar por posiciones observadas;
- seleccionar ganadores;
- abrir validación 2011-2020 o locked 2021+;
- añadir señales o fuentes distintas de las 240 familias congeladas;
- cambiar la función objetivo o las reglas de robustez.

## 13. Criterio de finalización

El catálogo estará creado cuando los cinco artefactos finales existan, sus
hashes coincidan, todas las pruebas de cobertura pasen y no haya filas
duplicadas o no autorizadas. La finalización no implicará que ninguna estrategia
sea buena ni que el catálogo esté integrado en una campaña.
