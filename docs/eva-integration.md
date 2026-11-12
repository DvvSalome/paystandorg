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
- **Parche de documentos:** `supabase/eva_patches/storage_download.py` (+ prueba). Descarga `storage:<ruta>` desde Supabase Storage con la clave de servicio.
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
- Pendiente: 4) parche de documentos (`storage_download.py`).

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
