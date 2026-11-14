#!/usr/bin/env python3
"""
Funciones base del pipeline: emparejamiento con el registro, fechas, OFAC,
nombre y dirección contra el documento, y detección de respuestas sin sentido.

Origen
──────
Portado el 2026-11-13 de scripts/regression_tests.py, que vivía solo en el
servidor de Eva, fuera de git. Ese archivo se escribió para la numeración del
5 de noviembre y el scorecard de 7 criterios: contra el pipeline v3 fallaba
14 de 106 verificaciones, y varias protegían comportamiento que se eliminó a
propósito (A4, B9, la dependencia sumando puntos). Hacerlas pasar lo habría
reintroducido. Se retiró.

Lo que sí seguía siendo válido son estos cinco grupos, y ninguna otra suite
los prueba: las demás solo extraen estas funciones como dependencias.

Cambios respecto al original:
- El registro de grantees es FICTICIO. El real vive en el servidor y este
  repositorio es público; los casos reproducen la forma de los reales (un
  nombre contenido en otro, mayúsculas, espacios, mismo país con una palabra
  acentuada en común) sin nombres de organizaciones reales.
- Ningún grupo escribe a disco.
- Se importa el módulo completo con las librerías de Google simuladas, como
  test_import_guard.py, en vez de un import directo que exige tenerlas.

Uso:
  python3 test_funciones_base.py
"""

import importlib
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from test_import_guard import install_google_stubs  # noqa: E402

FAILS = []
PASSED = 0


def check(cond, msg, got=None):
    global PASSED
    if cond:
        PASSED += 1
        print(f"  ✓ {msg}")
    else:
        FAILS.append(msg)
        print(f"  ✗ {msg}" + (f"  (obtuvo: {got!r})" if got is not None else ""))


# Registro ficticio con la misma forma que data/grantee_registry.json.
REGISTRY = [
    {"grantee_id": "GR-2025-004", "legal_name": "Escuela Costera Bitcoin - Los Surfistas", "country": "South Africa"},
    {"grantee_id": "GR-2025-025", "legal_name": "Semillas Digitales", "country": "El Salvador"},
    {"grantee_id": "GR-2026-015", "legal_name": "Fundación Mi Tierra Digital", "country": "Colombia"},
    {"grantee_id": "GR-2026-020", "legal_name": "Asociación Bitcoin Cali", "country": "Colombia"},
    {"grantee_id": "GR-2027-003", "legal_name": "Red Comunitaria Andina", "country": "Peru"},
]


def suite_matching(m):
    print("\n1. Emparejamiento con el registro de grantees")
    mg = m.match_grantee
    gid, _, ren = mg("Semillas Digitales", "El Salvador", REGISTRY)
    check(gid == "GR-2025-025" and ren, "nombre exacto → mismo grantee, renovación", gid)
    gid, _, _ = mg("Escuela Costera Bitcoin", "South Africa", REGISTRY)
    check(gid == "GR-2025-004", "nombre contenido en el registrado → mismo grantee", gid)
    gid, _, _ = mg("semillas digitales", "El Salvador", REGISTRY)
    check(gid == "GR-2025-025", "sin importar mayúsculas", gid)
    gid, _, _ = mg("  Semillas Digitales  ", "El Salvador", REGISTRY)
    check(gid == "GR-2025-025", "espacios al inicio y al final no importan", gid)
    gid, _, _ = mg("Semillas Digitales", "Mexico", REGISTRY)
    check(gid == "GR-2025-025", "mismo nombre con otro país → mismo grantee", gid)
    gid, _, ren = mg("Completely New Org Inc", "Nigeria", REGISTRY)
    check(gid is None and not ren, "organización nueva → sin emparejar, no es renovación", gid)
    gid, _, _ = mg("Bitcoin Zimbabwe Trust", "Zimbabwe", REGISTRY)
    check(gid is None, "comparte solo 'Bitcoin' → no empareja", gid)
    gid, _, _ = mg("", "El Salvador", REGISTRY)
    check(gid is None, "nombre vacío → sin emparejar", gid)
    # El caso del 13-nov: dos organizaciones del mismo país que comparten
    # una palabra acentuada. Antes "Fundación" se partía en fundaci + n y
    # una organización nueva heredaba el GR-id de otra.
    gid, _, _ = mg("Fundación Nueva Esperanza", "Colombia", REGISTRY)
    check(gid is None, "palabra acentuada en común, mismo país → no empareja", gid)

    new_id = m.generate_grantee_id(2027, REGISTRY)
    check(new_id == "GR-2027-004", "ID nuevo sigue al mayor del año", new_id)
    check(m.generate_grantee_id(2028, REGISTRY) == "GR-2028-001",
          "primer ID de un año sin grantees → 001")
    check(m.norm_org_name("Bitcoin Education Inc.") == "bitcoineducation",
          "norm_org_name quita 'Inc.'", m.norm_org_name("Bitcoin Education Inc."))
    check(m.norm_org_name("Bitcoin Project Ltd") == "bitcoinproject",
          "norm_org_name quita 'Ltd'", m.norm_org_name("Bitcoin Project Ltd"))


