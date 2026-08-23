# Diseño del asistente protegido de bootstrap del controlador de catálogo

Fecha: 2026-08-23
Estado: pendiente de aprobación final del usuario
Repositorio: `trading-optimizer-lab-org/aurora`

## 1. Objetivo

Sustituir el procedimiento técnico manual que bloquea el controlador por un
asistente local de una sola ejecución. El usuario no tendrá que crear Apps,
copiar claves, usar PowerShell, editar GitHub ni configurar cuentas de Windows.

La única intervención humana será confirmar las pantallas que GitHub y Windows
no permiten automatizar de forma legítima:

1. aceptar una elevación de Windows;
2. iniciar sesión o confirmar 2FA si GitHub lo exige;
3. confirmar la creación y la instalación de las dos Apps en el repositorio
   exacto;
4. confirmar una vez el acceso a Codex en el perfil aislado si OpenAI vuelve a
   solicitar autenticación.

El asistente no lanzará ningún run de catálogo de producción. El resultado solo
podrá ser `READY` o `BLOCKED` con una causa y una acción concretas.

## 2. Decisión y alternativas descartadas

### Opción elegida: asistente local aislado con GitHub App Manifest

Un paquete protegido, iniciado expresamente por el usuario, abre formularios
oficiales de GitHub ya configurados. Un proceso elevado distinto de Codex recibe
las claves, las protege y ejecuta el bootstrap existente. Codex solo recibe un
recibo final sin secretos.

Es la única opción que conserva simultáneamente automatización, mínimos
permisos, trazabilidad y separación real de la IA.

### Alternativa descartada: token personal de GitHub

Seguiría exigiendo una creación manual, sería una credencial duradera y tendría
un alcance más difícil de limitar. Además, un token disponible para Codex
permitiría saltarse el intermediario.

### Alternativa descartada: servicio externo

Trasladar el intermediario a Cloudflare u otro proveedor añadiría otra cuenta,
credenciales, despliegue, facturación y puntos de fallo. No elimina la
confirmación del propietario para instalar una App de GitHub.

### Alternativa descartada: aprobación manual de cada run

Evita parte del bootstrap, pero exige supervisión permanente y contradice el
objetivo de operación autónoma.

## 3. Experiencia del usuario

El Escritorio contendrá un único acceso llamado
`Instalar controlador AURORA`. Al abrirlo:

1. muestra un resumen simple: no se ejecutarán estrategias y el controlador
   permanecerá apagado hasta el final;
2. solicita una sola elevación de Windows;
3. guarda el estado, cierra todas las instancias de Codex bajo HP y comprueba que
   sus procesos han terminado antes de admitir cualquier secreto;
4. abre secuencialmente las páginas oficiales para crear e instalar la App
   solicitante y la App auditora;
5. en cada página indica un único botón que el usuario debe pulsar y espera el
   retorno firmado de GitHub;
6. ejecuta pruebas, vinculación pública, PR, fusión, instalación y
   cualificación sin más decisiones técnicas;
7. presenta `LISTO` o una explicación concreta de por qué se ha detenido;
8. abre Codex bajo `AURORAAgent` y deja el recibo sin secretos disponible en la
   tarea reanudada.

GitHub puede presentar hasta cuatro confirmaciones breves: crear e instalar
cada una de las dos Apps. No se prometerán menos pantallas de las que GitHub
exija en ese momento.

La interfaz local no tendrá campos para rutas, repositorios, permisos, nombres
de workflows, claves, tokens ni parámetros de runs.

## 4. Arquitectura

### 4.1 Lanzador visible y sin privilegios

El acceso del Escritorio ejecuta un lanzador mínimo, sin argumentos. Este
comprueba:

- que el checkout es el repositorio exacto;
- que no existe otro escritor activo en el worktree;
- que el commit coincide con el paquete de bootstrap construido;
- que `CATALOG_CONTROLLER_ENABLED=false`;
- que no existe ningún run de catálogo de producción iniciado por el asistente.

