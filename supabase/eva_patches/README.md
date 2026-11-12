# Parche de documentos para intake_pipeline.py (C1 desde Supabase Storage)

Problema: la vista `intake_rows` entrega C1/C2/J3 como `storage:<ruta>` (por ejemplo
`storage:APP-2027-0002/C1-registro.pdf`). El bloque de C1 (línea ~3021 del pipeline) solo descarga
enlaces `http...` o IDs de Drive; un valor con `/` y `.` cae en "filename only" y deja
`name_mismatch` y `address_mismatch` en PENDING sin descargar nada.

Cambios (probados con `python3 test_pipeline_c1_storage.py`):
1. Pegar `pipeline_c1_storage.py` (la función `download_supabase_doc` y 3 constantes) a nivel de módulo,
   justo antes de la función que contiene el bloque de C1. Usa `os`, `json`, `urllib.request`,
   `urllib.parse` y `load_supabase_key`, que el pipeline ya tiene.
2. En el bloque de C1, reemplazar
   `c1_is_downloadable = c1_val.startswith("http") or (...)` por dos líneas:
   `c1_is_storage = c1_val.startswith("storage:")` y
   `c1_is_downloadable = c1_is_storage or c1_val.startswith("http") or (...)`.
3. Reemplazar `doc_bytes, doc_mime = download_drive_file(drive_api, c1_val)` por
   `if c1_is_storage: doc_bytes, doc_mime = download_supabase_doc(c1_val)` / `else:` la llamada original.

`download_supabase_doc` devuelve `(bytes, mime)` o `(None, None)` si algo falla, igual que se espera de
`download_drive_file`, así que un fallo termina en `doc_text_extraction_failed` (revisión manual) y no
rompe el paso.
