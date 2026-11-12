# Integración con Eva (pipeline de intake v3) — estado al 2026-11-11

## Lo que sabemos del pipeline (leído del código que Eva mostró)
- `scripts/intake_pipeline.py` v3 (~195 KB), desplegado en el servidor de Eva el 2026-11-11. `QUESTION_MAP` v3 de 61 entradas, copiado en `supabase/eva_question_map.json`.
- **Ya tiene fuente Supabase.** `fetch_source_rows()` (línea ~1065) lee `config.ingest.source`; si es `supabase` llama a `fetch_supabase_rows()` (~991):
  - PostgREST `GET {url}/rest/v1/{table}?select=*&order={timestamp_column}.asc&limit={page_size}` y `&{timestamp_column}=gt.{watermark}`.
  - Espera una tabla **plana**: una columna por pregunta con el nombre del `QUESTION_MAP`. Pasa los nombres por `_normalize_source_headers()` (no visto aún).
  - Valores: `None` → `""`, listas/objetos → JSON, booleanos → `Yes`/`No`.
  - La clave sale de un archivo (`load_supabase_key`, ruta por defecto `DEFAULT_SUPABASE_KEY_PATH`, chmod 600). Nunca del config.
  - Si Supabase falla y `fallback_to_sheets` es true, lee la hoja y avisa por Slack.
- **IDs:** `resolve_app_id()` (~1139) usa el ID que trae la fila si existe una columna `App_ID`, `Application_ID`, `app_id` o `application_id` y cumple `^[A-Z]{2,6}-\d{4}-\d{3,6}$`. Mismo ID + misma fecha = reenvío (se salta); mismo ID + otra fecha = se procesa con sufijo `-RNN` y un aviso.
- **Idempotencia:** IDs ya presentes en la pestaña "2. Cleaned" se saltan. El watermark solo avanza en el paso 7 (WRITE).
- **Efectos en el paso 1 (INGEST):** por cada solicitante nuevo crea una carpeta `GR-2027-xxx - Nombre` en Drive y una fila en el Grantee Registry, antes de cualquier revisión. Necesita el token de Google aunque los datos vengan de Supabase.
- Documentos: hoy solo descarga enlaces o IDs de Google Drive (`c1_is_downloadable`).

## Decisión: opción A (Eva lee de Supabase)
Elegida por Salome el 2026-11-11. Implementación sin tocar el pipeline salvo los documentos:
- **Vista `intake_rows`** (`supabase/migrations/20261112000000_eva_view.sql`, generada por `scripts/gen-eva-view.py`):
  - una columna por pregunta con el nombre exacto del `QUESTION_MAP`; casillas unidas con `"; "`;
  - `application_id` (el pipeline lo usa como App_ID: el mismo número del correo al solicitante);
  - `"Timestamp"` como texto `YYYY-MM-DDTHH:MI:SSZ` (formato que Eva recomendó) y `finalized_at` (timestamptz) como columna de filtro;
  - solo aplicaciones `complete` con más de 2 minutos (evita que una aplicación llegue "detrás" del watermark y se salte);
  - documentos C1, C2, J3 como `storage:<ruta>`.
  - Bloquea el acceso con la clave pública (anon/authenticated) a tablas, vista, contador y funciones.
  - Probada en Postgres 16: 63 columnas, filtros, permisos, y aplicar la versión nueva encima de la anterior.
- **Parche de documentos:** `supabase/eva_patches/` (`pipeline_c1_storage.py`, `README.md`, prueba). Hace que el bloque de C1 (línea ~3021) descargue `storage:<ruta>` desde Supabase Storage. Se aplica a mano en el pipeline: dos líneas cambian y se pega una función.
- Descartado: `supabase_source.py` (módulo propio de lectura). Duplicaba `fetch_supabase_rows`.

## Configuración que debe poner Iván (`scripts/data/intake_sheets_config.json`)
```
"ingest": {
  "source": "supabase",
  "fallback_to_sheets": false,
  "supabase": {
    "url": "https://gkaukpnmpfdpljofnlxy.supabase.co",
    "table": "intake_rows",
    "timestamp_column": "finalized_at",
    "key_file": "<ruta chmod 600 con la service_role key>"
  }
}
```