Después inicia el coordinador mediante UAC. No recibe ni conserva secretos.

### 4.2 Coordinador elevado de una sola ejecución

El coordinador ejecuta una máquina de estados cerrada y reanudable. Solo admite
transiciones predefinidas y guarda un estado sellado en
`C:\ProgramData\AURORA\CatalogBootstrap` con herencia desactivada.

Sus estados son:

```text
PRECHECK
REQUESTER_CREATE_PENDING
REQUESTER_INSTALL_PENDING
AUDITOR_CREATE_PENDING
AUDITOR_INSTALL_PENDING
PUBLIC_BINDING_PENDING
MERGE_PENDING
LOCAL_INSTALL_PENDING
GITHUB_CONTROLS_PENDING
QUALIFICATION_PENDING
AGENT_RESTART_PENDING
FINAL_AUDIT_PENDING
READY | BLOCKED
```

Cada transición es idempotente. Reabrir el asistente reanuda el estado
existente; no crea otra App, otro issue de autoridad, otra PR ni otra petición de
cualificación.

### 4.3 Creación oficial de las Apps

Dos manifiestos cerrados contienen los nombres y permisos exactos ya aprobados:

- solicitante: Metadata de lectura e Issues de lectura/escritura;
- auditora: los permisos de lectura establecidos por el controlador y ningún
  permiso de escritura.

Los tres límites de gasto se consultan y administran mediante el plano de
facturación de `trading-optimizer-lab-org`, que admite presupuestos de alcance
repositorio. La App auditora se instala únicamente en la organización y en
`trading-optimizer-lab-org/aurora`; no solicita permisos empresariales ni exige
una segunda instalación en `trading-optimizer-lab`.

El coordinador levanta un receptor únicamente en `127.0.0.1`, genera un `state`
aleatorio de un solo uso y abre el formulario oficial de la organización. Solo
acepta el retorno si coinciden estado, ventana temporal, organización y tipo de
App.

El código temporal se intercambia dentro del mismo proceso elevado. La
respuesta privada nunca se devuelve al navegador, a Codex, a stdout ni a un
archivo temporal general.

Antes de abrir el primer formulario, el coordinador exige que no quede ningún
proceso de Codex bajo HP. Si no puede demostrarlo, no solicita ningún código ni
crea ninguna App.

La instalación se abre después en la página oficial de la App. El coordinador
no continúa hasta comprobar por API que la App está instalada únicamente en
`trading-optimizer-lab-org/aurora` y que los permisos observados son exactos.

### 4.4 Custodia de claves

Las dos claves se mantienen separadas:

- la clave solicitante se mueve directamente al almacén privado de
  `AURORARequester`;
- la clave auditora se carga directamente como secreto del entorno
  `catalog-production` y se elimina de la máquina tras verificar la huella y los
  metadatos del secreto.

Reglas obligatorias:

- nunca aparecen en argumentos, variables heredadas, logs, recibos, portapapeles
  ni Descargas;
- las escrituras son atómicas y con ACL cerrada antes de contener la clave;
- cualquier archivo intermedio se considera un fallo;
- el contenido se elimina de memoria en cuanto la operación termina;
- los recibos solo incluyen IDs, logins, permisos y huellas públicas;
- Codex y `AURORAAgent` deben recibir `Access Denied` ante cualquier intento de
  lectura.

### 4.5 Vinculación, PR y fusión

Tras observar ambas instalaciones, el coordinador:

1. deriva únicamente las claves públicas;
2. actualiza los campos públicos cerrados del controlador;
3. crea el ancla de autoridad única mientras producción sigue desactivada;
4. regenera los manifiestos afectados;
5. ejecuta las pruebas y tres rondas limpias exigidas por el plan;
6. crea una rama de bootstrap, un PR y espera sus comprobaciones;
7. fusiona solo si la protección vigente lo permite y todos los hashes coinciden.

No se aceptan cambios ajenos. Una divergencia, checkout sucio o revisión
obligatoria no satisfecha produce `BLOCKED` sin forzar la fusión.

