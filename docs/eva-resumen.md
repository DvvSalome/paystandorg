# Eva — resumen de lo que hace, lo hecho y lo que falta (2026-11-14)

Eva (agente OpenClaw en el servidor de Iván) **preclasifica, nunca decide**. El comité decide; el formulario nunca habla de puntaje.

## Qué hace hoy
Una corrida del pipeline `intake_pipeline.py` v3, en 7 pasos:
1. **Ingest**: lee las postulaciones completas de Supabase (vista `intake_rows`, clave de servicio solo en su servidor), crea la carpeta `GR-2027-xxx` en Drive y la fila en el registro.
2. **Limpieza** de los datos. 3. **Clasificación** (etapa Inicial / Establecida, ruta Nueva / Renovación).
4. **Flags** (documentos, coherencia, OFAC y demás). 5. **Puntaje** y semáforo. 6. **Paquete** para el comité. 7. **Escritura** en el Sheet de intake (pestañas 2–8).
Descarga los documentos adjuntos del bucket privado de Storage para analizarlos. Avisa por Slack a `#foundation-ops` (error o corrida completa).

## Qué se hizo (nov 2026)
- **Conexión con Supabase** en lugar de Wix/Apps Script: vista `intake_rows` generada desde su `QUESTION_MAP` (62 columnas: `application_id`, `finalized_at`, `Timestamp` + 59 preguntas). Solo muestra postulaciones `complete` con más de 2 minutos de finalizadas.
- **Descarga de documentos** desde Storage (parche C1), probada con archivos reales.
- **Correcciones**: `with_retry` (el pipeline no importaba), `match_grantee` con acentos y orden de nombres (OFAC), semáforo en rojo si falla una compuerta dura.
- **Formulario de 59 preguntas**: sin A4 (repetía G2); F2, F3 y E10 obligatorias para todos (se retiró el tramo de $10,000). El pipeline ya espera esta versión.
- **Operación más segura**: un watermark por ambiente (producción arranca vacío a propósito), candado de ejecución (una segunda corrida sale con código 75: no es error), el watermark no avanza si falla la escritura al Sheet.
- **Pruebas** en git y CI (`eva/test_*.py`).

## Verificado
- 12 nov: ensayo completo en TEST con datos reales de Supabase, score 85, verde.
- 14 nov: APP-2027-0001 (demo) leída de la vista (62 columnas), documentos descargados, pipeline completo en TEST: score **89/93, verde**, bajo la carpeta de Drive de prueba, sin tocar producción ni avisar a Slack.
- Esperado con la demo: `doc_text_extraction_failed` (PDF de 13 bytes) y `cost_per_participant` diferido (falta la mediana del ciclo).

## Pendiente
- **Cron de producción** (`--environment production`, cada ~30 min): crearlo solo con las tablas en cero.
- **Corrida de aceptación** con postulaciones 2026 reales (ONG madura, proyecto nuevo, renovación): si etapa o semáforo difieren del equipo en más de 1 de cada 3, ajustar antes de abrir.
- Rotar el token de Google. Aviso de Slack sin interruptor (en pruebas se silencia con un `openclaw` falso en el PATH). Confirmar por qué `total_processed` queda en 0 en el watermark de TEST.
- Paquete de correcciones de Eva (AGENTS/skills) y skill de preguntas de intake: sin aplicar.
- Instalar `pymupdf` y probar con un PDF real, para confirmar la extracción de texto.
