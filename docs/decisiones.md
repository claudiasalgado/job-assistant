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

## 007 · Validar en código el CV que propone Gemini y descartar lo no verificable

- **Fecha:** 2026-10-18
- **Estado:** la decisión 013 cambia qué se hace con un logro cuyas cifras
  no coinciden: vuelve al texto original en vez de descartarse. El resto
  sigue vigente.
- **Decisión:** Gemini solo devuelve un borrador (`TailoredCVDraft`) con
  textos e ids. El código (`build_tailored_cv`) lo comprueba contra el
  perfil y descarta, con un aviso en `warnings`:
  - experiencias cuyo `experience_id` no existe,
  - logros cuyo `source_id` no existe o es de otra experiencia,
  - logros cuyas cifras no coinciden con las del original (se comparan los
    conjuntos de números, normalizando coma y punto decimal),
  - skills que no están en el perfil (comparadas sin distinguir mayúsculas
    y mostradas siempre con el nombre del perfil).
  Empresas, cargos, fechas y datos personales los pone el código, nunca
  Gemini. Los datos personales no se envían a Gemini.
- **Contexto:** el prompt prohíbe inventar, pero un prompt es una petición,
  no una garantía. El esquema JSON asegura la forma de la respuesta, no
  que los ids o las cifras sean verdad.
- **Alternativas descartadas:**
  - Ante cifras cambiadas, volver al texto original: el CV podría salir con
    dos idiomas.
  - Ante cifras cambiadas, conservar el texto con un aviso: la cifra
    inventada llegaría al PDF.
  - Reintentar con Gemini explicándole el error: más coste, más latencia y
    más código. Queda en el roadmap si se descartan demasiados logros.
  - Comparar skills exactamente: "python" frente a "Python" se descartaría
    sin motivo.
  - Validar con validadores de Pydantic: mezcla la forma de los datos con
    las reglas de negocio y es más difícil de testear.
- **Motivo:** prefiero un CV con un punto menos que uno con un dato falso.
  La validación es una función pura, así que se prueba sin llamar a Gemini.
- **Consecuencia:** solo protege lo verificable (ids, cifras, skills). El
  resumen y los matices de redacción no se pueden comprobar con código: los
  cubre el prompt (decisión 008) y la revisión humana antes de enviar cada
  CV. Límites conocidos: una cifra escrita con palabras ("tres" frente a
  "3") cuenta como cambio, y la validación no detecta lo que el borrador
  omite, solo lo que incluye. Un LLM como juez queda en el roadmap.

## 008 · Voz única y niveles de skill fijos en el CV adaptado

- **Fecha:** 2026-10-18
- **Estado:** la voz de los logros la cambia la decisión 011 (frases
  nominales). La tabla de niveles la sustituye la decisión 015 (el
  resumen no califica niveles).
- **Decisión:** el prompt del adaptador fija:
  - la voz: resumen en frases nominales, sin verbos conjugados, y logros
    en primera persona del pasado sin pronombre ("Construí"; en inglés,
    "Built"). Nunca tercera persona;
  - el nivel de cada skill con una expresión fija según su `level` en el
    perfil: `beginner` → "nociones de", `intermediate` → "experiencia
    con", `advanced` → "dominio de";
  - la prohibición de añadir valoraciones ("clave", "sólido"), de cambiar
    cantidades escritas con palabras o el número gramatical, y de copiar
    las expresiones de nivel de la oferta.
- **Contexto:** en la primera prueba con la oferta 1 la validación no dio
  ningún aviso, pero el resumen decía "habilidades sólidas en SQL" (en el
  perfil, `intermediate`, copiado del "buen nivel de SQL" de la oferta),
  mezclaba tercera persona en el resumen con primera en los logros y un
  logro ganó un "clave" que no estaba en el original.
- **Alternativas descartadas:**
  - Pedir "no exageres": subjetivo, cada ejecución lo interpreta distinto
    y no se puede comprobar.
  - No enviar el `level` a Gemini: más seguro, pero el resumen sería más
    pobre y Gemini perdería información para ordenar las skills.
  - Un LLM como juez que revise el resumen: más coste y latencia, y el
    juez también se equivoca. Para un solo usuario que revisa cada CV no
    compensa todavía.
- **Motivo:** las frases nominales son lo habitual en el resumen de un CV
  en castellano y, al no tener persona gramatical, no chocan con los logros
  en primera persona. Una tabla fija de niveles se puede comprobar, y en el
  futuro incluso con código.
- **Consecuencia:** en la segunda prueba la voz y los niveles salieron
  bien, pero siguió apareciendo "especializada en" (se prohibió
  explícitamente después) y el modelo omitió una experiencia entera (ver
  decisión 009). Falta probar con la oferta 2.

## 009 · El CV adaptado incluye siempre todas las experiencias

- **Fecha:** 2026-10-18
- **Decisión:** el prompt pide a Gemini incluir siempre todas las
  experiencias del perfil, ordenadas por relevancia. Lo que adapta es qué
  logros muestra de cada una, no qué experiencias. Si aun así falta
  alguna, el código lo anota en `warnings`, pero no la añade.
- **Contexto:** en una prueba con la oferta 1, Gemini quitó entera la beca
  de investigación por considerarla poco relevante. El CV se quedaba con
  una sola experiencia y un hueco de seis meses, y la validación no avisaba
  porque solo comprueba lo que el borrador incluye.