### 4.6 Instalación local

Después de fusionar el commit protegido, el coordinador ejecuta primero en modo
simulación y después aplica los instaladores ya versionados:

- `install_catalog_agent_sandbox.ps1`;
- `install_catalog_requester_broker.ps1`.

Construye dos veces las aplicaciones del solicitante y exige igualdad byte a
byte. Crea `AURORAAgent` y `AURORARequester`, sus ACL, entornos aislados y la
tarea programada. Ninguna contraseña se muestra o pasa a Codex.

### 4.7 Relanzador de Codex aislado

Se instala un relanzador fijo y protegido que solo puede activar el paquete
firmado con familia `OpenAI.Codex_2p2nqsd0c76g0` bajo `AURORAAgent`. Resuelve y
verifica la versión instalada en cada arranque, por lo que una actualización no
depende de una ruta antigua ni permite elegir otro ejecutable. La credencial
aleatoria de esa cuenta queda protegida por Windows para el usuario humano y no
es legible desde `AURORAAgent`.

El relanzador:

- no acepta ruta, comando ni argumentos arbitrarios;
- no puede elevar ni iniciar procesos como administrador;
- rechaza arrancar si sigue existiendo una instancia de Codex bajo HP;
- inicia la nueva instancia con perfil separado, sin GitHub CLI, navegador,
  conectores ni credenciales del usuario;
- elimina cualquier mecanismo de bootstrap elevado al terminar.

El controlador no se habilita hasta que la auditoría observe que el proceso de
Codex que recibe el prompt y todos sus procesos hijos pertenecen a
`AURORAAgent`. Cualquier proceso hijo bajo HP, cualquier perfil heredado de HP o
cualquier helper no incluido en la lista cerrada bloquea la activación.

## 5. Uso de credenciales administrativas

El coordinador puede usar la sesión administrativa actual exclusivamente
durante el bootstrap para aplicar controles y fusionar el PR. Esa capacidad no
se copia a `AURORAAgent` ni al intermediario.

Antes de habilitar producción debe demostrar:

- que la instancia antigua de Codex ha terminado;
- que el nuevo proceso no puede leer ni ejecutar `gh` con la cuenta de HP;
- que no puede acceder al perfil, cookies, navegador, almacén de credenciales o
  claves del usuario;
- que el coordinador elevado y sus credenciales ya no están disponibles.

Si una de estas pruebas no puede realizarse, conserva
`CATALOG_CONTROLLER_ENABLED=false`.

## 6. Recuperación y errores

- Cerrar el navegador: queda pendiente la misma pantalla, sin duplicados.
- Login, CAPTCHA o 2FA: espera al usuario; no intenta eludirlos.
- Código temporal caducado después de crear la App: bloquea, registra el ID
  público del posible huérfano y no crea una App duplicada. La recuperación o
  eliminación será una operación administrativa separada.
- App creada pero no instalada: reabre únicamente su instalación.
- Permisos o repositorio incorrectos: bloquea y ofrece abrir la página oficial
  para corregirlos; no amplía permisos automáticamente.
- Caída de red: reintento limitado respetando `Retry-After`.
- Fallo de prueba, PR o protección: bloquea antes de instalar o habilitar.
- Reinicio del equipo: reanuda desde el último estado sellado.
- Fallo después de cargar la clave auditora: verifica el secreto antes de
  eliminar la copia local; nunca elimina la única copia sin prueba de destino.
- Estado ambiguo: `BLOCKED`; nunca interpreta ausencia de error como éxito.

El asistente no elimina Apps, issues, ramas, claves o cuentas automáticamente
cuando el estado es ambiguo. Toda limpieza material será una operación separada
y explícita.

## 7. Archivos previstos

- `config/catalog_bootstrap_app_manifests_v1.json`: los dos manifiestos cerrados.
- `schemas/catalog_bootstrap_app_manifests_v1.schema.json`: esquema sin campos
  adicionales.
- `infra/sp500_megarun/catalog_bootstrap_contract.py`: manifiestos y enlaces
  públicos cerrados.
