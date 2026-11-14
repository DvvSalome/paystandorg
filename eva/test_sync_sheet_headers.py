#!/usr/bin/env python3
"""
sync_sheet_headers.py contra una hoja simulada: muestra sin cambiar, reemplaza
la fila 1 solo en pestañas vacías, y en pestañas con datos solo agrega al
final. Nunca toca una celda con datos.

Uso:
  python3 test_sync_sheet_headers.py
"""
import importlib
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from test_import_guard import install_google_stubs  # noqa: E402

FAILS, PASSED = [], 0


def check(cond, msg, got=None):
    global PASSED
    if cond:
        PASSED += 1
        print(f"  ✓ {msg}")
    else:
        FAILS.append(msg)
        print(f"  ✗ {msg}" + (f"\n      obtuvo: {got!r}" if got is not None else ""))


def idx(col):
    n = 0
    for ch in col:
        n = n * 26 + ord(ch) - 64
    return n - 1


class GridError(Exception):
    pass


class FakeSheet:
    """
    Una hoja como lista de filas por pestaña; registra cada escritura. Cada
    pestaña tiene un tamaño fijo, y escribir fuera falla como en Google
    ("exceeds grid limits"), que es como falló el primer --apply real.
    """
    def __init__(self, tabs, rows=1000, cols=None):
        self.tabs = {t: [list(r) for r in rows_] for t, rows_ in tabs.items()}
        self.grid = {t: [rows, cols or max(len(r) for r in rows_)] for t, rows_ in self.tabs.items()}
        self.ops = []

    def spreadsheets(self):
        return self

    def values(self):
        return self

    def _call(self, fn):
        class C:
            def execute(_):
                return fn()
        return C()

    def get(self, spreadsheetId, range=None, fields=None):
        if range is None:   # spreadsheets().get: tamaño de cada pestaña
            return self._call(lambda: {"sheets": [
                {"properties": {"sheetId": i, "title": t,
                                "gridProperties": {"rowCount": g[0], "columnCount": g[1]}}}
                for i, (t, g) in enumerate(self.grid.items())]})
        tab = re.match(r"'(.+)'", range).group(1)
        return self._call(lambda: {"values": [list(r) for r in self.tabs.get(tab, [])]})

    def batchUpdate(self, spreadsheetId, body):
        def run():
            titles = list(self.grid)
            for req in body.get("requests", []):
                d = req["appendDimension"]
                g = self.grid[titles[d["sheetId"]]]
                g[0 if d["dimension"] == "ROWS" else 1] += d["length"]
            self.ops.append(("grow",))
            return {}
        return self._call(run)

    def clear(self, spreadsheetId, range, body):
        tab = re.match(r"'(.+)'!1:1", range).group(1)
        def run():
            self.ops.append(("clear", tab))
            self.tabs[tab][0] = []
            return {}
        return self._call(run)

    def update(self, spreadsheetId, range, valueInputOption, body):
        m = re.match(r"'(.+)'!([A-Z]+)1$", range)
        tab, start = m.group(1), idx(m.group(2))
        def run():
            if start + len(body["values"][0]) > self.grid[tab][1]:
                raise GridError(f"Range ('{tab}'!{m.group(2)}1) exceeds grid limits. "
                                f"Max columns: {self.grid[tab][1]}")
            self.ops.append(("update", tab, m.group(2)))
            rows = self.tabs.setdefault(tab, [[]])
            row = rows[0]
            row.extend([""] * max(0, start + len(body["values"][0]) - len(row)))
            for i, v in enumerate(body["values"][0]):
                row[start + i] = v
            return {}
        return self._call(run)


