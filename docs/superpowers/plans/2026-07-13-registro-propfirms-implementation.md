# Registro de propfirms Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extraer de The5ers las cuentas y movimientos disponibles y entregar un Excel de una sola hoja con resúmenes y gráficos actualizables.

**Architecture:** La extracción se realizará en una pestaña nueva de Chrome propiedad del agente y se normalizará en un JSON local. Un único constructor JavaScript leerá ese JSON, generará la hoja `Registro` con `@oai/artifact-tool`, comprobará fórmulas y gráficos y exportará el `.xlsx` final.

**Tech Stack:** Chrome browser-client en segundo plano, JavaScript ESM, `@oai/artifact-tool` 2.8.6+, fórmulas nativas de Excel.

## Global Constraints

- No cambiar el foco, activar ventanas ni reutilizar pestañas abiertas por el usuario.
- El login, CAPTCHA y 2FA los completa el usuario; Codex nunca solicita ni escribe contraseñas.
- No inventar cuentas, fechas, estados, importes ni movimientos.
- Incluir solo compras, renovaciones, reembolsos y payouts; excluir operaciones individuales de trading.
- Mantener una sola hoja visible llamada `Registro`.
- Expresar los resúmenes en EUR; usar el cambio mostrado por The5ers y, si falta, el cambio diario oficial del BCE con indicación de la fuente.
- Usar exclusivamente el Node.js y `node_modules` proporcionados por `load_workspace_dependencies`.
- Guardar el resultado en `outputs/019f5b3d-4c9c-79e2-a6df-f7601abb2125/registro_propfirms.xlsx`.

---

### Task 1: Obtener y normalizar los datos de The5ers

**Files:**
- Create: `outputs/019f5b3d-4c9c-79e2-a6df-f7601abb2125/the5ers_data.json`

**Interfaces:**
- Consumes: sesión autenticada de The5ers facilitada manualmente por el usuario.
- Produces: JSON con `source`, `accounts` y `movements` para el constructor del libro.

- [ ] **Step 1: Abrir una pestaña nueva del agente en segundo plano**

Ejecutar con el controlador persistente de Chrome, sin reclamar ninguna pestaña existente:

```js
await chrome.nameSession("🔎 Registro The5ers");
globalThis.the5ersTab = await chrome.tabs.new();
globalThis.the5ersHandoffId = the5ersTab.id;
await the5ersTab.goto("https://the5ers.com/");
nodeRepl.write(await the5ersTab.playwright.domSnapshot());
```

Expected: la instantánea pertenece a `the5ers.com` y la pestaña no toma el foco.

- [ ] **Step 2: Llegar al acceso usando solo elementos observados**

Obtener una lista acotada de enlaces candidatos y mostrarla. Continuar solo si hay un único candidato; después usar exactamente su atributo `href` y confirmar `count() === 1`. Si aparece login, conservar la pestaña para el usuario y detener la ejecución:

```js
const loginCandidates = await the5ersTab.playwright.evaluate(() =>
  Array.from(document.querySelectorAll("a")).slice(0, 200).map((a) => ({
    href: a.getAttribute("href"),
    text: a.textContent?.trim() ?? "",
  })).filter((a) => a.href && /login|log in|sign in|dashboard|client area/i.test(`${a.text} ${a.href}`))
);
nodeRepl.write(loginCandidates);
if (loginCandidates.length !== 1) throw new Error("No hay un único enlace de acceso verificable");
const loginHref = loginCandidates[0].href;
const loginLink = the5ersTab.playwright.locator(`a[href=${JSON.stringify(loginHref)}]`);
if (await loginLink.count() !== 1) throw new Error("El enlace de acceso no es único");
await loginLink.click();
await chrome.tabs.finalize({ keep: [{ tab: the5ersTab, status: "handoff" }] });
```

Expected: el usuario recibe una petición clara para iniciar sesión, completar 2FA/CAPTCHA si procede y responder `listo`.

- [ ] **Step 3: Recuperar únicamente la pestaña creada por el agente**

Tras la confirmación del usuario, reclamar la misma pestaña por su identificador guardado:

```js
const openTabs = await chrome.user.openTabs();
const handoffInfo = openTabs.find((item) => item.id === the5ersHandoffId);
if (!handoffInfo) throw new Error("No se encuentra la pestaña de The5ers creada por el agente");
globalThis.the5ersTab = await chrome.user.claimTab(handoffInfo);
nodeRepl.write({ title: await the5ersTab.title(), url: await the5ersTab.url() });
```

Expected: la URL pertenece a The5ers y la página muestra una sesión autenticada.

- [ ] **Step 4: Extraer cuentas e historial de pagos**

En cada vista, tomar una instantánea nueva, usar solo enlaces y contenedores observados y exigir un locator único. Extraer tablas o tarjetas con una única evaluación acotada al contenedor identificado:

```js
const rows = await exactContainer.evaluate((element) =>
  Array.from(element.querySelectorAll("tr, [role='row']")).slice(0, 500).map((row) =>
    Array.from(row.querySelectorAll("th, td, [role='cell']")).map((cell) => cell.textContent?.trim() ?? "")
  )
);
```

