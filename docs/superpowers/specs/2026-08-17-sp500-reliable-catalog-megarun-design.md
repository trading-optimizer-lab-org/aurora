# Diseño: mega-run SP500 fiable con catálogos prediseñados

**Fecha:** 2026-08-17  
**Estado:** diseño aprobado conversacionalmente; pendiente de revisión escrita  
**Worktree autoritativo:** `C:\Users\HP\AURORA_sp500_search_method_benchmark_short`  
**Rama:** `codex/sp500-search-method-benchmark-short`  
**Ámbito:** SPY como representación operativa del S&P 500, entrenamiento hasta `2010-12-31`

## 1. Objetivo

Diseñar una campaña de búsqueda de estrategias SP500 que sea finita, reproducible, eficiente y resistente a fallos. El sistema deberá probar todas las recetas del catálogo cerrado, conservar todos sus resultados y terminar sin depender de una base de datos central, coordinación dinámica o exploración adaptativa.

La campaña se ejecutará como una sucesión de catálogos cerrados. El primer catálogo se evaluará completamente. Solo después de revisar sus resultados se podrá diseñar otro catálogo. No se lanzará automáticamente una campaña posterior.

La prioridad es reducir el tiempo por estrategia sin introducir la complejidad y los fallos observados en DEHB.

## 2. Límites permanentes

- `search_end=2010-12-31`.
- No abrir, leer, montar ni usar validation `2011-01-01`–`2020-12-31`.
- No abrir, leer, montar ni usar locked `2021-01-01` en adelante.
- Sin subagentes ni horquillas.
- Ejecución científica únicamente en GitHub Actions.
- No usar DEHB, base de datos central, coordinador permanente ni continuación automática.
- No detener el catálogo al encontrar una estrategia buena.
- No rellenar tiempo con duplicados artificiales.
- No deduplicar dos recetas solo porque produjeron las mismas posiciones históricas.
- No cambiar objetivos, datos, señales o reglas después de ver los resultados.

## 3. Arquitectura elegida

Se utilizará un catálogo cerrado por campaña, dividido en bloques estáticos e independientes.

Flujo:

```text
contratos y fuentes
        -> auditoría de familias
        -> catálogo canónico congelado
        -> decisión de preparación por coste/ahorro
        -> bloques estáticos equilibrados
        -> workers independientes
        -> resultados por bloque
        -> unión verificable
        -> objetivos
        -> robustez
        -> informe final
```

Cada worker recibe un bloque fijo. No reclama tareas en una base compartida, no espera nuevas instrucciones y no modifica el catálogo. Un error afecta únicamente al bloque que lo contiene.

El número de trabajos paralelos no se fijará obligatoriamente en 360. Se elegirá entre configuraciones seguras mediante la calibración, buscando la menor duración total sin aumentar innecesariamente la probabilidad de error o la cola de GitHub.

## 4. Catálogo `SP500_ATLAS_1`

El primer catálogo incluirá:

1. Todas las configuraciones individuales válidas de las 240 familias actuales.
2. La inversión exacta de cada estrategia individual.
3. Todas las familias nuevas que superen la auditoría de datos y no dupliquen las actuales.
4. Cruces de dos señales dentro de una misma familia cuando estén autorizados.
5. Cruces de dos señales de familias distintas cuando estén autorizados.
6. Las formas autorizadas de combinación: confirmación, filtro, prioridad, votación y pesos acotados.
7. La inversión exacta de cada cruce no equivalente.
8. Controles simples y estrategias históricas declaradas.

No se incluirán en `ATLAS_1` combinaciones de tres, cuatro o cinco señales. Esas combinaciones se reservarán para `SP500_ATLAS_2`, que se diseñará después de revisar el primer catálogo.

El tamaño no se fijará arbitrariamente. El compilador calculará la cifra exacta después de aplicar cobertura, prohibiciones, equivalencias y deduplicación formal. Si el catálogo fuese demasiado grande para el plan de tiempo, se dividirá en catálogos cerrados sin eliminar recetas por su rendimiento.