- **Alternativas descartadas:**
  - Que el código añada las experiencias que falten con sus logros
    originales: garantiza que estén todas, pero si la oferta está en otro
    idioma esos logros saldrían sin traducir.
  - Dejar que Gemini decida y solo avisar: con mucha trayectoria es lo
    habitual, pero con un perfil junior quitar una experiencia siempre
    resta.
  - Que Gemini elija solo logros y el código ponga las experiencias:
    obligaría a cambiar `TailoredCVDraft` y Gemini dejaría de ordenarlas.
- **Motivo:** con una a tres experiencias, ninguna sobra. El aviso deja ver
  el fallo sin volver al problema del idioma.
- **Consecuencia:** en tres ejecuciones seguidas con la oferta 1 se
  incluyeron las dos experiencias, sin avisos y sin "especializada". Pero
  en cada ejecución se coló un fallo distinto en el texto libre, que la
  validación no detecta: una tarea copiada de la oferta como si fuera
  propia ("modelado de tablas en BigQuery"), un nivel mal traducido
  (Google Cloud Platform, `beginner`, como "experiencia con") y una
  cantidad perdida ("tres informes" pasó a "informes"). Confirma la
  decisión 007: el texto libre depende de la revisión humana. Si se repite,
  candidatos para el futuro: comprobar en código la tabla de niveles,
  bajar la temperatura del adaptador o el LLM como juez. Si la lista de
  experiencias crece, se puede pasar a dejar que Gemini decida.

## 010 · El seniority lo fija el perfil y el código lo comprueba

- **Fecha:** 2026-10-18
- **Estado:** corregida por la decisión 011. El resumen ya no nombra el
  nivel, y `seniority` queda solo para comparar con la oferta.
- **Decisión:** `Profile` tiene un campo `seniority` (`intern`, `junior`,
  `mid`, `senior`, `lead`) y el código lo copia a `TailoredCV`, como las
  fechas o la empresa. El prompt pide que la primera frase del resumen
  nombre el rol con ese nivel y que no mencione otro. El código avisa en
  `warnings` si el resumen no lo nombra o si menciona un nivel distinto.
  En la misma revisión del prompt, la tabla de niveles de skill pasa a
  tener su versión en inglés y se prohíben los pronombres en todo el CV.
- **Contexto:** con la oferta 2 (inglés, nivel `mid`), en dos de tres
  ejecuciones Gemini quitó "Junior" del resumen para encajar mejor con la
  oferta. Además, el nivel `beginner` salió con tres expresiones inglesas
  distintas ("notions of", "foundational experience", "beginner's grasp")
  y una ejecución usó "I am eager".
- **Alternativas descartadas:**
  - Solo una regla en el prompt: más barato, pero un "Junior" omitido no
    daría ningún aviso.
  - Que el resumen no mencione el nivel y solo salga en la cabecera:
    Gemini podría seguir describiendo el rol sin "Junior", sin aviso.
  - Un tipo `Seniority` compartido con `ExtractedOffer`: la oferta necesita
    además `unspecified`, y la unión de enums complica el esquema que se
    envía a Gemini (decisión 004). Se repite la lista de valores.
  - Añadir al regex las variantes con tilde (`s[eé]nior`): hay que
    acordarse de cada una. Quitar las tildes con `unicodedata` las cubre
    todas.
- **Motivo:** el nivel es un dato verificable, así que se protege con
  código (decisión 007). Subirlo para encajar con una oferta es justo la
  exageración que se nota en una entrevista. Con los mismos valores en
  perfil y oferta, el matching del sprint 4 podrá compararlos directamente.
- **Consecuencia:** en tres ejecuciones con la oferta 2, "Junior" apareció
  siempre, `beginner` salió siempre como "basic knowledge of" y no hubo
  pronombres ni avisos. Límites conocidos: "lead" usado como verbo en
  inglés daría un falso aviso, y `intern` no se detecta en castellano
  ("becaria"). Para un perfil `junior` no afectan.

## 011 · Un perfil por idioma, titular propio y voz nominal

