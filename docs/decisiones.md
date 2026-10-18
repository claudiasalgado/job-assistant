# Decisiones de arquitectura

## 001 · Proyecto de GCP nuevo y dedicado

- **Fecha:** 2026-10-18
- **Decisión:** crear un proyecto de GCP exclusivo para este repo, con
  facturación vinculada y presupuesto de 5 € con alertas al 50 %, 90 % y
  100 %.
- **Contexto:** la cuenta ya tenía proyectos de otros usos y la config de
  gcloud apuntaba a uno sin acceso.
- **Alternativa descartada:** reutilizar un proyecto existente.
- **Motivo:** aislar permisos, costes y limpieza. Un proyecto propio permite
  ver el gasto real del proyecto por separado y borrarlo entero al terminar.
  Reutilizar uno habría mezclado APIs, claves y costes de otros usos.
- **Consecuencia:** el presupuesto solo avisa por email, no corta el gasto.
  Aceptado: el coste esperado es de 0 a 5 € al mes.

## 002 · Monorepo como workspace de uv

- **Fecha:** 2026-10-18
- **Decisión:** un workspace de uv con tres miembros: `packages/core`
  (modelos, repos de Firestore, clientes de GCS y Pub/Sub), `services/api`
  y `services/worker`. La raíz es un *virtual workspace*: solo declara los
  miembros, sin paquete propio. Un único `uv.lock` para todo.
- **Contexto:** el plan separa api y worker en dos servicios de Cloud Run
  que comparten código. El repo nació como un único paquete
  (`src/jobassistant`) con solo la plantilla de `uv init`.
- **Alternativas descartadas:**
  - Paquetes independientes con dependencia por ruta: un lock por
    paquete, y las versiones de lo compartido pueden desincronizarse.
  - Un único paquete con *extras*: la imagen de `api` arrastraría el
    código del worker; menos separación.
  - Copiar `core` en cada servicio: dos copias que divergen.
  - Raíz como paquete (no virtual): mezcla el contenedor con un paquete
    real, sin ventaja a cambio.
- **Motivo:** un solo lock garantiza que api y worker usen la misma versión
  de lo que comparten (p. ej. Pydantic, que define los mensajes entre
  ambos). Cada miembro lleva solo sus dependencias, así que cada imagen
  Docker es más pequeña (WeasyPrint solo en el worker).
- **Consecuencia:** el *build context* de Docker es la raíz del repo, no
  la carpeta del servicio, porque `core` está fuera de ella. Los comandos
  necesitan `--package` para indicar el miembro.

## 003 · Prototipar con datos ficticios

- **Fecha:** 2026-10-18
- **Decisión:** el sprint 1 se desarrolla contra `data/samples/`: un perfil
  inventado (`profile.json`) y dos ofertas inventadas (`offer_01.txt`,
  `offer_02.txt`). Los datos reales viven en `data/private/`, ignorado
  por git.
- **Contexto:** el repo puede ser público y no debe contener CV, ofertas ni
  salarios reales. El sprint 1 es un script local que lee una oferta, llama
  a Gemini en Vertex AI y genera el CV; aún no hay API propia ni ingesta
  automática de ofertas.
- **Alternativa descartada:** usar ofertas y CV reales desde el primer día,
  en el repo o anonimizados a mano.
- **Motivo:** anonimizar a mano es fácil de hacer mal. Con datos fijos se
  puede repetir una prueba y comparar resultados al cambiar un prompt. Las
  dos ofertas son distintas a propósito (idioma, seniority, formato del
  salario, encaje con el perfil) para cubrir casos distintos del extractor.
- **Consecuencia:** los datos inventados son más limpios que los reales y
  pueden ocultar fallos del extractor. Antes de cerrar el sprint 1 hay que
  probarlo con al menos una oferta real desde `data/private/`.

## 004 · SDK `google-genai` y salida estructurada con esquema JSON