Recorrer, si existen, las vistas de cuentas, historial de pedidos/facturas y payouts. Para paginación, usar únicamente un control `Siguiente` observado, comprobar que sea único y detenerse cuando quede deshabilitado. Contrastar el número de filas extraídas con el total visible.

- [ ] **Step 5: Normalizar y guardar el contrato de datos**

Usar `null` para campos que The5ers no muestre. Los importes originales son positivos y `type` solo admite `Compra`, `Renovación`, `Reembolso` o `Payout`. Este es el contrato exacto:

```ts
type IsoDate = `${number}-${number}-${number}`;
type AccountStatus = "Evaluación" | "Financiada" | "Fallida" | "Cerrada" | "Reembolsada";
type MovementType = "Compra" | "Renovación" | "Reembolso" | "Payout";

type TrackerData = {
  source: {
    propfirm: "The5ers";
    retrievedAt: string;
    accountUrl: string | null;
    paymentsUrl: string | null;
  };
  accounts: Array<{
    propfirm: "The5ers";
    accountId: string;
    size: number | null;
    currency: string | null;
    phase: string | null;
    status: AccountStatus;
    purchaseDate: IsoDate | null;
    activationDate: IsoDate | null;
    closeDate: IsoDate | null;
  }>;
  movements: Array<{
    date: IsoDate;
    propfirm: "The5ers";
    accountId: string | null;
    type: MovementType;
    concept: string;
    currency: string;
    amountOriginal: number;
    fxToEur: number | null;
    fxSourceUrl: string | null;
  }>;
};
```

Guardar el objeto con `JSON.stringify(data, null, 2)` mediante el módulo `node:fs/promises`. Expected: todos los movimientos tienen fecha, tipo, moneda e importe positivo; las ausencias están representadas por `null`, no por valores deducidos.

- [ ] **Step 6: Completar los cambios de divisa que falten**

Consultar la serie histórica oficial del BCE para cada combinación de fecha y moneda faltante. Convertir cada cotización a `euros por una unidad de la moneda original`; si la fecha no es hábil, usar el último dato anterior e indicar esa fecha en `fxSourceUrl`. Para EUR, usar `fxToEur: 1`.

Expected: cada movimiento tiene `fxToEur > 0`; las cotizaciones de referencia conservan una URL oficial del BCE.

- [ ] **Step 7: Finalizar el navegador**

```js
await chrome.tabs.finalize({ keep: [] });
```

Expected: se cierra la pestaña de extracción creada por el agente y no se altera ninguna pestaña del usuario.

---

### Task 2: Construir el Excel de una sola hoja

**Files:**
- Create: `outputs/019f5b3d-4c9c-79e2-a6df-f7601abb2125/build_propfirm_tracker.mjs`
- Create: `outputs/019f5b3d-4c9c-79e2-a6df-f7601abb2125/registro_propfirms.xlsx`

**Interfaces:**
- Consumes: `the5ers_data.json` con el contrato de Task 1.
- Produces: un libro con una hoja `Registro`, tablas `CuentasTable` y `MovimientosTable`, KPIs y dos gráficos.

- [ ] **Step 1: Preparar el entorno aislado del constructor**

Crear en la carpeta de salida una unión `node_modules` al directorio indicado por `load_workspace_dependencies`. No modificar el directorio proporcionado.

Run:

```powershell
New-Item -ItemType Junction -Path "outputs\019f5b3d-4c9c-79e2-a6df-f7601abb2125\node_modules" -Target "C:\Users\HP\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules"
```

Expected: la unión existe y resuelve `@oai/artifact-tool` sin instalar paquetes.

- [ ] **Step 2: Crear el esqueleto del constructor**

El archivo debe importar únicamente APIs documentadas, leer el JSON y crear una sola hoja:

```js
import fs from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const outputDir = fileURLToPath(new URL(".", import.meta.url));
const data = JSON.parse(await fs.readFile(`${outputDir}/the5ers_data.json`, "utf8"));
const workbook = Workbook.create();
const sheet = workbook.worksheets.add("Registro");
sheet.showGridLines = false;
sheet.freezePanes.freezeRows(1);
await workbook.comments.setSelf({ displayName: "User" });
```

- [ ] **Step 3: Escribir el panel, las cuentas y los movimientos**

Usar este mapa estable:

- Título y fuente: `A1:L2`.
- Cinco KPI: `A4:J6`.
- Gráficos: `A9:F22` y `G9:L22`.
- Cuentas: cabecera `A25:I25`, datos `A26:I75`.
- Movimientos: cabecera `A79:M79`, datos `A80:M379`.
- Ayuda mensual auditable: `O25:S85`.

Las fórmulas de la primera fila de movimientos serán:

```js
sheet.getRange("I80:M80").formulas = [[
  '=IF(OR(G80="",H80=""),"",G80*H80)',
  '=IF(OR(D80="Reembolso",D80="Payout"),I80,"")',
  '=IF(OR(D80="Compra",D80="Renovación"),I80,"")',
  '=IF(I80="","",J80-K80)',
  '=IF(A80="","",TEXT(A80,"yyyy-mm"))'
]];
sheet.getRange("I80:M379").fillDown();
```