## Estado del lado de Iván (2026-11-12)
- Hecho según Iván: 1) token de Google, 3) config de ingest, 5) carpetas de prueba borradas. Falta verificar con Eva que el token refresca.
- 2) clave de servicio: Iván la tomó del proyecto y la puso (2026-11-12). Falta su prueba con curl (debe dar 200).
- Eva probó la clave del archivo `secrets/supabase_service_key.txt`: `applications` responde 200.
- Pendiente: 4) parche de documentos (`supabase/eva_patches/README.md`); aplicarlo en una copia con respaldo.

## Verificado contra el Supabase real (2026-11-12)
- Envío completo desde el formulario (datos ficticios "(DEMO)"): `submit` 200, subida de 2 archivos a Storage 200, `finalize` 200 (comprueba que los archivos existen). ID asignado: `APP-2027-0002`.
- Con la clave pública: `applications` y `application_files` responden `[]` (RLS bloquea), pero **`next_application_id()` era ejecutable por cualquiera** (gastó el `APP-2027-0001`). La migración `20261112000000_eva_view.sql` lo cierra: **aún no está aplicada** (la vista `intake_rows` da 404).
- El token de Supabase guardado en el entorno de Claude solo permite lo que Supabase le concedió: le faltan `database_read` y `edge_functions_read`, así que las migraciones se aplican desde el panel (SQL Editor) o con la CLI.
- Limpieza pendiente tras las pruebas: borrar la aplicación `APP-2027-0002` y sus archivos de Storage, vaciar `rate_events`, y `alter sequence application_seq restart with 1;`.

## Aplicado en el servidor de Eva (2026-11-12)
- Línea 990: `@with_retry(max_attempts=3)` -> `@with_retry` (el decorador no acepta argumentos; el pipeline no se podía importar).
- Parche de C1 aplicado en `step_flag`. Respaldo: `scripts/intake_pipeline.py.bak-2026-11-12`.
- Prueba real: `download_supabase_doc('storage:APP-2027-0002/C1-demo-registro-y-estatus.pdf')` -> `13 application/pdf b'%PDF-1.4'`.
- `regression_tests.py --all`: 130 OK / 11 fallos, igual antes y después del parche. Fallos: `KeyError 'B9'` (suite cleaning), 3 de scoring (puntajes ~16 en vez de >=90), 1 de config (B9), 1 de errors (app perfecta puntúa 14). `scoring_verify.py` fixtures: 5/5.
- Por aclarar antes de procesar solicitantes reales: si `B9` y otros IDs viejos aún se usan en el CÓDIGO del pipeline (no solo en las pruebas) y por qué una app perfecta puntúa tan bajo.

## Verificado por Eva (2026-11-12, solo lectura)
- Vista `intake_rows` leída con la clave del servidor: HTTP 200, 2 filas, 63 columnas con los nombres del QUESTION_MAP.
- Ruta de lectura del propio pipeline (`fetch_supabase_rows`): 63 columnas, 2 filas, valores bien ubicados; `Timestamp` normaliza a `2026-11-12T16:52:34Z`; `C1_Registration_Doc` llega como `storage:...`.
- Config `ingest` (Iván): `source: supabase`, `table: intake_rows`, `timestamp_column: finalized_at`, `fallback_to_sheets: false`, clave en archivo.
- `KeyError 'B9'` y los puntajes bajos vienen de `regression_tests.py` (fixtures con IDs v2); el código del pipeline ya trata B9/E14/E15 como eliminados. `scoring_verify.py` 5/5.
- Hallazgos para el lanzamiento:
  - **Un solo watermark** (`cache/intake_watermark.json`) para test y production, y los dos ambientes leen la misma tabla de Supabase: no correr `--environment test` con aplicaciones reales; idealmente un watermark por ambiente.
  - `send_slack_notification` avisa a `#foundation-ops` (8-10 sitios, sin opción para apagarlo). Para ensayos: poner un `openclaw` falso primero en el PATH (sale con código 1 y el pipeline cae a stderr).
  - `step_ingest` crea carpeta `GR-2027-xxx` en Drive y filas en "0. Grantee Registry"; `step_clean` reescribe `scripts/data/grantee_registry.json`; `step_ingest` actualiza "1. Form Responses" (línea ~908, revisar que no escriba filas arbitrarias con la fuente Supabase).
  - La carpeta de pruebas `1Kb-uzMvjUhlqQS7bcAoF8FyW342guovz` NO es accesible con el token de Eva (404): es de otra cuenta. No hay modo dry-run.

