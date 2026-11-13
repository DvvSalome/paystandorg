# Pipeline de intake v3 y sus pruebas

El pipeline que corre en el servidor de Eva, puesto bajo control de versiones.

## Por qué está aquí

Hasta hoy existían **dos copias divergentes** de `intake_pipeline.py`: la del
servidor de Eva —con los parches aplicados a mano desde
`supabase/eva_patches/`— y la de la máquina de Iván, donde se hizo la
migración a v3 y el scorecard de 4 criterios. Cada despliegue desde cualquiera
de los dos lados borraba el trabajo del otro.

Eso ya estuvo a punto de costar caro. La copia de Iván traía
`@with_retry(max_attempts=3)` cuando `with_retry` solo acepta la función: un
`TypeError` **al importar**, es decir el pipeline entero sin arrancar. El
equipo lo encontró al desplegar y lo parchó en el servidor el 2026-11-12; la
copia de Iván seguía con el bug y lo habría reintroducido en el siguiente
despliegue, junto con borrar el parche de C1 y el de tildes.

Con el archivo en git hay un solo origen, los parches dejan de ser
instrucciones en un README, y un cambio se revisa antes de llegar a
producción.

## Qué contiene

| Archivo | Qué es |
|---|---|
| `intake_pipeline.py` | El pipeline v3 completo, con los tres parches del equipo ya integrados |
| `test_import_guard.py` | Importa el módulo de verdad con las librerías de Google simuladas |
| `test_form_contract.py` | Pool A — 11 casos controlados con resultados calculados a mano |
| `test_live_intake.py` | Pool B — B1 sobre prosa real de grantees, B2 contra Supabase |
| `test_score_v3.py` | Invariantes del scorecard de 4 criterios |
| `scoring_verify.py` | Reimplementación independiente del scorecard + 6 fixtures a mano |
| `test_crosscheck.py` | Confronta pipeline, reimplementación y cifras a mano |
| `data/scorecard_config.json` | Pesos, umbrales y reglas del scorecard |

Correr todo:

```bash
cd eva
python3 test_import_guard.py && python3 test_form_contract.py && \
python3 test_score_v3.py && python3 scoring_verify.py --fixtures && \
python3 test_crosscheck.py
```

Las cinco pasan sin red y sin las librerías de Google.

## Lo que deliberadamente NO está aquí

Este repo es **público**. No se versiona nada de esto:

| Archivo | Por qué |
|---|---|
| `data/grantee_registry.json` | 54 correos y 53 registros con nombre y contacto de organizaciones reales |
| `data/seguimiento_2027.json` | 50 correos reales |
| `data/intake_sheets_config.json` | IDs de carpetas de Drive y de las hojas de TEST y PRODUCCIÓN |
| Llaves de cualquier tipo | La `service_role` vive solo en Supabase y en un archivo chmod 600 en el servidor |

`test_live_intake.py --b1` necesita el padrón y sin él se detiene con un
mensaje explicando de dónde copiarlo. No se sustituye por datos sintéticos a
propósito: el punto de B1 es medir la clasificación contra **prosa real**, y
con texto inventado mediría la redacción de quien escribió la prueba.

Los fixtures de `test_score_v3.py` y `scoring_verify.py` usaban nombres,
personas de contacto y correos de grantees reales. Se reemplazaron por
organizaciones ficticias conservando la *forma* de los datos, que es lo único
que la prueba necesita.

## Los tres parches del equipo, ya integrados

Venían de `supabase/eva_patches/` y estaban aplicados a mano en el servidor.
Ahora viven en el archivo:

1. **`@with_retry` sin argumentos** — el decorador no acepta parámetros. Con
   `max_attempts=3` el módulo no importa.
2. **Descarga de C1 desde Supabase Storage** — la vista `intake_rows` entrega
   C1/C2/J3 como `storage:<ruta>`; ese valor trae `/` y `.`, así que caía en la
   rama de "solo nombre de archivo" y dejaba `name_mismatch` y
   `address_mismatch` en PENDING sin descargar nada.
3. **Tildes en `match_grantee`** — `re.findall(r'[a-z0-9]+', ...)` partía
   "Fundación" en `fundaci` + `n`. Dos organizaciones del mismo país con una
   palabra acentuada compartían esos dos tokens y una organización **nueva** se
   fusionaba con un grantee existente: reusaba su GR-id, no se creaba su
   carpeta y heredaba datos ajenos.

## El hueco que las pruebas tenían

Cinco de las seis suites cargan el pipeline extrayendo funciones por AST, para
correr sin las librerías de Google. Eso las hace portátiles y **ciegas a todo
error de nivel de módulo**. Con el bug del decorador puesto a propósito:

```
IMPORTACIÓN:  ✗ TypeError en línea 1002
CONTRATO:     79 ok, 0 fallidos      ← verde
FIXTURES:     6/6 passed             ← verde
```

`test_import_guard.py` cierra ese hueco: importa el módulo completo con las
librerías de Google sustituidas por dobles. **Córrelo primero**; si falla, el
pipeline no arrancaría en el servidor y no hay que desplegar.
