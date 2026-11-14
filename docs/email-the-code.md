# Enviar el código por correo — especificación

Para Salomé. Estado al 2026-11-13.

## Estado

**Hecho en el formulario (2026-11-13), rediseñado el mismo día:** el
correo se pide en el primer guardado, en una tarjeta que se abre junto al
botón que la persona pulsó, atado a la parte de correo de D1 en las dos
direcciones. El código aparece en una tarjeta grande con botón de copiar, y
después queda a mano en una ficha arriba del formulario. Los guardados
siguientes solo dicen "Saved at 14:32 ✓". El aviso es honesto según la
bandera `emailCodes` de `config.js`.

Probado en navegador: la tarjeta no guarda nada hasta que la persona decide;
un correo inválido se rechaza ahí mismo; el correo de la tarjeta llena D1
mientras se escribe; el segundo guardado no vuelve a preguntar; si D1 ya
tiene correo, el primer guardado no pregunta; volver en el mismo navegador
muestra "Welcome back" y restaura el borrador con los dos correos llenos; y
se ve bien a 375 px de ancho.

**Falta, para Salomé — el envío:**

1. En `drafts.js`, enviar el correo en la rama de creación (`store.insert`),
   sin que su fallo afecte el guardado, con límite por dirección.
2. Elegir proveedor y guardar su llave con los secretos.
3. Cuando el envío funcione, poner `emailCodes: true` en
   `site/assets/config.js`. **Solo entonces** el formulario dice "We sent it
   to …". Mientras esté en `false` dice "Write this code down now: there is
   no way to recover it", porque prometer un correo que no llega es peor que
   no prometer nada.

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

### 1. El correo llega tarde

El código se emite en el primer guardado, y se puede guardar desde el pie
de cualquier sección. Pero el correo vivía solo en D1, en la sección D, la
quinta. Quien guardaba antes de llegar ahí mandaba `email: null` y no había a
dónde enviar nada.

**Decisión (Iván, 2026-11-13): el correo se pide antes de que exista el
código, y vive también en D1.**

Primero se pensó en un campo fijo en la barra de arriba. Se descartó por
experiencia de uso: obligaba a ver seis cosas en la puerta del formulario
—explicación, correo, botón de guardar, código, campo para retomar y
mensajes— antes de escribir nada, con "Save and get my code" como botón
principal de un formulario vacío.

Quedó así, un momento a la vez:

| Momento | Qué ve la persona |
|---|---|
| Llega | Una línea: no tiene que terminar de una vez. Un enlace discreto "Have a code?". |
| Llega y este navegador recuerda un borrador | "Welcome back" con "Continue where I left off". |
| Primer guardado | Junto al botón que pulsó, una tarjeta: "Save your progress", su correo, "Save and get my code" o "Save without email". |
| Código emitido | En ese mismo lugar, el código grande con "Copy code". |
| Guardados siguientes | Solo "Saved at 14:32 ✓". Nada vuelve a preguntar. |
| Después | Arriba, una ficha compacta con el código y su botón de copiar. |

El primer guardado es el momento en que pedir el correo tiene sentido para
la persona: está a punto de recibir algo que tiene que poder recuperar. Si D1
ya tiene un correo válido, no se pregunta.

No hay ventanas modales: el formulario vive en un iframe de altura
automática, y una capa fija se abriría arriba del contenido, lejos de donde
está la persona.

#### Un solo valor, dos lugares

El campo de arriba y la parte de correo de D1 son **dos vistas del mismo
`V.D1__email`**. Editar cualquiera de los dos cambia ambos. No pueden
divergir.

Esto es lo que lo separa del problema de A4/G2, y por eso importa hacerlo
así y no de otra forma:

| | Cómo funciona | Resultado |
|---|---|---|
| **Atado (este)** | Los dos campos leen y escriben `V.D1__email`. | Un dato, dos vistas. No hace falta reconciliar nada. |
| Pre-llenado (no) | D1 copia el de arriba y después queda independiente — el patrón actual de G2. | Divergen, y harían falta banderas de incoherencia como las de A4/G2. |

Nombre, cargo y teléfono se quedan en D1, en la sección D, donde tienen
contexto. Solo el correo se adelanta, porque es lo único que el guardado
necesita.

Para el resto del sistema no cambia nada: `QUESTION_MAP`, la vista
`intake_rows` y el pipeline de Eva —incluida su validación
`nonsense_invalid_email:D1`— siguen leyendo D1 igual. Las preguntas siguen
siendo 60.

#### Tres reglas que hay que respetar

- **Arriba es opcional para guardar; en D1 es obligatorio para enviar.**
  Quien guarde sin correo puede hacerlo y recibe el aviso de que el código no
  se recupera (texto más abajo). D1 sigue siendo obligatorio, así que nadie
  envía la solicitud sin correo.
- **Cambiar el correo después de recibir el código** no obliga a reenviarlo:
  el código anterior sigue valiendo. Los correos siguientes van a la
  dirección nueva.
- **Restaurar el borrador tiene que llenar los dos campos.** `snapshot()`
  guarda valores por control (`form.js:672`). El campo de arriba no debe
  guardarse como control propio: tiene que leer y escribir `V.D1__email`, y
  `restore()` repintarlo desde ahí. Si se guardan por separado, al restaurar
  uno de los dos puede quedar vacío —o peor, con un valor distinto— y ya hay
  dos datos otra vez.

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

El correo de arriba es opcional para guardar, así que alguien puede pedir su
código sin dejarlo. En ese caso el código **solo existe en pantalla**, y hoy el aviso dice
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

1. `form.js`: la tarjeta del primer guardado, con un correo atado a
   `V.D1__email` en las dos direcciones. `snapshot()` no lo guarda aparte y
   `restore()` repinta los dos. **Hecho.**
2. `drafts.js`: enviar el correo en la rama de creación (`store.insert`), sin
   que su fallo afecte el guardado, con límite por dirección.
3. `form.js`: el texto del aviso según haya correo o no. **Hecho.**
4. Elegir proveedor de correo y guardar su llave donde van los secretos
   —nunca en el repo ni en `config.js`.

`questions.js` no cambia: D1 sigue en la sección D con sus cuatro partes.
