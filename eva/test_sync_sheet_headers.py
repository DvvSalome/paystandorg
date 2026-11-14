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


from fake_google import FakeSheet  # noqa: E402


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
    check(left == 3, "reporta las 2 pestañas con faltantes y el Review Log que no existe", left)

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

    print("\n2d. Tablero de revisión")
    check(P.TAB_REVIEW_LOG in sh.tabs and sh.tabs[P.TAB_REVIEW_LOG][0] == P.REVIEW_LOG_COLUMNS,
          "se creó '9. Review Log' con sus columnas")
    hdr = sh.tabs[P.TAB_PACKAGE][0]
    for name, opts in P.REVIEW_DROPDOWNS.items():
        check(sh.validations.get((P.TAB_PACKAGE, hdr.index(name))) == opts,
              f"lista desplegable en {name}")
    prot = [p for p in sh.protected.values() if p["tab"] == P.TAB_PACKAGE]
    protected_cols = {c for p in prot for c in range(*p["cols"])}
    team_cols = {hdr.index(c) for c in P.REVIEW_TRACKED_COLUMNS}
    check(prot and all(p["warningOnly"] for p in prot), "columnas de Eva protegidas solo con aviso")
    check(not (protected_cols & team_cols), "ninguna columna del equipo queda protegida")
    check({hdr.index(c) for c in ("Semaforo", "Eva_Assessment_Link", "Stage_Suggested")} <= protected_cols,
          "las de Eva sí")
    check(any(p["tab"] == P.TAB_REVIEW_LOG for p in sh.protected.values()), "el Review Log también")

    print("\n3. Una segunda corrida deja la hoja igual")
    def state(x):
        return (repr(x.tabs), repr(sorted(x.validations.items())),
                sorted((p["tab"], p["cols"], p["description"]) for p in x.protected.values()))
    snap = state(sh)
    S.sync(sh, "x", apply=True, out=lambda *a: None)
    check(state(sh) == snap, "idempotente: mismos datos, mismas listas, protecciones sin duplicar")

    print("\n" + "=" * 68)
    print(f"SINCRONIZAR ENCABEZADOS: {PASSED} ok, {len(FAILS)} fallidos")
    print("=" * 68)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