- **Fecha:** 2026-10-18
- **Decisión:** llamar a Gemini en Vertex AI con el SDK `google-genai`
  (modo Vertex activado con la variable `GOOGLE_GENAI_USE_ENTERPRISE=true`,
  autenticado con ADC) y obtener el JSON pasando la
  clase Pydantic `ExtractedOffer` como `response_json_schema`. El resultado
  se valida igualmente con Pydantic.
- **Contexto:** el extractor convierte el texto libre de una oferta en un
  JSON con forma fija que usan el adaptador de CV y, más adelante,
  Firestore.
- **Alternativas descartadas:**
  - SDK `vertexai` (`GenerativeModel`): es el antiguo y está en retirada.
  - Pedir JSON en el prompt, parsear y reintentar: portable entre LLMs,
    pero con más fallos (bloques de código, campos inventados) y con
    reintentos que escribir y mantener.
- **Motivo:** con un esquema JSON Gemini restringe la generación a él, así que casi siempre devuelve JSON válido. Las `description` de
  cada campo actúan como instrucciones. Con ADC no hay API keys que
  guardar ni rotar.
- **Consecuencia:** acoplamiento a Gemini y a su subconjunto de JSON Schema
  (por eso el modelo usa tipos simples: `Literal`, `str | None`, listas de
  `str`). Cambiar de proveedor obligaría a rehacer esta capa. La versión
  del modelo va en una variable de entorno, no en el código.

## 005 · Región `europe-west4` y modelo `gemini-2.5-flash`

- **Fecha:** 2026-10-18
- **Decisión:** llamar a Vertex AI en `europe-west4` con `gemini-2.5-flash`.
  Región y modelo se configuran por variables de entorno
  (`GOOGLE_CLOUD_LOCATION`, `GEMINI_MODEL`).
- **Contexto:** a partir del adaptador de CV se enviarán a Gemini datos
  personales (el perfil), así que importa dónde se procesan. En
  `europe-west4` el proyecto no tenía acceso a `gemini-3.8-flash` (404);
  consultando la API, la región solo ofrecía la familia 2.5.
- **Alternativas descartadas:**
  - `global` con `gemini-3.8-flash`: funciona y es más moderno, pero no se
    controla dónde se procesan los datos.
  - Otras regiones de la UE: no exploradas.
- **Motivo:** procesamiento en la UE. En la oferta 1, `gemini-2.5-flash`
  dio exactamente el mismo resultado que `gemini-3.8-flash`. La oferta 2
  solo se probó con 2.5, con un resultado correcto tras ajustar el prompt.
- **Consecuencia:** una generación de modelo anterior, que se retirará
  antes. La equivalencia de calidad se ha visto en una oferta y una
  ejecución, no se ha medido, y esa prueba se hizo con la temperatura por
  defecto (antes de la decisión 006), así que pudo influir el azar. Revisar
  cuando los modelos 3.x lleguen a la UE. Cambiar de modelo o región es una
  línea del `.env`.

## 006 · Temperatura 0 en el extractor

- **Fecha:** 2026-10-18
- **Decisión:** llamar a Gemini con `temperature=0` en la extracción de
  ofertas.
- **Contexto:** la decisión 003 usa datos fijos para repetir pruebas y
  comparar resultados al cambiar un prompt o un modelo. Con la temperatura
  por defecto, la misma oferta puede dar salidas distintas en cada
  ejecución, y no se distingue el efecto del cambio del efecto del azar.
- **Alternativas descartadas:**
  - Temperatura por defecto: más variedad, que en extracción no aporta nada.
  - `temperature=0` con `seed` fijo: algo más reproducible, pero tampoco
    garantiza salidas idénticas y añade un parámetro más. Se puede añadir
    si al comparar modelos sigue habiendo ruido.
- **Motivo:** extraer datos no es una tarea creativa. Lo que interesa es
  que la misma entrada dé la misma salida.
- **Consecuencia:** con temperatura 0 Gemini no es totalmente
  determinista (el cálculo en GPU varía un poco), así que la salida es muy
  estable pero no idéntica siempre. No se aplica al adaptador de CV ni a
  la carta, donde algo de variedad al redactar sí aporta.