La cobertura deberá garantizar:

- presencia de cada familia;
- presencia de cada valor permitido de cada parámetro;
- presencia de cada pareja compatible de valores;
- presencia de cada pareja autorizada de familias;
- presencia de cada composición autorizada;
- presencia de cada dirección normal e inversa;
- cero recetas prohibidas;
- cero recetas no autorizadas;
- cero identificadores con contenidos diferentes.

## 5. Equivalencia y deduplicación

La deduplicación será estricta. Solo se compartirán resultados cuando se pueda demostrar que las dos recetas son la misma función para cualquier combinación posible de entradas bajo el contrato científico vigente.

Se podrán unir, por ejemplo:

- la misma receta escrita dos veces;
- permutaciones que no cambian una operación conmutativa;
- pesos proporcionales que producen exactamente la misma decisión;
- fórmulas que se simplifican a la misma expresión canónica.

No bastará con que dos recetas hayan tomado las mismas posiciones hasta 2010. Si son reglas distintas que solo coincidieron históricamente, se evaluarán por separado.

La comprobación incluirá todas las combinaciones posibles de señales `-1`, `0` y `+1` que puedan emitir los componentes, además de la equivalencia de configuración. La equivalencia quedará ligada al hash del evaluador, contrato, datos de entrenamiento y semántica de valores ausentes.

Si cambia el código científico, la configuración de datos o la forma de tratar una señal, la equivalencia anterior deja de ser válida y se comprueba de nuevo.

## 6. Admisión de familias nuevas

Las 240 familias actuales ya cubren gran parte de precio, volumen, volatilidad, VIX, tipos, crédito, macroeconomía, amplitud, modelos, posicionamiento, eventos y calendario. No se añadirán familias que sean simples renombres o pequeñas variaciones de una familia existente.

Se investigarán, entre otras, estas posibles áreas:

- duración y persistencia de señales;
- acuerdo o conflicto entre escalas diaria, semanal y mensual;
- velocidad y aceleración de tendencias;
- flujos públicos de fondos y financiación;
- emisiones, recompras y compras internas con fecha pública;
- deuda de margen y posicionamiento público adicional;
- opciones, asimetría y estructura de volatilidad si existe historia gratuita verificable;
- reacciones a publicaciones económicas usando la información disponible en cada fecha;
- metadatos públicos de documentos y eventos con fecha causal;
- relaciones entre liquidez, crédito, tipos y participación no cubiertas por el contrato actual.

Una familia solo entrará si:

1. es científicamente distinta;
2. usa datos gratuitos y públicos;
3. tiene suficiente historial anterior a 2011;
4. permite demostrar cuándo estaba disponible cada dato;
5. no usa revisiones futuras como si hubieran estado disponibles entonces;
6. es determinista;
7. tiene una explicación económica comprensible;
8. puede ejecutarse dentro del contrato train-only.

Cada candidata quedará clasificada como `accepted`, `duplicate`, `insufficient_history`, `not_verifiable` o `not_free`. Solo `accepted` se incorpora al catálogo congelado.

## 7. Preparación de componentes y punto de equilibrio

Preparar componentes por adelantado no se considerará automáticamente una mejora. El tiempo de preparación se sumará siempre al tiempo total del primer catálogo.

El planificador comparará:

```text
camino preparado = preparación + evaluación preparada
camino frío = evaluación completa en frío
```

Se elegirá el camino preparado únicamente si el ahorro total esperado compensa el coste de preparación en el catálogo actual y en los catálogos futuros razonablemente previstos.

Reglas:

- Si solo hay un catálogo y la preparación no compensa, se ejecuta en frío.
- Si existe un almacén compatible ya preparado, se reutiliza.
- Si se esperan varios catálogos compatibles, se prepara una sola vez.
- Los componentes preparados se conservan aunque el primer catálogo se ejecute en frío.
- No se hará una segunda construcción completa solo para producir una cifra de velocidad si no se amortiza.
- La preparación y la evaluación se medirán por separado.

