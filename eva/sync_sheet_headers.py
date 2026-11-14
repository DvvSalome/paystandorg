#!/usr/bin/env python3
"""
Pone en la fila 1 de cada pestaña de resultados las columnas que el pipeline
escribe (TAB_COLUMNS en intake_pipeline.py).

Por qué existe: el 2026-11-13 la hoja de producción todavía tenía los
encabezados v2. Como el pipeline escribe por nombre de columna, de lo que
calcula se habrían guardado 13 de 51 valores en Cleaned, 12 de 40 en
Classified y 8 de 22 en Scorecard. step_write ahora se niega a escribir si
faltan columnas; este script las pone.

Sin --apply solo muestra la diferencia; no cambia nada.
Con --apply:
  - pestaña SIN filas de datos: la fila 1 queda exactamente como TAB_COLUMNS
    (se quitan los encabezados viejos, que no tienen datos debajo);
  - pestaña CON filas de datos: solo agrega al final las columnas que faltan.
    Nunca borra, mueve ni renombra un encabezado que tenga datos debajo.
Después vuelve a leer la fila 1 y termina con código 1 si todavía falta algo.

Uso (desde scripts/, como antforce):
  python3 sync_sheet_headers.py --environment test
  python3 sync_sheet_headers.py --environment test --apply
"""
import argparse
import sys

import intake_pipeline as P


def col_letter(n):
    r = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        r = chr(65 + rem) + r
    return r


def tab_state(api, sheet_id, tab):
    values = P.read_sheet(api, sheet_id, tab) or []
    headers = [str(h).strip() for h in (values[0] if values else [])]
    data_rows = sum(1 for row in values[1:] if any(str(c).strip() for c in row))
    return headers, data_rows


def diff(headers, wanted):
    have = {h.lower() for h in headers if h}
    want = {w.lower() for w in wanted}
    missing = [w for w in wanted if w.lower() not in have]
    extra = [h for h in headers if h and h.lower() not in want]
    return missing, extra


def sync(api, sheet_id, apply=False, out=print):
    """Returns the number of tabs still missing columns after the run."""
    still_missing = 0
    for tab, wanted in P.TAB_COLUMNS.items():
        headers, data_rows = tab_state(api, sheet_id, tab)
        missing, extra = diff(headers, wanted)
        out(f"\n[{tab}] {len(headers)} encabezados, {data_rows} filas de datos")
        if not missing:
            out("  ✓ tiene todas las columnas" + (f" (más {len(extra)} sin uso)" if extra else ""))
            continue
        out(f"  faltan {len(missing)}: {', '.join(missing)}")
        if extra:
            out(f"  sin uso {len(extra)}: {', '.join(extra)}")
        if not apply:
            still_missing += 1
            continue
        # A tab is created with a fixed number of columns; writing past it
        # fails ("exceeds grid limits"). Grow it first.
        P.ensure_grid(api, sheet_id, tab, 1, max(len(wanted), len(headers) + len(missing)))
        values = api.spreadsheets().values()
        if data_rows == 0:
            values.clear(spreadsheetId=sheet_id, range=f"'{tab}'!1:1", body={}).execute()
            values.update(spreadsheetId=sheet_id, range=f"'{tab}'!A1",
                          valueInputOption="RAW", body={"values": [list(wanted)]}).execute()
            out(f"  → fila 1 reemplazada por las {len(wanted)} columnas del pipeline")
        else:
            start = col_letter(len(headers) + 1)
            values.update(spreadsheetId=sheet_id, range=f"'{tab}'!{start}1",
                          valueInputOption="RAW", body={"values": [missing]}).execute()
            out(f"  → {len(missing)} columnas agregadas al final (desde {start}); "
                f"no se tocó lo que tiene datos")
        headers, _ = tab_state(api, sheet_id, tab)
        missing, _ = diff(headers, wanted)
        if missing:
            still_missing += 1
            out(f"  ✗ todavía faltan: {', '.join(missing)}")
        else:
            out("  ✓ verificado")
    return still_missing


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--environment", choices=["test", "production"], required=True)
    ap.add_argument("--apply", action="store_true", help="cambiar la hoja (sin esto solo muestra)")
    args = ap.parse_args()
    cfg = P.load_config()
    sheet_id = cfg[args.environment]["intake_sheet_id"]
    print(f"Hoja de {args.environment}: {sheet_id}  ({'APLICAR' if args.apply else 'solo mostrar'})")
    left = sync(P.get_sheets_service(), sheet_id, apply=args.apply)
    print("\n" + ("Todas las pestañas tienen sus columnas." if not left else
                  f"{left} pestaña(s) con columnas faltantes."
                  + ("" if args.apply else " Corre con --apply para corregirlas.")))
    return 1 if left else 0


if __name__ == "__main__":
    sys.exit(main())