def main():
    print("=" * 68)
    print("SINCRONIZAR ENCABEZADOS")
    print("=" * 68)
    install_google_stubs()
    P = importlib.import_module("intake_pipeline")
    S = importlib.import_module("sync_sheet_headers")
    C = P.TAB_COLUMNS

    v2_score = ["App_ID", "Timestamp", "Grantee_Name", "Score_Mission_Alignment", "Total_Score"]
    data_row = ["APP-2026-0001", "2026-03-01", "Org con datos", "7", "70"]
    base = {
        P.TAB_CLEAN: [["App_ID", "Timestamp", "A4_2026_Amount_Num"]],   # v2, vacía
        P.TAB_CLASSIFY: [list(C[P.TAB_CLASSIFY])],                       # ya correcta
        P.TAB_FLAGS: [list(C[P.TAB_FLAGS])],
        P.TAB_SCORE: [v2_score, data_row],                               # v2 CON datos
        P.TAB_PACKAGE: [list(C[P.TAB_PACKAGE])],
    }

    print("\n1. Sin --apply no cambia nada")
    sh = FakeSheet(base)
    left = S.sync(sh, "x", apply=False, out=lambda *a: None)
    check(sh.ops == [], "ninguna escritura", sh.ops)
    check(left == 2, "reporta las 2 pestañas con faltantes", left)

    print("\n2. Con --apply")
    sh = FakeSheet(base)
    left = S.sync(sh, "x", apply=True, out=lambda *a: None)
    check(left == 0, "termina sin faltantes", left)
    check(sh.tabs[P.TAB_CLEAN][0] == C[P.TAB_CLEAN],
          "pestaña vacía: la fila 1 queda exactamente como TAB_COLUMNS (sin el A4 viejo)")
    score = sh.tabs[P.TAB_SCORE]
    check(score[0][:len(v2_score)] == v2_score,
          "pestaña con datos: los encabezados existentes no se mueven ni se borran")
    check(score[1] == data_row, "y la fila de datos queda intacta")
    check(set(C[P.TAB_SCORE]) <= set(score[0]), "las columnas que faltaban quedan al final")
    check(("clear", P.TAB_SCORE) not in sh.ops, "nunca se borra la fila 1 de una pestaña con datos")
    check(not [o for o in sh.ops if len(o) > 1 and o[1] in (P.TAB_CLASSIFY, P.TAB_FLAGS, P.TAB_PACKAGE)],
          "las pestañas ya correctas no se tocan", sh.ops)

    print("\n2b. La hoja tenía el tamaño justo de los encabezados viejos")
    sh = FakeSheet(base)
    check(sh.grid[P.TAB_CLEAN][1] == 3, "la pestaña Cleaned simulada tiene solo 3 columnas")
    left = S.sync(sh, "x", apply=True, out=lambda *a: None)
    check(left == 0, "el script la amplía y termina sin faltantes (antes: exceeds grid limits)", left)
    check(sh.grid[P.TAB_CLEAN][1] >= len(C[P.TAB_CLEAN]), "la pestaña quedó con columnas suficientes")

    print("\n2c. El pipeline amplía las filas antes de escribir")
    log = FakeSheet({P.TAB_LOG: [["Log_ID"]]}, rows=1000, cols=19)
    P.ensure_grid(log, "x", P.TAB_LOG, 1001, 19)
    check(log.grid[P.TAB_LOG][0] >= 1001,
          "la fila 1001 del Process Log existe (con el cron, a las ~3 semanas)", log.grid[P.TAB_LOG])
    before = len(log.ops)
    P.ensure_grid(log, "x", P.TAB_LOG, 1001, 19)
    check(len(log.ops) == before, "si ya cabe, no amplía otra vez")

    import inspect
    for fn in ("write_sheet", "atomic_batch_write"):
        src = inspect.getsource(getattr(P, fn).__wrapped__ if hasattr(getattr(P, fn), "__wrapped__")
                                else getattr(P, fn))
        check("ensure_grid(" in src, f"{fn} amplía la hoja antes de escribir")

    print("\n3. Una segunda corrida no cambia nada")
    ops = len(sh.ops)
    S.sync(sh, "x", apply=True, out=lambda *a: None)
    check(len(sh.ops) == ops, "idempotente")

    print("\n" + "=" * 68)
    print(f"SINCRONIZAR ENCABEZADOS: {PASSED} ok, {len(FAILS)} fallidos")
    print("=" * 68)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