La cifra de `component-warm` nunca se presentará como ahorro real sin incluir el coste previo de preparar el almacén.

## 8. Calibración de veinte minutos

Antes de congelar el tamaño del catálogo se ejecutará una calibración con un límite estricto de veinte minutos de tiempo real.

La calibración será una muestra determinista y estratificada que incluya:

- familias actuales y nuevas;
- individuales y cruces;
- recetas normales e inversas;
- preparación de componentes representativos;
- evaluación, almacenamiento y unión parcial;
- reintento controlado de un bloque pequeño.

La muestra no se escogerá por rendimiento. Al alcanzar veinte minutos se detendrá limpiamente, conservará lo medido y no se considerará un fallo.

Registrará:

- tiempo de preparación;
- tiempo de evaluación;
- estrategias físicas;
- resultados reutilizados;
- estrategias por minuto;
- errores y reintentos;
- bytes por resultado;
- memoria y CPU;
- tiempo de guardado y unión.

Con la velocidad observada se calculará el tamaño objetivo:

```text
estrategias objetivo = minutos disponibles x velocidad real x 0,80
```

El factor `0,80` deja un margen del 20 % para colas, fallos, bloques lentos y recuperación.

## 9. Objetivo temporal solicitado

El objetivo de finalización aproximado es el **20 de agosto de 2026 a las 07:31, Europe/Madrid**.

En el cálculo realizado el 17 de agosto de 2026 a las 11:19:50 quedaban aproximadamente **68 horas, 11 minutos y 10 segundos**.

La hora será un objetivo de planificación, no un corte que deje el catálogo incompleto. La prioridad científica acordada sigue siendo terminar el 100 % de las recetas. Si la cola de GitHub o un fallo retrasan el run, se conservarán los resultados y se terminarán los bloques pendientes.

Con los benchmarks existentes, la capacidad teórica para ese intervalo es:

| Camino | Velocidad usada | Capacidad teórica | Capacidad con margen del 20 % |
|---|---:|---:|---:|
| Frío | 8.280 recetas/min | 33,87 millones | 27,10 millones |
| Componentes preparados | 20.509 recetas/min | 83,91 millones | 67,12 millones |

Estas cifras son una referencia del catálogo actual, no una promesa para familias nuevas. La cifra definitiva se calculará después de la calibración de veinte minutos.

No se añadirán duplicados artificiales para ocupar el tiempo disponible.

## 10. Ejecución y recuperación

Antes del run completo:

1. Generar el catálogo dos veces y exigir igualdad byte a byte.
2. Verificar contrato, datos, código, hashes y límites.
3. Certificar las equivalencias formales.
4. Ejecutar la calibración de veinte minutos.
5. Elegir frío o preparado según el punto de equilibrio.
6. Congelar catálogo, componentes, plan de reparto y entorno.
7. Ejecutar un smoke pequeño de preparación, evaluación, almacenamiento y unión.

Durante el run:

- cada bloque será independiente;
- cada bloque tendrá identidad y rango fijo;
- cada resultado se escribirá de forma incremental;
- un worker no podrá modificar el trabajo de otro;
- cada bloque podrá reintentarse como máximo dos veces;
- los bloques correctos no se recalcularán;
- la pérdida de un archivo se detectará por hash y conteo;
- no se abrirá una continuación automática.

Si un bloque falla dos veces, el run se declarará incompleto y conservará todo lo correcto. No se ocultará el fallo ni se marcará como finalizado.

## 11. Resultados y finalización

Se conservarán:

- cada receta del catálogo;
- cada resultado físico;
- cada resultado reutilizado y su origen;
- cada posición o resumen necesario para auditoría;
- tiempos por etapa;
- reintentos y errores;
- conteos por familia, composición y bloque;
- hashes de entradas y salidas.

La unión final solo será válida si:

