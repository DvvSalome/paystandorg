#!/usr/bin/env python3
"""
Watermark por ambiente y candado de ejecución — 2026-11-13.

Tres fallas que esta prueba fija:

1. Test y producción compartían cache/intake_watermark.json y leen la misma
   tabla de Supabase. Una corrida de prueba movía la marca más allá de
   solicitudes reales, y producción ya no las veía nunca.
2. Dos corridas a la vez (el cron mientras una manual sigue, o dos ticks del
   cron con una corrida lenta) leían la misma marca y escribían filas dobles.
3. El watermark avanzaba aunque la escritura a la hoja fallara: esas
   solicitudes quedaban atrás de la marca y no se procesaban más.

No toca el cache real: todo corre en un directorio temporal.

Uso:
  python3 test_watermark_lock.py
"""

import ast
import importlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from test_import_guard import install_google_stubs  # noqa: E402

FAILS = []


def check(cond, msg):
    print(f"  {'✓' if cond else '✗'} {msg}")
    if not cond:
        FAILS.append(msg)


def load(tmp):
    install_google_stubs()
    mod = importlib.import_module("intake_pipeline")
    mod.CACHE_DIR = tmp
    mod.WATERMARK_LEGACY = tmp / "intake_watermark.json"
    mod.RUN_LOCK_PATH = tmp / "intake_pipeline.lock"
    return mod


def test_watermark(m, tmp):
    print("\n1. Un watermark por ambiente")
    m.save_watermark("test", {"last_timestamp": "2026-11-13T10:00:00", "last_row": 3,
                              "total_processed": 3, "last_run_id": "R1"})
    check(m.load_watermark("test")["last_timestamp"] == "2026-11-13T10:00:00",
          "test guarda y lee su propia marca")
    check(m.load_watermark("production")["last_timestamp"] is None,
          "una corrida de test no mueve la marca de producción")
    check(not list(tmp.glob("*.tmp")), "la escritura no deja archivos .tmp")

    try:
        m.load_watermark(None)
        check(False, "un ambiente vacío debe fallar, no caer a un archivo compartido")
    except ValueError:
        check(True, "un ambiente vacío falla en vez de caer a un archivo compartido")

    # Legacy: solo test hereda el archivo compartido.
    (tmp / "intake_watermark.test.json").unlink()
    (tmp / "intake_watermark.json").write_text(json.dumps(
        {"last_timestamp": "2026-11-12T09:00:00", "last_row": 2,
         "total_processed": 2, "last_run_id": "OLD"}))
    check(m.load_watermark("test")["last_timestamp"] == "2026-11-12T09:00:00",
          "test hereda el watermark compartido anterior")
    check(m.load_watermark("production")["last_timestamp"] is None,
          "producción NO lo hereda: vería todo lo que test ya tocó")


def test_lock(m, tmp):
    print("\n2. Candado de ejecución")
    fh = m.acquire_run_lock(info={"environment": "test"})
    try:
        m.acquire_run_lock()
        check(False, "una segunda corrida debe quedar bloqueada")
    except m.PipelineLocked as held:
        check(True, "una segunda corrida queda bloqueada")
        check('"environment": "test"' in str(held),
              "el mensaje dice quién tiene el candado")
    fh.close()
    fh2 = m.acquire_run_lock()
    check(True, "al cerrar la corrida, el candado se libera")
    fh2.close()

    # Un proceso que muere sin limpiar no deja el candado tomado.
    child = subprocess.Popen([sys.executable, "-c", (
        "import fcntl,sys,time;f=open(sys.argv[1],'a+');"
        "fcntl.flock(f.fileno(),fcntl.LOCK_EX);print('ok',flush=True);time.sleep(60)"),
        str(m.RUN_LOCK_PATH)], stdout=subprocess.PIPE, text=True)
    child.stdout.readline()
    try:
        m.acquire_run_lock()
        check(False, "con otro proceso vivo, el candado debe estar tomado")
    except m.PipelineLocked:
        check(True, "otro proceso con el candado bloquea esta corrida")
    child.send_signal(signal.SIGKILL)
    child.wait()
    fh3 = m.acquire_run_lock()
    check(True, "si ese proceso muere (kill -9), el candado se libera solo")
    fh3.close()

    # El candado se toma antes de correr, en el punto de entrada.
    src = (HERE / "intake_pipeline.py").read_text(encoding="utf-8")
    main_if = [n for n in ast.parse(src).body if isinstance(n, ast.If)
               and "__main__" in ast.unparse(n.test)]
    body = ast.unparse(main_if[-1]) if main_if else ""
    a, r = body.find("acquire_run_lock"), body.find("run_pipeline(args)")
    check(a != -1 and r != -1 and a < r,
          "__main__ toma el candado antes de run_pipeline")
    check("EXIT_LOCKED" in body, "si está tomado sale con código 75, no con error")


def test_write_holds_watermark(m, tmp):
    print("\n3. La marca no avanza si la escritura falla")
    for f in tmp.glob("intake_watermark*"):
        f.unlink()
    apps = [{"timestamp": "2026-11-13T12:00:00", "cleaned": {"app_id": "APP-2027-0101"}}]
    cfg = {"active": {"intake_sheet_id": "x"}, "active_env": "production"}
    m.validate_sheet_schema = lambda *a, **k: []
    m.read_sheet = lambda *a, **k: [["app_id"]]
    m.update_dashboard = lambda *a, **k: None
    m.write_sheet = lambda *a, **k: None

    m.atomic_batch_write = lambda *a, **k: (0, ["batchUpdate: HttpError 503"])
    out = m.step_write(None, apps, [], cfg, "RUN-FAIL", [], "manual", "test")
    check(m.load_watermark("production")["last_timestamp"] is None,
          "con error de escritura la marca se queda donde estaba")
    check("watermark held back" in out["log"]["errors"],
          "el log de la corrida dice que la marca se retuvo")

    m.atomic_batch_write = lambda *a, **k: (1, [])
    m.step_write(None, apps, [], cfg, "RUN-OK", [], "manual", "test")
    check(m.load_watermark("production")["last_timestamp"] == "2026-11-13T12:00:00",
          "con la escritura completa la marca avanza")
    check(m.load_watermark("test")["last_timestamp"] is None,
          "y solo en el ambiente de la corrida")

    m.update_dashboard = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("dash"))
    apps2 = [{"timestamp": "2026-11-13T13:00:00", "cleaned": {"app_id": "APP-2027-0102"}}]
    m.step_write(None, apps2, [], cfg, "RUN-DASH", [], "manual", "test")
    check(m.load_watermark("production")["last_timestamp"] == "2026-11-13T13:00:00",
          "un error solo del Dashboard no retiene la marca: los resultados sí llegaron")


def main():
    print("=" * 68)
    print("WATERMARK POR AMBIENTE Y CANDADO")
    print("=" * 68)
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        m = load(tmp)
        test_watermark(m, tmp)
        test_lock(m, tmp)
        test_write_holds_watermark(m, tmp)
    print("\n" + "=" * 68)
    print(f"WATERMARK Y CANDADO: {'FALLA' if FAILS else 'OK'} "
          f"({len(FAILS)} fallidos)")
    print("=" * 68)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
