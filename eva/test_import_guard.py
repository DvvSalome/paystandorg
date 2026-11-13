#!/usr/bin/env python3
"""
Guarda de importación — el hueco que las otras cinco suites no pueden ver.

Por qué existe
──────────────
test_form_contract, test_live_intake, test_score_v3, scoring_verify y
test_crosscheck cargan el pipeline extrayendo funciones por AST. Eso las hace
correr sin las librerías de Google, en cualquier máquina — y por eso mismo
NUNCA ejecutan el módulo completo. Un error de nivel de módulo (un decorador
mal llamado, una constante que referencia algo inexistente, un import
circular) las pasa de largo con 100% en verde.

No es hipotético. El 2026-11-11 el pipeline salió con:

    @with_retry(max_attempts=3)
    def fetch_supabase_rows(...)

pero `with_retry(func)` solo acepta la función. Eso es un TypeError AL
IMPORTAR: el módulo entero no carga, el pipeline no corre. Las cinco suites
daban verde. Lo encontró el equipo de Salomé al desplegarlo, y lo parcharon a
mano en el servidor de Eva el 2026-11-12.

Esta prueba importa el módulo DE VERDAD, con las librerías de Google
sustituidas por dobles. Si el módulo no carga, falla aquí y no en producción.

Uso:
  python3 test_import_guard.py
"""

import sys
import types
from pathlib import Path

HERE = Path(__file__).parent


def _stub(name, attrs=()):
    """Módulo doble: cualquier atributo devuelve otro doble invocable."""
    m = types.ModuleType(name)

    class _Any:
        def __init__(self, *a, **k):
            pass

        def __call__(self, *a, **k):
            return _Any()

        def __getattr__(self, _):
            return _Any()

    for a in attrs:
        setattr(m, a, _Any)
    m.__getattr__ = lambda _n: _Any
    return m


def install_google_stubs():
    """
    Sustituye las librerías de Google. Deliberadamente NO se instala nada
    real: el objetivo es ejecutar el cuerpo del módulo, no hablar con la red.
    """
    mods = {
        "google": _stub("google"),
        "google.oauth2": _stub("google.oauth2"),
        "google.oauth2.credentials": _stub(
            "google.oauth2.credentials", ["Credentials"]),
        "google.auth": _stub("google.auth"),
        "google.auth.transport": _stub("google.auth.transport"),
        "google.auth.transport.requests": _stub(
            "google.auth.transport.requests", ["Request"]),
        "googleapiclient": _stub("googleapiclient"),
        "googleapiclient.discovery": _stub(
            "googleapiclient.discovery", ["build"]),
        "googleapiclient.errors": _stub("googleapiclient.errors"),
        "googleapiclient.http": _stub("googleapiclient.http"),
    }
    # HttpError tiene que ser una excepción real: el pipeline la usa en
    # `except HttpError`, y un doble cualquiera revienta con TypeError ahí.
    class HttpError(Exception):
        def __init__(self, resp=None, content=b"", *a, **k):
            self.resp = resp
            self.content = content
            super().__init__(str(content))

    mods["googleapiclient.errors"].HttpError = HttpError

    for name, mod in mods.items():
        sys.modules.setdefault(name, mod)

    # google_auth.py vive en scripts/ del servidor de Eva, no en este repo:
    # centraliza las credenciales para los nueve scripts. Se simula con la
    # misma superficie pública para que el pipeline importe aquí igual que
    # allá. Si alguien le agrega una función al módulo y el pipeline la usa,
    # esta prueba falla con un ImportError claro en vez de hacerlo en el
    # servidor a media corrida.
    if "google_auth" not in sys.modules:
        ga = types.ModuleType("google_auth")
        ga.FIXED_SCOPES = [
            "https://www.googleapis.com/auth/drive",
            "https://www.googleapis.com/auth/spreadsheets",
        ]
        ga.get_credentials = lambda *a, **k: None
        ga.get_sheets_service = lambda *a, **k: None
        ga.get_drive_service = lambda *a, **k: None
        ga.get_access_token = lambda *a, **k: ""
        sys.modules["google_auth"] = ga


def main():
    print("=" * 68)
    print("GUARDA DE IMPORTACIÓN — ejecuta el módulo completo")
    print("=" * 68)

    install_google_stubs()
    sys.path.insert(0, str(HERE))

    try:
        import importlib
        mod = importlib.import_module("intake_pipeline")
    except Exception as e:
        print(f"\n  ✗ EL MÓDULO NO CARGA: {type(e).__name__}: {e}")
        import traceback
        tb = traceback.extract_tb(sys.exc_info()[2])
        for fr in tb:
            if "intake_pipeline" in (fr.filename or ""):
                print(f"     en intake_pipeline.py línea {fr.lineno}: {fr.line}")
        print("\n  El pipeline no arrancaría en el servidor. No desplegar.")
        return 1

    print("\n  ✓ el módulo importa — todo el código de nivel de módulo corrió")

    # Lo que de verdad importa: que las funciones de entrada existan y sean
    # llamables después de que sus decoradores se aplicaron.
    required = [
        "fetch_supabase_rows", "fetch_source_rows", "step_ingest",
        "step_clean", "step_classify", "step_flag", "step_score",
        "match_grantee", "resolve_app_id", "infer_pillar", "infer_stage",
    ]
    bad = []
    for name in required:
        fn = getattr(mod, name, None)
        if fn is None:
            bad.append(f"{name}: no existe")
        elif not callable(fn):
            bad.append(f"{name}: no es invocable")
    for line in bad:
        print(f"  ✗ {line}")
    if not bad:
        print(f"  ✓ las {len(required)} funciones de entrada existen y son "
              f"invocables")

    # QUESTION_MAP en su tamaño correcto, leído del módulo ya ejecutado.
    qm = getattr(mod, "QUESTION_MAP", {})
    ok_qm = len(qm) == 61
    print(f"  {'✓' if ok_qm else '✗'} QUESTION_MAP: {len(qm)} columnas "
          f"(deben ser 61)")

    print("\n" + "=" * 68)
    failed = bool(bad) or not ok_qm
    print("IMPORTACIÓN: FALLA" if failed else "IMPORTACIÓN: OK")
    print("=" * 68)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