- están las 100 % de las recetas;
- no hay recetas duplicadas con resultados contradictorios;
- no falta ningún bloque;
- los hashes coinciden;
- el contrato de entrenamiento sigue intacto;
- validation y locked siguen cerrados.

## 12. Tres objetivos principales

Cada estrategia se medirá con:

1. porcentaje de semanas completas con resultado estrictamente positivo;
2. porcentaje de meses completos con resultado estrictamente positivo;
3. número y porcentaje de años completos en los que simultáneamente la estrategia es positiva y supera al SPY.

Los periodos exactamente iguales a cero no cuentan como positivos. Los periodos parciales no se mezclarán con los completos.

No se usará una suma ponderada de los tres objetivos. Se conservará la frontera de estrategias no dominadas: una receta permanece si ninguna otra es igual o mejor en los tres objetivos y mejor en al menos uno.

Retorno anualizado, alpha, rentabilidad acumulada, drawdown, Sharpe y costes podrán conservarse como información descriptiva, pero no decidirán el ganador.

## 13. Robustez equilibrada

La robustez se aplicará después de identificar la frontera de los tres objetivos, usando límites fijados antes de ver resultados.

Fallos de tolerancia cero:

- resultados distintos al repetir la misma receta;
- uso de información no disponible en la fecha de decisión;
- lectura posterior a 2010;
- datos incompletos tratados como datos válidos;
- identidad o resultado no reproducible.

Pruebas de fragilidad:

- retrasar decisiones uno y dos días;
- cambiar cada parámetro al valor válido vecino;
- retirar un año cada vez;
- separar el entrenamiento en tres tramos;
- mover ligeramente las fechas de inicio y fin;
- retirar un componente de los cruces;
- simular pequeños huecos realistas;
- retirar periodos excepcionalmente favorables.

Clasificación:

- `green`: mantiene prácticamente los tres objetivos;
- `amber`: empeora de manera visible pero sigue siendo razonable;
- `red`: pierde más de cinco puntos porcentuales en semanas o meses positivos, o pierde más de un año conjunto positivo y superior al SPY.

Una prueba roja deja la receta como frágil de reserva. Dos pruebas rojas independientes la descartan. Un fallo de tolerancia cero la invalida inmediatamente. Los resultados originales siempre se conservan.

## 14. `SP500_ATLAS_2` y siguientes

Después de cerrar `ATLAS_1`, se revisarán sus resultados y su mapa de robustez. Solo entonces se diseñará `ATLAS_2`, centrado en combinaciones de tres a cinco señales y otras áreas que merezcan profundización.

`ATLAS_2` será otro catálogo inmutable, con su propia calibración, contrato y cálculo de punto de equilibrio. No heredará resultados incompatibles automáticamente.

## 15. Gates de aceptación

El diseño solo se considera listo para implementación cuando se demuestre:

1. catálogo doblemente reproducible;
2. cobertura completa de las recetas declaradas;
3. deduplicación exclusivamente formal;
4. componentes verificables y compatibles;
5. calibración de veinte minutos o menos;
6. decisión explícita de frío frente a preparado;
7. bloques independientes y reanudables;
8. reintentos limitados;
9. unión que rechaza faltas y contradicciones;
10. objetivos exactos y no ponderados;
11. robustez con límites congelados;
12. 100 % de recetas terminadas antes de declarar éxito;
13. `validation_opened=false`;
14. `locked_opened=false`;
15. sin subagentes ni horquillas.

## 16. Fuera de alcance de esta especificación

- implementar código;
- crear o modificar workflows;
- descargar datos nuevos;
- ejecutar la calibración;
- ejecutar el mega-run;
- abrir validation o locked;
- diseñar `ATLAS_2` antes de revisar `ATLAS_1`;
- afirmar que una estrategia es rentable o válida fuera del entrenamiento.

## 17. Próximo paso

Tras revisar este documento, el siguiente paso será crear un plan de implementación separado. La aprobación de esta especificación no autoriza todavía el lanzamiento del run.