## Ensayo del pipeline con datos de Supabase (2026-11-12, ambiente TEST, run 20261112-202123)
- 7/7 pasos OK con las 2 aplicaciones demo (`APP-2027-0002` y `0003`): los IDs del formulario se respetaron; 5 pestañas escritas de forma atómica, dashboard de 26 métricas, 6 filas de log.
- Resultado: perfil Establecida, pilar Economic Empowerment, **score 85/93 (normalizado 91,4), semáforo VERDE**. Dependencia 23,5 % (= 20.000 / 85.000: confirma que A4/G2 y B5 llegan a los campos correctos).
- Flags esperados: `duplicate_name` (mismo nombre y correo en las 2 demo), `doc_text_extraction_failed` (el PDF demo es falso), `name_mismatch`/`address_mismatch` en PENDING. `cost_per_participant` diferido (faltan 3 valores para la mediana).
- A revisar: ambas demo se emparejaron con el grantee histórico `GR-2026-015` (posible falso positivo del emparejamiento difuso; no se creó carpeta nueva en Drive porque el paso la crea solo para solicitantes NUEVOS).
- PyMuPDF no está instalado en el `.venv`: la extracción de texto cae a pdftotext/tesseract. Falta probar con un PDF real.
- El ensayo dejó: filas de prueba en las pestañas 2-6 y 8 del Sheet TEST, `cache/intake_watermark.json` nuevo (antes no existía), carpeta vacía "ENSAYO intake 2027 (borrar)" en la raíz de Eva, `cache/noop-bin/openclaw` (silencia Slack en ensayos). Config y registry restaurados (`cmp` idénticos).
- **No activar el cron de producción antes de borrar las aplicaciones demo de Supabase**: se procesarían como reales.

## Bloqueos y riesgos abiertos
1. **Token de Google roto** (`invalid_scope` al refrescar). Sin él falla el paso 1 (carpetas en Drive) y la escritura de resultados. Hipótesis: el código pide un scope que el token no tiene. Lo arregla Iván.
2. **El paso 1 crea carpetas y filas de registro para cualquier envío**, incluso basura o pruebas. Si el pipeline falla después y se reintenta, el solicitante podría quedar marcado como grantee existente (por confirmar en `match_grantee`).
3. Carpetas de prueba `GR-2027-001..004` en la carpeta real: borrarlas antes de abrir (Iván).
4. Contador de IDs: reiniciar (`alter sequence application_seq restart with 1;`) cuando no queden aplicaciones de prueba.

## Preguntas pendientes para Eva (de a una por mensaje)
1. `_normalize_source_headers` completa: ¿renombra algún nombre (por ejemplo `created_at` → `Timestamp`, o pasa a minúsculas)?
2. `load_supabase_key` y el valor de `DEFAULT_SUPABASE_KEY_PATH`.
3. El bloque `c1_is_downloadable` con la descarga y extracción de C1 (para insertar el parche).
4. Cómo lee las casillas: la función del gate de elegibilidad 0.2 y K1/K3/K4. ¿Cuenta opciones separadas por `;`?
5. Qué devuelve `normalize_timestamp("2026-11-11T13:45:30Z")`.
6. Cómo parsea D1 (contacto), E2 (fechas), F2/F3 (valor @ fecha), G3, G4, E10. `NUMERIC_FIELDS` y `REQUIRED_FIELDS`.
7. El bloque `ingest` actual del config (con secretos tapados).
8. Confirmar el nombre `K4_Data_Consent` (llegó partido en el mensaje).