def suite_dates(m):
    print("\n2. Normalización de fechas")
    nt = lambda s: m.normalize_timestamp(s)[0]  # noqa: E731
    check(nt("2027-01-15T10:00:00Z") == "2027-01-15T10:00:00Z", "ISO 8601 pasa igual")
    check(nt("44567").startswith("2022"), "número de serie de Google Sheets", nt("44567"))
    check("2027-01-15" in nt("1/15/2027 10:00:00"), "formato EE.UU. con hora", nt("1/15/2027 10:00:00"))
    check("2026-11-02" in nt("November 2, 2026 at 10:02 AM"), "formato WordPress",
          nt("November 2, 2026 at 10:02 AM"))
    check("2027-01-15" in nt("2027-01-15"), "solo fecha", nt("2027-01-15"))
    check(nt("") == "", "vacío → vacío")
    out = nt("1/15/2027 10:00:00")
    check("T" in out and out.endswith("Z"), "la salida siempre es ISO 8601 con T y Z", out)


def suite_ofac(m):
    print("\n3. Chequeo OFAC")
    sdn = [("BIN LADEN, Osama", "AFG"), ("AL-QAIDA", ""),
           ("NORTH KOREA GOVERNMENT", "PRK"), ("TERRORIST ORGANIZATION", "")]
    check(not m.check_ofac("Semillas Digitales", sdn)[0], "nombre limpio → sin coincidencia")
    check(m.check_ofac("AL-QAIDA", sdn)[0], "coincidencia exacta")
    check(m.check_ofac("AL-QAIDA NETWORK", sdn)[0], "contiene un nombre de la lista")
    check(not m.check_ofac("AL", sdn)[0], "nombre muy corto → sin falso positivo")
    check(not m.check_ofac("", sdn)[0], "vacío → sin coincidencia")


def suite_documents(m):
    print("\n4. Nombre y dirección contra el documento de registro")
    cn, ca = m.check_name_in_doc, m.check_address_in_doc
    check(cn("This certifies that Semillas Digitales is a registered organization in El Salvador.",
             "Semillas Digitales")[0], "nombre exacto en el documento")
    check(not cn("This certifies that Some Other Org is registered.", "Semillas Digitales")[0],
          "nombre ausente → no coincide")
    check(cn("Registration of Semillas Digitales Foundation El Salvador", "Semillas Digitales")[0],
          "coincidencia parcial por palabras")
    check(not cn("", "Semillas Digitales")[0], "documento vacío → no coincide")
    addr = "123 Main Street, San Salvador, El Salvador"
    check(ca("Registered office: 123 Main Street, San Salvador, El Salvador", addr)[0],
          "dirección exacta en el documento")
    check(ca("Office located at Main Street San Salvador", addr)[0],
          "dirección parcial por palabras")
    check(not ca("Office at 999 Other Road, Mexico City", "123 Main Street, San Salvador")[0],
          "dirección ausente → no coincide")


def suite_nonsense(m):
    print("\n5. Normalización de texto y respuestas sin sentido")
    check(m.normalize_text("  HELLO World  ") == "hello world", "normalize_text: minúsculas y sin bordes")
    check(m.has_repeated_text("the quick brown fox the quick brown fox the quick brown fox"),
          "frase repetida → se detecta")
    check(not m.has_repeated_text("test test test"), "muy pocas palabras → no se marca")
    check(m.has_consecutive_consonants("asdfghjkl"), "letras al azar → se detecta")
    check(not m.has_consecutive_consonants("Hello World Foundation"), "texto normal → no se marca")
    a, b = "Our primary goal is financial inclusion", "  OUR primary goal is financial inclusion "
    check(m.normalize_text(a) == m.normalize_text(b),
          "dos respuestas copiadas normalizan igual")


def main():
    print("=" * 68)
    print("FUNCIONES BASE DEL PIPELINE")
    print("=" * 68)
    install_google_stubs()
    m = importlib.import_module("intake_pipeline")
    for suite in (suite_matching, suite_dates, suite_ofac, suite_documents, suite_nonsense):
        try:
            suite(m)
        except Exception as e:  # una suite que revienta es una falla, no un salto
            FAILS.append(f"{suite.__name__}: {type(e).__name__}: {e}")
            print(f"  ✗ {suite.__name__} se cayó: {type(e).__name__}: {e}")
    print("\n" + "=" * 68)
    print(f"FUNCIONES BASE: {PASSED} ok, {len(FAILS)} fallidos")
    print("=" * 68)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