- **Fecha:** 2026-10-18
- **Decisión:**
  - Hay un perfil por idioma (`profile.es.json`, `profile.en.json`) con
    los mismos ids. El CV sale en el idioma del perfil que se elija; si no
    se elige, en el de la oferta. Se genera un solo CV, no uno por idioma.
    Gemini escribe en el idioma del perfil y no traduce.
  - El perfil tiene un titular (`headline`) que copia el código. El
    resumen no menciona ningún nivel profesional y el código avisa si lo
    hace. `seniority` se queda en el perfil solo para el matching.
  - Todo el CV usa frases nominales, también los logros ("Construcción
    de...", "Development of..."), sin pronombres ni tercera persona.
  - El perfil incorpora las secciones del CV real: descripción y puntos
    en la formación, categoría de skill, certificaciones, voluntariado y
    proyectos. Las copia el código; Gemini no las ve.
- **Contexto:** al comparar el sistema con el CV real (un HTML por idioma)
  salieron tres choques. El CV en inglés de la oferta 2 llevaba la
  formación y los idiomas en castellano, porque lo que copia el código no
  se traducía. El CV real no dice "junior" y la decisión 010 obligaba a
  ponerlo. Y el CV real usa frases nominales, no la primera persona de la
  decisión 008.
- **Alternativas descartadas:**
  - Que Gemini traduzca también lo que copia el código: un solo perfil,
    pero más texto en sus manos, y justo en la formación, que es lo que más
    pesa en un perfil junior.
  - Cada texto del perfil como diccionario por idioma: un solo fichero,
    pero el doble de pesado y más difícil de editar a mano.
  - Generar siempre los dos idiomas: el doble de llamadas a Gemini para un
    CV que casi siempre se envía en un solo idioma.
  - Mantener la decisión 010: todos los CV dirían "junior", aunque la
    persona haya decidido no ponerlo. Lo que había que proteger era no
    subir el nivel, no obligar a nombrarlo.
  - Verbo en pasado para los logros en inglés ("Built"): es la convención
    habitual allí, pero el CV real en inglés ya usa frases nominales y así
    los dos idiomas son coherentes.
- **Motivo:** es como ya se mantenía el CV a mano (un HTML por idioma), y
  quita el problema de la traducción en origen en vez de vigilarlo. Cada
  persona decide cómo se presenta; el sistema solo impide exagerar.
- **Consecuencia:** dos perfiles que mantener sincronizados. A Gemini se
  le envía una lista blanca de campos (`include`), no una lista negra, para
  que un campo personal nuevo no se le envíe por accidente. En las cuatro
  combinaciones de oferta y perfil, el CV salió en el idioma del perfil, sin
  niveles en el resumen y sin avisos. Siguen colándose fallos en el texto
  libre: por segunda vez, la tarea "modelar tablas" de la oferta 1 como si
  fuera propia; por cuarta vez, "un compañero" en plural; y una finalidad
  añadida ("for quality assurance"). Son los candidatos para el LLM como
  juez.

## 012 · Plantilla Jinja2 única y PDF con WeasyPrint

- **Fecha:** 2026-10-18
- **Decisión:** el CV se genera con una sola plantilla Jinja2
  (`templates/cv.html`) que reproduce el diseño, las clases y el orden del
  CV hecho a mano, más un diccionario de textos fijos por idioma
  (`LABELS` en `render.py`). WeasyPrint convierte el HTML en un PDF/UA-1.
  La plantilla, el CSS y las fuentes Mulish (con su licencia OFL) viven en
  `src/worker/templates/`, junto a los prompts.
- **Contexto:** el CV se mantenía a mano como dos HTML (uno por idioma) con
  un CSS común y un script de WeasyPrint. Su diseño ya estaba pensado para
  los ATS: una columna, el cargo antes que la fecha en el HTML, skills
  separadas por comas y PDF etiquetado.
- **Alternativas descartadas:**
  - f-strings o `string.Template` en vez de Jinja2: sin dependencias, pero
    con bucles y condicionales se vuelve ilegible.
  - Generar el HTML desde Python (`dominate`): no habría un fichero HTML
    que previsualizar y editar.
  - Dos plantillas, una por idioma: cada cambio de diseño habría que
    hacerlo dos veces y acabarían desincronizadas. Con un perfil por idioma
    (decisión 011) solo cambian unas diez etiquetas.
  - Chromium sin interfaz (Playwright) para el PDF: renderiza como Chrome,
    pero la imagen pesa unos 300 MB y no genera PDF/UA.
  - ReportLab: el PDF se dibuja con código y se perdería el diseño en
    HTML y CSS.
- **Motivo:** se conserva el diseño y su compatibilidad con los ATS, que
  ya estaba probada. Jinja2 es el estándar en Python y es el mismo motor
  de plantillas que se usará con FastAPI.
- **Consecuencia:** la plantilla usa `autoescape` (un texto con "<" no
  rompe el HTML) y `StrictUndefined` (una variable mal escrita falla en vez
  de dejar un hueco en el CV). `render_html` y `render_pdf` van separados
  e importan WeasyPrint solo al generar el PDF, así que el HTML se puede
  testear sin las librerías del sistema. WeasyPrint necesita pango: en
  macOS, `DYLD_FALLBACK_LIBRARY_PATH` debe ir en el `.env`, porque `uv run`
  no hereda las variables `DYLD_*` de la terminal; en Docker, la imagen del
  worker tendrá que instalar pango y será más pesada. Al extraer el texto
  del PDF, las viñetas aparecen agrupadas al final: pendiente de revisar con
  el test de pdfplumber.

## 013 · Un logro con las cifras cambiadas vuelve a su texto original

- **Fecha:** 2026-10-18
- **Decisión:** si la versión adaptada de un logro no tiene las mismas
  cifras que el original, el CV usa el texto original del perfil y lo
  anota en `warnings`, en vez de descartar el logro. El prompt aclara que
  al acortar un logro no se puede quitar ninguna cifra.
- **Contexto:** con la oferta 2 y el perfil en castellano, Gemini acortó
  los dos logros con datos medibles ("de 3 horas a 20 minutos", "F1 del
  0,86") quitándoles las cifras. La validación los descartó según la
  decisión 007, y el CV perdió justo los dos mejores logros. La beca se
  quedó sin ninguno. El prompt permitía "acortar" y prohibía "cambiar"
  cifras, pero no decía que quitarlas también es cambiarlas.
- **Alternativas descartadas:**
  - Solo aclarar el prompt: si Gemini lo vuelve a hacer, el logro se
    sigue perdiendo.
  - Mantener el descarte: en la 007 era lo correcto porque el texto
    original podía estar en otro idioma, pero desde la 011 el perfil está
    siempre en el idioma del CV, así que ese motivo ya no existe.
  - Reintentar con Gemini: sigue en el roadmap. El texto original es un
    respaldo más barato e igual de seguro.
- **Motivo:** el texto original lo escribió la persona, así que es por
  definición correcto y está en el idioma del CV. Se pierde la adaptación
  de un punto, nunca el logro ni la veracidad.
- **Consecuencia:** una cifra inventada tampoco llega nunca al PDF,
  porque el logro vuelve al original. Probado sin Gemini (una cifra quitada
  y una inventada vuelven al original con aviso) y con Gemini (dos
  ejecuciones con la oferta 2 en castellano, ya con el prompt aclarado,
  sin cifras perdidas ni avisos).

## 014 · Gemini ve todo el perfil profesional y nunca los datos personales

- **Fecha:** 2026-10-18
- **Decisión:** el adaptador envía a Gemini el perfil completo menos los
  campos de `PROFILE_FIELDS_NOT_SENT` en `tailor.py`: `personal` (nombre,
  email, teléfono, enlaces) y `seniority`. Pasa de una lista blanca a una
  lista negra. El prompt pide que el resumen use todo el perfil, que el
  cargo salga solo del titular o de la formación y nunca del puesto de la
  oferta, y que una certificación no se presente como cargo.
- **Contexto:** con el perfil real, la lista blanca de la minimización
  (`language`, `summary`, `experience`, `education`, `skills`) dejaba
  fuera las certificaciones y el titular. El resumen en castellano las
  omitió, y el de inglés usó el nombre de una certificación como si fuera
  un cargo. Al pedir que no repitiera el titular, el resumen presentó a la
  persona con el cargo de la oferta ("Ingeniera de datos" para una oferta
  de Data Engineer).
- **Alternativas descartadas:**
  - Ampliar la lista blanca con certificaciones, titular, idiomas,
    voluntariado y proyectos: más segura ante campos nuevos, pero cada
    campo profesional nuevo hay que acordarse de añadirlo o Gemini no lo
    ve.
  - Una segunda llamada solo para el resumen, con el CV ya montado: más
    coherente, pero el doble de llamadas y de latencia. Con una sola
    experiencia no compensa todavía.
- **Motivo:** la minimización protege los datos personales, y esos siguen
  fuera. Los datos profesionales no son sensibles y son justo lo que
  necesita el resumen. El riesgo de la lista negra (un campo sensible
  nuevo que se envía por olvido) se limita con una constante visible en un
  solo sitio.
- **Consecuencia:** cualquier campo sensible nuevo en `Profile` (por
  ejemplo, un salario deseado) debe añadirse a `PROFILE_FIELDS_NOT_SENT`.
  Pendiente: un test que lo compruebe. En las pruebas con el perfil real
  (oferta 1 en castellano, oferta 2 en los dos idiomas) el cargo salió del
  titular y las certificaciones aparecieron como certificaciones. Una vez,
  en castellano, el resumen omitió el máster.
- **Ajuste posterior:** el prompt pide mencionar siempre la titulación de
  mayor nivel. Se descartaron un campo `summary_must_mention` comprobado
  en código (falsos avisos cuando Gemini lo reformula) y una primera frase
  fija escrita por la persona (garantía total, pero la misma presentación
  en todos los CV). Basta con el prompt porque la persona revisa cada CV
  antes de enviarlo. En dos ejecuciones más con la oferta 1 el máster
  apareció las dos veces.

## 015 · El resumen no califica el nivel de las skills

- **Fecha:** 2026-10-18
- **Decisión:** el resumen nombra las skills sin expresiones de nivel
  ("Python, SQL y Docker", no "dominio de Python"). El `level` del perfil
  solo sirve para elegir qué skills destacar y en qué orden. Sustituye a
  la tabla de niveles de la decisión 008.
- **Contexto:** con la tabla, Gemini escribió "experience with CI/CD"
  para una skill en `beginner` y "conocimientos de" para una en
  `intermediate`, una expresión que la tabla no tiene. Era lo peor de los
  dos mundos: frases rígidas y sin garantía de que se cumplieran.
- **Alternativas descartadas:**
  - Mantener la tabla y comprobarla en código: garantiza el nivel, pero
    las frases quedan de robot y solo detecta las expresiones listadas
    ("sólidos conocimientos" se escaparía).
  - Dejar que Gemini exprese el nivel con libertad: texto natural, pero
    el sesgo del modelo es exagerar para encajar con la oferta y nadie lo
    comprueba.
  - Un juez LLM que revise si el texto exagera: sigue en el roadmap.
- **Motivo:** un nivel en el CV es una afirmación sobre la persona, como
  una cifra. Si no se afirma, no hay nada que vigilar. El nivel se
  demuestra con la experiencia, la formación y las certificaciones, y los
  niveles autoevaluados convencen poco a los reclutadores.
- **Consecuencia:** en tres pruebas ningún resumen calificó niveles. En
  una apareció "con experiencia en Google Cloud Platform", que no está
  prohibido pero se acerca. Es texto libre: candidato para el juez LLM.

## 016 · En el sprint 2, el servicio es `api` y usa `worker` como librería

- **Fecha:** 2026-10-18
- **Decisión:** el único servicio de Cloud Run del sprint 2 es el paquete
  `api` (FastAPI). Depende del paquete `worker` del workspace y llama
  directamente a `extract_offer`, `tailor_cv` y `render_pdf`, de forma
  síncrona.
- **Contexto:** la lógica del sprint 1 vive en `worker`. El plan pide un
  solo servicio en el sprint 2 y partirlo en api y worker con Pub/Sub en
  el sprint 3.
- **Alternativas descartadas:**
  - Mover extracción, adaptación y render a `core`: `core` cargaría con
    google-genai y WeasyPrint, que la api no necesitará en el sprint 3, y
    habría que deshacerlo.
  - Poner FastAPI dentro de `worker`: lo más directo, pero en el sprint 3
    habría que sacar de él las rutas de usuario y el frontend.
- **Motivo:** la frontera entre api y worker ya existe en el código. En el
  sprint 3, partir el servicio es cambiar la llamada directa por la
  publicación de un mensaje y quitar la dependencia.
- **Consecuencia:** mientras dure el sprint 2, la imagen de la api incluye
  WeasyPrint y sus librerías de sistema, así que es más pesada y arranca
  más lenta en frío. Se acepta porque es temporal.

## 017 · Repositorio en `core` con Firestore y Cloud Storage

- **Fecha:** 2026-10-19
- **Decisión:** la api deja de guardar en disco. `ApplicationRepository`
  (`packages/core/src/core/repository.py`) guarda cada candidatura como
  documento `applications/{id}` en Firestore y sus ficheros (`offer.txt`,
  `cv.pdf`) en el bucket `clau-job-assistant` bajo `applications/{id}/`. Los
  dos recursos están en `europe-west4`. El documento es `Application`
  (`core.models`) sin el `id`, que es el nombre del documento; las rutas de
  GCS se deducen del id y no se guardan. La api sirve el PDF leyéndolo de
  GCS. En local se trabaja contra los recursos reales con ADC.
- **Contexto:** en Cloud Run el disco es efímero y no se comparte entre
  instancias, así que el estado tiene que vivir fuera del contenedor. En el
  sprint 3 el worker escribirá en las mismas colecciones.
- **Alternativas descartadas:**
  - Llamar a Firestore y GCS directamente desde `main.py`: el worker
    duplicaría ese código y nada se podría probar sin GCP.
  - Una interfaz con dos implementaciones (disco y GCP): se podría trabajar
    sin conexión, pero son dos implementaciones que pueden comportarse
    distinto y la de disco no se usaría en producción.
  - URLs firmadas para el PDF: no cargan a la api, pero en Cloud Run la
    service account necesita `roles/iam.serviceAccountTokenCreator` sobre sí
    misma para firmar. Cambiarlo más adelante es tocar un endpoint.
  - Bucket público: son datos personales. El bucket tiene
    `public-access-prevention` y acceso uniforme por IAM.
  - Emulador de Firestore en local: GCS no tiene emulador oficial, así que
    solo cubría la mitad. Con este volumen los recursos reales cuestan 0 €.
  - Guardar el PDF en Firestore: límite de 1 MiB por documento, y se pagaría
    leer bytes que nunca se consultan.
- **Motivo:** el código de acceso a datos se escribe una vez y lo comparten
  api y worker. Los clientes se inyectan (constructor del repositorio y
  `Depends` en FastAPI), así que un test puede sustituirlos sin tocar GCP.
- **Consecuencia:** no hay transacción entre Firestore y GCS. Se escriben
  primero los ficheros y el documento al final: si algo falla a medias
  quedan ficheros huérfanos en el bucket, nunca un documento sin su PDF.
  `created_at` se guarda como timestamp nativo (`model_dump` en modo Python,
  no JSON). Los datos de prueba en local se mezclan con los reales.
  `render_pdf` devuelve los bytes del PDF para no pasar por disco. Los
  perfiles siguen leyéndose de `data/private/`, que no existe en Cloud Run:
  hay que moverlos antes de desplegar. Probado de punta a punta con la
  oferta 1 y el perfil de ejemplo: 201, documento con timestamp nativo y PDF
  descargable.

## 018 · Los perfiles viven en Cloud Storage como JSON

- **Fecha:** 2026-10-19
- **Decisión:** los perfiles se leen de
  `gs://clau-job-assistant/profiles/profile.{idioma}.json` con
  `ProfileRepository` (`core.repository`). Son los mismos ficheros que se
  editan a mano en `data/private/` y se suben con `gcloud storage cp`. El
  campo `language` de la petición se restringe a dos letras minúsculas
  porque forma parte del nombre del objeto.
- **Contexto:** la api los leía de `data/private/`, que no existe en Cloud
  Run. El plan proponía un documento `profile/me` en Firestore, pero desde
  la decisión 011 hay un perfil por idioma y se mantiene a mano como JSON.
- **Alternativas descartadas:**
  - Firestore (`profiles/{idioma}`): lo que decía el plan, y permite editar
    campos desde la consola. Pero hace falta un script de sincronización y
    habría dos fuentes de verdad (el JSON local y Firestore) que acabarían
    divergiendo.
  - Secret Manager: es para credenciales, no para documentos (límite de
    64 KiB).
  - Copiarlos en la imagen Docker: datos personales dentro de la imagen y
    un redespliegue por cada cambio del CV.
- **Motivo:** el perfil siempre se lee entero y nunca se consulta por
  campo. Mismo criterio que la decisión 017: Firestore para lo que se
  consulta, GCS para lo que se lee entero. Lo que se edita es exactamente
  lo que se lee.
- **Consecuencia:** al cambiar el CV hay que acordarse de volver a subir el
  JSON; si no, la api usa la versión anterior sin avisar. Un perfil con un
  error de formato no se detecta al subirlo, sino en la primera petición
  (500 de validación de Pydantic). El CLI del sprint 1 sigue leyendo de
  disco.

## 019 · Imagen con uv, Cloud Build regional y Cloud Run privado con service account propia

- **Fecha:** 2026-10-20
- **Decisión:**
  - `services/api/Dockerfile` sobre `python:3.12-slim-bookworm`, con pango
    y harfbuzz instalados con apt, uv copiado de su imagen oficial (versión
    fijada) y dos `uv sync`: primero las dependencias y luego el workspace.
    El código se copia carpeta a carpeta y el proceso no corre como root.
  - La imagen se construye en Cloud Build (`services/api/cloudbuild.yaml`)
    en `europe-west4`, con buckets regionales, y se guarda en el
    repositorio `job-assistant` de Artifact Registry. `.gcloudignore`
    explícito.
  - El servicio `api` de Cloud Run se ejecuta como `api-runtime`, con
    `datastore.user` y `aiplatform.user` en el proyecto y
    `storage.objectUser` solo en el bucket. Es privado
    (`--no-allow-unauthenticated`), tiene un máximo de 2 instancias, 1 GiB
    y escala a cero.
  - Los comandos de IAM y despliegue viven en `infra/*.sh` hasta Terraform.
- **Contexto:** primer despliegue del sprint 2. La imagen construida en el
  Mac era `arm64` y Cloud Run ejecuta `amd64`. La service account por
  defecto de Compute tiene `roles/editor` en el proyecto.
- **Alternativas descartadas:**
  - Alpine: imagen más pequeña, pero `musl` obliga a compilar wheels y
    pango da guerra.
  - Multi-stage build: algo más pequeña, pero lo que pesa es pango. Queda
    como mejora.
  - `docker build --platform linux/amd64` y push desde el Mac: emula amd64
    (lento) y sube la imagen desde casa.
  - `gcloud run deploy --source .`: un solo comando, pero usa buildpacks o
    exige el Dockerfile en la raíz, y esconde los pasos.
  - La service account por defecto: funciona sin configurar nada, pero con
    `editor` un fallo en la api daría acceso a casi todo el proyecto.
  - Servicio público con login propio, o Identity-Aware Proxy: más código
    o más infraestructura para una sola usuaria. IAP queda para cuando haya
    frontend en el navegador.
  - `--min-instances=1`: sin arranque en frío, pero unos 10-15 € al mes.
- **Motivo:** mínimo privilegio y nada de claves descargadas: el servicio
  obtiene sus credenciales del metadata server. Todo en la UE. Los scripts
  dejan versionado lo que Terraform tendrá que crear.
- **Consecuencia:** sin token de Google la api responde 403 sin llegar al
  código. Para probarla, `gcloud run services proxy` o
  `curl` con `gcloud auth print-identity-token`. Probado: 403 sin token,
  GET y PDF con 200, y un POST completo con la oferta 2 en unos 16 s
  (incluye el arranque en frío). Pendientes: Cloud Build usa aún la cuenta
  por defecto de Compute con `editor` (cuenta de build propia en el sprint
  5); política de limpieza de imágenes en Artifact Registry; el tag
  `latest` es mutable.

## 020 · Identity-Aware Proxy integrado en Cloud Run, con cliente OAuth propio

- **Fecha:** 2026-10-20
- **Decisión:** el servicio `api` sigue privado (`--no-allow-unauthenticated`)
  y tiene IAP activado (`--iap`). El agente de servicio de IAP tiene
  `run.invoker` sobre el servicio y solo la cuenta de Clau tiene
  `iap.httpsResourceAccessor`. El frontend lo sirve la propia api en `/`,
  así que comparte origen con ella. Como el proyecto no tiene organización,
  IAP usa un cliente OAuth propio (`IAP api`, tipo aplicación web), creado
  a mano en la consola con la pantalla de consentimiento en modo External y
  en pruebas, y aplicado con `gcloud iap settings set` a nivel de proyecto.
- **Contexto:** con el servicio privado, el navegador no puede llamar a la
  api porque no envía tokens de Google. El cliente OAuth gestionado por
  Google solo admite usuarios de la misma organización, y en un proyecto
  sin organización los clientes OAuth no se pueden crear por API. La opción
  "Auto generate credentials" de la consola no apareció.
- **Alternativas descartadas:**
  - Seguir solo con `gcloud run services proxy`: sin configuración, pero
    solo desde un ordenador con gcloud.
  - Servicio público con login de Google verificado en FastAPI (Firebase
    Auth): código de seguridad propio, y un fallo expondría los datos.
  - Load balancer con IAP: la forma clásica, pero unos 18 $ al mes solo
    por el balanceador.
  - Frontend en un bucket o en Firebase Hosting: obliga a gestionar CORS y
    un segundo origen para la cookie de IAP.
- **Motivo:** login con Google sin escribir código de autenticación, sin
  coste y con el acceso definido en IAM, como el resto del proyecto.
- **Consecuencia:** sin sesión, la URL redirige (302) al login de Google.
  Para que IAP funcione hizo falta habilitar también la API de Cloud
  Resource Manager. El cliente OAuth no está en ningún script: Terraform
  tampoco podrá crearlo en un proyecto sin organización. El client secret
  pasó por el historial de la conversación con Claude: conviene rotarlo
  (añadir un secret nuevo al cliente, aplicarlo y borrar el antiguo). Con
  la app en modo pruebas solo entran los usuarios de prueba de la pantalla
  de consentimiento.

## 021 · El CV ocupa siempre una página como máximo

- **Fecha:** 2026-10-20
- **Decisión:** `render_pdf` maqueta el CV con WeasyPrint, cuenta las
  páginas antes de escribir el PDF y lanza `CVTooLongError` si pasan de
  una. Antes, `fit_to_one_page` recorta: mientras no quepa, quita el último
  logro de la última experiencia que tenga más de uno. Es el logro menos
  relevante de la experiencia menos relevante, según el orden que da
  Gemini. Ninguna experiencia se queda sin logros (decisión 009) y cada
  recorte queda en `warnings`. Si ni así cabe, la api responde 422.
- **Contexto:** uno de los cinco CV generados hasta ahora ocupaba dos
  páginas. Gemini no sabe cuánto ocupa su texto en la plantilla, y un
  prompt no es una garantía (decisión 007).
- **Alternativas descartadas:**
  - Pedir en el prompt que quepa en una página: sin garantía.
  - Reducir el tamaño de letra y los márgenes: conserva el contenido,
    pero empeora la lectura y también necesita un límite. Se puede añadir
    antes del recorte si se recorta demasiado.
  - Volver a pedírselo a Gemini indicando cuánto sobra: más coste y
    latencia, y tampoco garantiza nada.
  - Cortar lo que sobresale con CSS: cortaría texto a mitad de frase sin
    avisar.
  - Solo dar error si ocupa más: cumple el límite, pero deja sin CV.
  - Quitar antes secciones enteras (proyectos, voluntariado): se eligió
    recortar solo logros.
- **Motivo:** la garantía está en `render_pdf`, así que ningún camino (api
  o CLI) puede generar un PDF de dos páginas, aunque se olvide recortar. El
  recorte no vuelve a llamar a Gemini, solo maqueta otra vez (milisegundos).
- **Consecuencia:** probado con un CV forzado a 3 páginas: se recortó a una
  (de 9 y 6 logros pasó a 3 y 1, primero en la experiencia menos
  relevante), con un aviso por logro, y `render_pdf` rechazó la versión sin
  recortar. Un perfil que no cabe ni con un logro por experiencia da error.
  Al regenerar la oferta del CV de dos páginas, esta vez Gemini lo escribió
  más corto y no hizo falta recortar: el recorte depende de cuánto escriba
  Gemini en cada ejecución.

## 022 · api y worker separados por Pub/Sub push, con tasks idempotentes

- **Fecha:** 2026-10-20
- **Decisión:**
  - `POST /applications` sube la oferta a GCS, crea `tasks/{id}` en
    Firestore (`queued`), publica en el topic `cv-tasks` un `TaskMessage`
    con solo el `task_id` y responde 202. El frontend consulta
    `GET /tasks/{id}` cada 2 s.
  - Un mensaje es una candidatura entera: extraer, adaptar y generar el PDF.
  - La subscription push `cv-tasks-worker` llama a `POST /pubsub` del
    servicio `worker`, firmando con la cuenta `pubsub-push` (solo tiene
    `run.invoker` sobre el worker). Reintentos de 10 s a 10 min; al quinto
    fallo, el mensaje va a `cv-tasks-dead`, que guarda 7 días la
    subscription `cv-tasks-dead-inspect`.
  - `TaskRepository.claim` marca el task como `running` en una transacción
    de Firestore, solo si está `queued` o `failed`, o lleva más de 10 min
    en `running` (lease). Si no, el worker responde 204 sin hacer nada.
  - Errores permanentes (sin oferta, sin perfil, CV que no cabe): task
    `failed` y 204. Transitorios: task de vuelta a `queued` con el error y
    500, para que Pub/Sub reintente.
  - Cada servicio tiene su identidad: `api-runtime` (Firestore, bucket,
    publicar en `cv-tasks`; ya no tiene `aiplatform.user`) y
    `worker-runtime` (Firestore, bucket, Vertex AI). La api ya no depende
    del paquete `worker` ni lleva WeasyPrint. Su imagen baja de 838 a 617 MB
    y su memoria, de 1 GiB a 512 MiB.
- **Contexto:** en el sprint 2 la petición esperaba unos 20 s a Gemini y al
  PDF. Si algo fallaba, se perdía el trabajo sin reintento. Pub/Sub entrega
  *at least once*.
- **Alternativas descartadas:**
  - Cloud Tasks: más simple para un solo consumidor, pero un topic de
    Pub/Sub se podrá reutilizar con varios consumidores en el sprint 4.
  - Pull con un worker pool: sin IAM de push, pero no escala a cero.
  - Una cadena de mensajes (extraer y luego generar): un fallo solo repite
    su paso, pero hay el doble de estados y código. Se revisará al añadir
    la carta.
  - Mirar el estado sin transacción: dos entregas simultáneas procesarían
    las dos.
  - *Exactly-once delivery*: solo existe en subscriptions pull.
  - Meter la oferta en el mensaje: el worker no leería Firestore al
    empezar, pero habría datos duplicados y un reintento tardío podría
    usar datos viejos.
  - Heartbeat en vez de lease fijo: detecta antes una instancia muerta,
    pero necesita un hilo extra; con trabajos de ~20 s no compensa.
- **Motivo:** la petición HTTP responde en lo que tardan tres escrituras,
  el trabajo caro se reintenta solo y un mensaje duplicado no genera dos CV
  ni paga dos veces a Gemini.
- **Consecuencia:** probado en local (10 `claim` simultáneos: solo uno
  gana; una segunda entrega del mismo mensaje no repite nada) y en la nube
  (POST → `running` → `done` en ~70 s). En la nube, las tres primeras
  entregas dieron 403 porque el `run.invoker` de `pubsub-push` aún no se
  había propagado, y Pub/Sub lo resolvió reintentando. Esos 403 no cuentan
  en `attempts` del task, pero sí en los 5 intentos de Pub/Sub antes de la
  DLQ. Un task cuyo mensaje acaba en la DLQ se queda en `queued` con su
  último error; el frontend se rinde a los 5 minutos. La configuración de
  Cloud Build pasa a ser común a los dos servicios (`infra/cloudbuild.yaml`
  con `_SERVICE`).

## 023 · Matching de skills con Gemini, seguimiento por estados y eventos a BigQuery

- **Fecha:** 2026-10-20
- **Decisión:**
  - **Matching:** Gemini (`match_skills.md`, temperatura 0) solo empareja
    cada skill obligatoria y deseable de la oferta con un nombre de skill del
    perfil, o con null. El código (`build_skill_match`, función pura)
    descarta emparejamientos con nombres que no están en el perfil, cuenta
    como no cubierta cualquier skill que Gemini se salte y calcula la
    puntuación: 80 % obligatorias y 20 % deseables (si falta una lista, la
    otra pesa el 100 %). Se guarda en `Application.match` con las cubiertas,
    las obligatorias que faltan (`gaps`) y las deseables que faltan.
  - **Seguimiento:** `Application.status` (`cv_ready`, `applied`,
    `screening`, `interview`, `offer`, `rejected`, `ghosted`) se cambia con
    `PATCH /applications/{id}` desde un panel en la web, que lista las
    candidaturas con `GET /applications`.
  - **Analítica:** cada candidatura nueva (worker) y cada cambio de estado
    (api) publica un `ApplicationEvent` en el topic `application-events`. La
    subscription de BigQuery `application-events-bigquery` lo escribe en la
    tabla `job_assistant.application_events` (append-only, particionada por
    día, `--use-table-schema` y `--write-metadata`), con DLQ a los 5
    intentos. La vista `applications_current` quita duplicados por
    `event_id` y se queda con el último evento de cada candidatura. Encima,
    un informe de Looker Studio creado con la Linking API.
- **Contexto:** el sprint 4 del plan: matching de skills, eventos a
  BigQuery, vista de estado actual y dashboard.
- **Alternativas descartadas:**
  - Comparar los nombres en código: gratis y determinista, pero "GCP" no
    coincidiría con "Google Cloud Platform", y los nombres de la oferta los
    escribe Gemini al extraer.
  - Que Gemini dé la puntuación directamente: no se puede comprobar, y el
    mismo sesgo de exagerar de las decisiones 008 y 015.
  - Hacer el matching en la misma llamada que adapta el CV: una llamada
    menos, pero mezcla dos tareas y la del CV no usa temperatura 0.
  - Escribir en BigQuery desde el código (cliente o Storage Write API):
    más código y más permisos en cada servicio. Con la subscription de
    BigQuery no hay código de ingesta.
  - `--drop-unknown-fields`: un campo nuevo sin columna se perdería sin
    avisar; sin él, falla y va a la DLQ.
  - Una columna de fecha propia en el evento: `publish_time` de
    `--write-metadata` ya es la hora del cambio.
  - Reconstruir el histórico de las candidaturas anteriores: casi todas
    eran pruebas con las ofertas de ejemplo, y tendrían la fecha de la
    reconstrucción, no la real.
- **Motivo:** el código verifica lo que se puede verificar, como en la
  decisión 007, y la analítica no añade código de ingesta ni permisos sobre
  BigQuery a los servicios.
- **Consecuencia:** el matching cuesta una llamada más a Gemini Flash por
  candidatura. Solo mira la lista de skills del perfil: algo que aparece en
  la experiencia pero no en las skills cuenta como gap. Si el worker no
  puede publicar el evento `created`, lo registra en el log y sigue, sin
  reintentar el task. En cambio, el `PATCH` falla si no puede publicar el
  suyo. El histórico en BigQuery empieza en el sprint 4. Hay un evento de
  prueba de una candidatura de ejemplo (Nubelia Analytics). Probado en la
  nube: oferta 2 con encaje 53 (gaps: Kubernetes y Terraform); `created` y
  `status_changed` llegaron a BigQuery en unos 2 s.