- `infra/sp500_megarun/catalog_bootstrap_state.py`: estados, transiciones y
  persistencia reanudable.
- `infra/sp500_megarun/catalog_bootstrap_manifest.py`: formulario y retorno
  local de GitHub sin logs.
- `infra/sp500_megarun/catalog_bootstrap_github.py`: verificación exacta de las
  instalaciones.
- `infra/sp500_megarun/catalog_bootstrap_secrets.py`: custodia y borrado de las
  claves.
- `infra/sp500_megarun/catalog_bootstrap_binding.py`: enlace público, ancla, PR
  y fusión protegida.
- `infra/sp500_megarun/catalog_bootstrap_finalizer.py`: auditoría, sello y
  recibo final.
- `scripts/run_catalog_bootstrap_assistant.py`: receptor local y coordinador de
  GitHub sin interfaz arbitraria.
- `scripts/install_catalog_bootstrap_assistant.ps1`: preflight, UAC, paquete,
  ACL y acceso del Escritorio.
- `scripts/launch_catalog_codex_secure.ps1`: relanzador de ruta y argumentos
  cerrados bajo `AURORAAgent`.
- `requirements/catalog-bootstrap.in` y lock específico: entorno mínimo,
  aislado y reproducible.
- `tests/test_catalog_bootstrap_assistant.py`: máquina de estados y recuperación.
- `tests/test_catalog_bootstrap_app_manifests.py`: permisos y formularios.
- `tests/test_catalog_bootstrap_secret_isolation.py`: claves, logs, ACL y
  procesos.
- `tests/test_catalog_bootstrap_end_to_end.py`: doble construcción, PR,
  instalación, reanudación y cualificación sintética.
- `docs/runbooks/CATALOG_BOOTSTRAP_ASSISTANT.md`: instrucciones de un clic y
  recuperación sin secretos.
- `docs/runbooks/CATALOG_CONTROLLER_BOOTSTRAP_RECEIPT.md`: resultado final.

No se modificará ni sustituirá
`C:\Users\HP\Desktop\plantilla-prompt-nuevo-run-catalogo.md`.

## 8. Pruebas y aceptación

Antes de ofrecer el acceso del Escritorio deben pasar:

1. pruebas de los manifiestos y permisos exactos;
2. retorno válido, `state` incorrecto, repetición, caducidad y puerto ocupado;
3. respuesta con clave falsa o malformada sin filtración a logs;
4. crash y reanudación en cada transición;
5. doble clic simultáneo sin duplicar recursos;
6. ACL positivas para el propietario correcto y negativas para Codex;
7. escaneo de secretos en procesos, argumentos, entorno, archivos y recibos;
8. construcción determinista del paquete;
9. pruebas de PR, checks fallidos, divergencia y protección de rama;
10. instalación en simulación y una prueba sintética sin cálculo;
11. proceso real de Codex bajo `AURORAAgent` y proceso antiguo ausente;
12. lectura final de Apps, permisos, entorno, secretos, presupuestos, ancla,
    intermediario, sello y controlador;
13. tres cualificaciones equivalentes;
14. cero runs de catálogo de producción y cero solicitudes de producción.

El resultado final será `READY` únicamente cuando el recibo protegido del plan
original quede completo y el controlador se lea como habilitado desde GitHub.
La interfaz no mostrará `LISTO` basándose solo en pruebas locales.

## 9. Límites

- Un único agente; sin subagentes, forks ni worktrees adicionales.
- No se toca el checkout principal sucio.
- No se lanza ningún run de catálogo de producción.
- No se rebajan permisos, gates, presupuestos ni separación de identidades.
- Ninguna confirmación de login, 2FA, CAPTCHA, UAC o instalación se simula.
- El navegador es del usuario durante esas confirmaciones; el asistente no toma
  control de otras pestañas ni automatiza la sesión autenticada.
- Ante cualquier contradicción con el plan original, prevalece el comportamiento
  que mantenga producción desactivada.
