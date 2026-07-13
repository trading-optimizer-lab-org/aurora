# Diseño: registro sencillo de propfirms

## Objetivo

Crear un único archivo Excel, con una sola hoja, que permita conocer cuánto dinero se ha gastado y cobrado en cuentas de fondeo, el beneficio neto y la rentabilidad acumulada. Codex obtendrá los datos reales desde las áreas privadas de las propfirms indicadas por el usuario; no se inventarán movimientos ni estados.

## Alcance

- Primera propfirm: The5ers.
- Una fila por cuenta en la zona de cuentas.
- Una fila por movimiento de caja en la zona de movimientos.
- Movimientos admitidos: compra, renovación, reembolso y payout.
- No se registrarán operaciones individuales de trading.
- Se admitirán importes en distintas monedas y todos los resúmenes se expresarán en euros.
- El libro será sencillo de ampliar con nuevas cuentas, movimientos y propfirms.

## Estructura de la única hoja

### Panel superior

Mostrará mediante fórmulas:

- Ingresos totales en euros.
- Gastos totales en euros.
- Beneficio neto en euros.
- ROI, calculado como beneficio neto dividido entre gastos totales.
- Número de cuentas activas. Se considerarán activas las que estén en evaluación o financiadas.
- Gráfico mensual de ingresos y gastos.
- Gráfico de beneficio neto acumulado.

### Zona de cuentas

Campos: propfirm, identificador de cuenta, tamaño nominal, moneda base, fase, estado, fecha de compra, fecha de activación y fecha de cierre. El estado se elegirá mediante una lista desplegable con valores como evaluación, financiada, fallida, cerrada y reembolsada.

### Zona de movimientos

Campos: fecha, propfirm, identificador de cuenta, tipo de movimiento, concepto, moneda original, importe original, tipo de cambio a EUR e importe en EUR. El importe en EUR se calculará mediante fórmula. Compra y renovación se tratarán como gastos; reembolso y payout, como ingresos.

Los importes originales se introducirán siempre como números positivos. La clasificación del tipo de movimiento determinará su tratamiento en los resúmenes, evitando signos manuales incoherentes.

## Conversión de divisas

El tipo de cambio será editable en cada movimiento para conservar el valor realmente aplicado en la fecha del cargo o cobro. Expresará cuántos euros equivale una unidad de la moneda original. El importe en EUR será el importe original multiplicado por ese tipo. Para movimientos denominados en EUR, el tipo será 1.

## Obtención de datos

Para cada propfirm, Codex abrirá una pestaña nueva de su propiedad y trabajará en segundo plano, sin reutilizar pestañas del usuario ni cambiar el foco de ventana. Si el sitio requiere inicio de sesión, CAPTCHA o doble factor, Codex se detendrá y pedirá al usuario que complete esa acción manual. Tras la confirmación del usuario, Codex extraerá únicamente la información necesaria de cuentas y movimientos.

La información disponible se contrastará, cuando sea posible, entre el historial de cuentas y el historial de pagos. Los campos que la plataforma no muestre se dejarán vacíos y se señalarán como pendientes; no se deducirán sin base.

## Controles y avisos

- Listas desplegables para propfirm, fase, estado, tipo de movimiento y moneda.
- Aviso visual en filas incompletas que carezcan de fecha, cuenta, tipo, importe o tipo de cambio.
- Identificación visual discreta de cuentas fallidas o cerradas.
- Protección frente a división por cero en el cálculo del ROI.
- Sin celdas con errores de fórmula.

## Comprobación y entrega

Antes de entregar el archivo se comprobarán las fórmulas, los totales, los gráficos y la legibilidad de toda la hoja. Se revisará que el total de movimientos extraídos coincida con lo visible en la propfirm para el periodo accesible. El resultado final será un único archivo `.xlsx` listo para seguir añadiendo datos.