Los KPI serán `SUM(J80:J379)`, `SUM(K80:K379)`, `SUM(L80:L379)`, `IF(gastos=0,"",beneficio/gastos)` y la suma de `COUNTIF(F26:F75,"Evaluación")` y `COUNTIF(F26:F75,"Financiada")`.

- [ ] **Step 4: Añadir validaciones, formatos y avisos**

Aplicar listas desplegables a propfirm, moneda, fase, estado y tipo. Fechas con `yyyy-mm-dd`; importes con `"€"#,##0.00;[Red]("€"#,##0.00);-`; ROI con `0.0%`. Formatear entradas con relleno claro y fórmulas con texto negro.

Aplicar estas reglas:

```js
sheet.getRange("A26:I75").conditionalFormats.addCustom(
  '=OR($F26="Fallida",$F26="Cerrada")',
  { fill: "#FDECEC", font: { color: "#991B1B" } }
);
sheet.getRange("A80:M379").conditionalFormats.addCustom(
  '=AND(COUNTA($A80:$H80)>0,OR($A80="",$B80="",$C80="",$D80="",$G80="",$H80=""))',
  { fill: "#FFF4CC" }
);
```

Crear `CuentasTable` en `A25:I75` y `MovimientosTable` en `A79:M379`, con filtros y bandas discretas. No aplicar bordes pesados a cada celda.

- [ ] **Step 5: Crear la ayuda mensual y los gráficos**

`O26` partirá del primer mes con datos; `O27:O85` avanzará con `EDATE` hasta el último mes. `P:Q` sumará ingresos y gastos con `SUMIFS`, `R` calculará beneficio mensual y `S` el acumulado.

Crear un gráfico de líneas desde `O25:Q85` titulado `Ingresos y gastos mensuales (€)` y otro con series manuales `O26:O85` / `S26:S85` titulado `Beneficio neto acumulado (€)`. En ambos, usar eje Y `"€"#,##0`, fuentes de 10–12 pt y posiciones reservadas sin cubrir datos.

- [ ] **Step 6: Exportar una primera versión**

```js
await fs.mkdir(outputDir, { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(`${outputDir}/registro_propfirms.xlsx`);
```

Run:

```powershell
& "C:\Users\HP\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe" "outputs\019f5b3d-4c9c-79e2-a6df-f7601abb2125\build_propfirm_tracker.mjs"
```

Expected: proceso con código 0 y un único `.xlsx` final.

---

### Task 3: Verificar y reparar el libro

**Files:**
- Modify: `outputs/019f5b3d-4c9c-79e2-a6df-f7601abb2125/build_propfirm_tracker.mjs`
- Verify: `outputs/019f5b3d-4c9c-79e2-a6df-f7601abb2125/registro_propfirms.xlsx`

**Interfaces:**
- Consumes: el workbook en memoria y el JSON de origen.
- Produces: inspecciones compactas, dos vistas renderizadas y el `.xlsx` corregido.

- [ ] **Step 1: Inspeccionar fórmulas y resultados clave**

Añadir antes de la exportación:

```js
console.log((await workbook.inspect({
  kind: "table",
  range: "Registro!A1:S100",
  include: "values,formulas",
  tableMaxRows: 100,
  tableMaxCols: 19,
  maxChars: 12000,
})).ndjson);
console.log((await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 300 },
  summary: "final formula error scan",
})).ndjson);
```

Expected: KPIs coherentes con el JSON y cero errores de fórmula.

- [ ] **Step 2: Conciliar los datos fuente**

Comprobar en JavaScript:

```js
if (data.accounts.length > 50) throw new Error("Hay más de 50 cuentas; ampliar la tabla");
if (data.movements.length > 300) throw new Error("Hay más de 300 movimientos; ampliar la tabla");
if (data.movements.some((m) => !m.date || !m.type || !(m.amountOriginal > 0) || !(m.fxToEur > 0))) {
  throw new Error("Hay movimientos incompletos o inválidos");
}
```

Expected: recuentos del JSON, tablas y vistas privadas de The5ers coinciden para el periodo accesible.

- [ ] **Step 3: Renderizar toda la única hoja por secciones**

```js
for (const [name, range] of [["dashboard", "A1:S78"], ["movimientos", "A79:M120"]]) {
  const preview = await workbook.render({ sheetName: "Registro", range, scale: 1.5, format: "png" });
  await fs.writeFile(`${outputDir}/${name}.png`, new Uint8Array(await preview.arrayBuffer()));
}
```

Revisar ambas imágenes: títulos y números visibles, gráficos no vacíos, sin solapes ni columnas cortadas. Corregir únicamente los defectos observados y volver a ejecutar el constructor una vez.

- [ ] **Step 4: Confirmar el artefacto final**

Run:

```powershell
Get-Item "outputs\019f5b3d-4c9c-79e2-a6df-f7601abb2125\registro_propfirms.xlsx" | Select-Object FullName, Length, LastWriteTime
```

Expected: archivo no vacío, actualizado tras la verificación y listo para entrega.
