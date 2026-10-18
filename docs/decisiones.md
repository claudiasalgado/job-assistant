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
