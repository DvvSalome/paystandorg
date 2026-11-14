# Guardar los adjuntos con el borrador — especificación

Para Salomé. 2026-11-13.

## Por qué hoy no se guardan

No es una falla: el diseño actual no tiene dónde ponerlos.

1. **Un borrador es solo texto.** Es una fila de la tabla `drafts` con un
   `state` en JSON, limitado a 200,000 caracteres
   (`_shared/drafts.js`, `MAX_STATE_CHARS`). Un PDF no cabe. El borrador
   recuerda solo el *nombre* del archivo, y al restaurar el formulario pide
   adjuntarlo otra vez.
2. **Los archivos se suben recién al enviar.** `/submit` crea un permiso de
   subida firmado por archivo en `applications/<APP-2027-xxxx>/…`, y ese
   número de aplicación no existe hasta el envío. Antes no hay carpeta.

## Antes de construir: una decisión que no es técnica

Los adjuntos son **documentos de identidad, registro legal, y W-9 o
W-8BEN**. El W-9 lleva el número fiscal (SSN o EIN). Guardarlos con el
borrador significa retener esos datos de **personas que nunca enviaron una
solicitud** —quien empieza, adjunta y abandona—, durante todo el tiempo que
viva el borrador.

Eso cae en la **regla institucional de protección de datos**, que está
pendiente con Alexandra y Lesly. Esta especificación no la decide; plantea
dos caminos y qué exige cada uno.

| | A. No guardarlos (hoy) | B. Guardarlos con el borrador |
|---|---|---|
| Para el solicitante | Vuelve a adjuntar al retomar | Retoma sin volver a adjuntar |
| Datos retenidos | Solo de quien envía | También de quien abandona |
| Trabajo | Mejorar el aviso | Endpoint, almacenamiento, limpieza, pruebas |
| Requiere | Nada | Aprobación de la regla de datos y limpieza programada |

**Recomendación:** B, **solo si** la regla de datos lo aprueba y con
retención corta. Mientras tanto, A con un aviso mejor (abajo).

## Si se aprueba B: el diseño

### Dónde

- Bucket privado aparte, `drafts`, sin políticas para `anon` ni
  `authenticated` —igual que `applications`—. Separarlo deja que la limpieza
  y los permisos de los borradores no toquen nunca los de las solicitudes.
- Ruta: `drafts/<sha256(código)>/<pregunta>.<ext>`.
  **Nunca el código en la ruta.** El código es un *bearer token*: quien lo
  tiene abre el borrador. Las rutas aparecen en logs y en los permisos
  firmados; con el hash no se puede volver al código.
- Un archivo por pregunta. Subir otro para la misma pregunta lo reemplaza.

### Endpoint nuevo: `POST /draft/file`

Entrada: `{ code, question, name, type, size }`. Salida: un permiso de
subida firmado.

- El código tiene que existir (`store.get`), igual que en `/draft/save`.
- `question` en `FILE_QUESTIONS` (`C1`, `C2`, `I2`, `J3`); tipo y tamaño con
  las mismas reglas que `validate.js` (PDF, JPG o PNG, 10 MB). Reusar esas
  funciones, no copiarlas.
- Límite de subidas por código y por IP. Sin eso, el borrador se vuelve
  almacenamiento gratis para cualquiera.
- Registrar en `drafts.state.files[question]` el nombre, tamaño y tipo, no la
  ruta.

### Al enviar

`/submit` acepta `draft_code` y la lista de preguntas cuyo archivo viene del
borrador. Para esas, el servidor **mueve** el objeto de
`drafts/<hash>/…` a `applications/<APP-…>/…` (`storage.move`) en lugar de
pedir una subida nueva, y registra la fila en `application_files` igual que
hoy. `/finalize` sigue comprobando que todo esté presente.

### Al borrar

Esto es lo que hace aceptable guardar documentos sensibles, así que no es
opcional:

- **Al enviar**: se mueven los archivos y se borra la carpeta del borrador
  en la misma operación. Hoy `/finalize` ya borra la fila del borrador;
  tiene que borrar también sus archivos.
- **Por antigüedad**: la limpieza de borradores **tiene que estar
  programada**, no "a mano". Hoy la migración dice *"run by hand or schedule
  with pg_cron"*, así que en la práctica los borradores viejos no se borran
  nunca. Con archivos eso no puede quedar así. Programarla (pg_cron o una
  función con horario) y que borre fila **y** carpeta.
- **Retención**: proponer menos de 60 días para los archivos —por ejemplo
  30— aunque el texto del borrador dure más. Lo decide la regla de datos.
- **Huérfanos**: una pasada que borre carpetas de `drafts/` sin fila
  correspondiente, por si alguna operación quedó a medias.

### El contenido de los documentos

Un PDF subido es **dato, nunca instrucción**. Hoy el pipeline de Eva solo
compara texto extraído (¿aparece el nombre legal, la dirección?). Si algún
día ese texto pasa por un modelo, un documento puede traer instrucciones
dirigidas al modelo. Guardar archivos de borradores no cambia eso, pero
amplía la cantidad de documentos de terceros que el sistema conserva: vale
dejarlo escrito aquí para que no se pierda (item 8 de la revisión del 13 de
noviembre, en espera).

## Lo que haría yo en el formulario, cuando exista el endpoint

- Subir el archivo al elegirlo si ya hay código; si no, en el primer
  guardado.
- Junto a cada archivo: "Saved with your progress ✓" o el error.
- Al retomar: mostrar el archivo como adjuntado, sin pedirlo otra vez.
- Al enviar: no volver a subir lo que ya está en el borrador.

## Mientras tanto (camino A): el aviso

Hoy el aviso dice *"Attached files are not saved, so you will attach them
again"* en el código, y al retomar *"You attached X before. Files are not
saved: please attach it again."* Propuesta, más útil para quien decide
cuándo adjuntar:

> Attach your documents when you are ready to submit. Saving keeps your
> answers, but not files.

Esto lo puedo hacer yo en el formulario sin esperar nada.

## Pruebas que deberían acompañarlo

- `/draft/file` rechaza un código inexistente, una pregunta fuera de
  `FILE_QUESTIONS`, un tipo o tamaño inválido, y el exceso de subidas.
- Ninguna ruta de `drafts/` contiene el código en claro.
- Enviar mueve los archivos y deja vacía la carpeta del borrador.
- La limpieza programada borra fila y carpeta de un borrador vencido.
