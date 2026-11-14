# Enviar el código por correo — especificación

Para Salomé. Estado al 2026-11-13.

## El hallazgo: casi todo ya existe

Buscando esto encontré que la tubería está construida y solo le falta el
último tramo. No hace falta una pregunta nueva ni una columna nueva.

| Pieza | Dónde | Estado |
|---|---|---|
| `D1` es `composite` con una parte `email` | `site/assets/questions.js` | ya está |
| El correo se guarda aparte en `V.D1__email` | `site/assets/form.js:337` | ya está |
| `snapshot()` lo manda: `email: V.D1__email \|\| ""` | `site/assets/form.js:684` | ya está |
| `saveDraft` lo valida, baja a minúsculas, corta a 200 | `supabase/functions/_shared/drafts.js:37` | ya está |
| Columna `email` en la tabla, comentada *"for a future email me my code"* | `supabase/migrations/20261113000000_drafts.sql:8` | ya está |
| Enviar el correo | — | **falta** |
| El correo llega a tiempo para el primer guardado | — | **falta** |

## Los dos huecos

### 1. D1 está en la sección D, la quinta

El código se emite en el primer guardado, y el primer botón de guardar está
al final de la sección 0. Para entonces `V.D1__email` está vacío, así que
`saveDraft` recibe `email: null` y no hay a dónde enviar nada.

**Propuesta: mover D1 a la sección 0**, después de las listas de
verificación. Es cambiar una propiedad — `s: "D"` por `s: "0"` — y no toca
nada más:

- `QUESTION_MAP` sigue mapeando `D1 -> D1_Primary_Contact`. La sección es
  presentacional; no entra en el mapa.
- La vista `intake_rows` se genera del `QUESTION_MAP`, así que no cambia.
- El pipeline de Eva sigue leyendo `D1` igual, incluida su validación
  `nonsense_invalid_email:D1`.
- Las 60 preguntas siguen siendo 60.

La sección D queda con D2, D3 y D4 — autorización, firmante y copia — que
siguen siendo coherentes juntas como "quién firma".

**Por qué no una pregunta nueva arriba.** Sería preguntar el correo dos
veces: el texto de ayuda de D1 ya dice *"We will use this email for all
correspondence about your application"*, así que es el mismo dato. Es
exactamente el problema que Iván señaló con A4 y G2 — dos fuentes para una
cosa — y no conviene repetirlo aquí.

### 2. Nadie envía el correo

No hay servicio de correo configurado. El commit `0effcb5` de hoy
precisamente quitó la promesa de un correo de confirmación por eso.

**Qué tiene que pasar:** cuando `saveDraft` crea un código nuevo (la rama
`store.insert`, no la de `update`) y hay un `email` válido, enviarlo.

Requisitos, no implementación — el proveedor lo eliges tú:

- **Solo en la creación**, no en cada guardado. Alguien que guarda doce veces
  no quiere doce correos con el mismo código.
- **El fallo del correo no debe fallar el guardado.** Si el envío revienta,
  el borrador ya quedó guardado y el código ya se muestra en pantalla. Que
  el error se registre y el guardado devuelva 200.
- **Límite de envío por dirección**, no solo por IP. Ya existe
  `store.rateLimited`; un `draft:mail:<hash del correo>` evita que el
  formulario se use para mandar correo a terceros.
- **Nunca registrar el cuerpo del correo** en logs.

## Lo que el correo está entregando es una credencial

Esto importa para redactarlo. El código es un *bearer token*: cualquiera que
lo tenga abre el borrador, y el borrador contiene datos personales del
solicitante. El aviso del formulario ya lo dice —*"anyone with this code can
open your draft"*— y el correo tiene que decirlo igual.

De ahí tres cosas concretas:

- **No reenviar el correo** a nadie más. Que el texto lo pida explícitamente.
- **Nada de datos del borrador en el cuerpo.** Solo el código y el enlace.
  Si el correo se filtra, que no se filtre además el contenido.
- El borrador **se borra al enviar la solicitud** y se ignora a los 60 días.
  Eso ya está en la migración; vale decirlo en el correo para que la persona
  sepa que el código no vive para siempre.

## Y lo que hay que decirle a quien no deja correo

El campo de correo de D1 es parte de una pregunta obligatoria, pero alguien
puede guardar antes de llenarla si movemos D1 y aún así la deja en blanco.
En ese caso el código **solo existe en pantalla**, y hoy el aviso dice
*"Keep it somewhere safe"* sin explicar que no hay recuperación.

Propuesta de texto, cuando no hay correo:

> Apunta este código ahora. Sin un correo donde enviártelo, **no hay forma de
> recuperarlo**: si lo pierdes, hay que empezar la solicitud de nuevo.

Y cuando sí hay correo:

> Te lo enviamos a <correo>. Guárdalo igual: es la única forma de volver a
> tu solicitud.

El `localStorage` ayuda en el mismo navegador, pero no sirve si cambian de
dispositivo o limpian el navegador — que es justo el caso que el guardado
existe para resolver.

## Resumen de lo que cambia

1. `questions.js`: `D1` pasa de `s: "D"` a `s: "0"`. Correr después
   `scripts/sync-questions.sh` y `python3 scripts/build-function-single.py`
   (`node tests/questions.test.mjs` falla si se olvida).
2. `drafts.js`: enviar el correo en la rama de creación, sin que su fallo
   afecte el guardado, con límite por dirección.
3. `form.js`: el texto del aviso según haya correo o no.
4. Elegir proveedor de correo y guardar su llave donde van los secretos
   —nunca en el repo ni en `config.js`.
