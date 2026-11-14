"""
Google Sheets simulado en memoria, para las pruebas. No es un mock que acepta
todo: cada pestaña tiene un tamaño fijo y escribir fuera falla como en Google
("exceeds grid limits"), que es como falló el primer --apply real.
"""
import re


class GridError(Exception):
    pass


def col_index(col):
    n = 0
    for ch in col:
        n = n * 26 + ord(ch) - 64
    return n - 1


class _Call:
    def __init__(self, fn):
        self.fn = fn

    def execute(self):
        return self.fn()


class FakeSheet:
    def __init__(self, tabs, rows=1000, cols=None):
        self.tabs = {t: [list(r) for r in rows_] for t, rows_ in tabs.items()}
        self.grid = {t: [rows, cols or max([len(r) for r in rows_] + [1])]
                     for t, rows_ in self.tabs.items()}
        self.ids = {t: i for i, t in enumerate(self.tabs)}
        self.validations = {}      # (tab, col) -> options
        self.protected = {}        # id -> {"tab", "cols", "description", "warningOnly"}
        self.ops = []
        self.fail_append = False

    # spreadsheets() and values() are the same object, like the real client chain
    def spreadsheets(self):
        return self

    def values(self):
        return self

    def _tab(self, sheet_id):
        return next(t for t, i in self.ids.items() if i == sheet_id)

    def get(self, spreadsheetId, range=None, fields=None):
        if range is None:
            def meta():
                out = []
                for t, i in self.ids.items():
                    out.append({"properties": {"sheetId": i, "title": t, "gridProperties": {
                        "rowCount": self.grid[t][0], "columnCount": self.grid[t][1]}},
                        "protectedRanges": [{"protectedRangeId": pid, "description": p["description"]}
                                            for pid, p in self.protected.items() if p["tab"] == t]})
                return {"sheets": out}
            return _Call(meta)
        tab = re.match(r"'(.+?)'", range).group(1)
        return _Call(lambda: {"values": [list(r) for r in self.tabs.get(tab, [])]})

    def batchUpdate(self, spreadsheetId, body):
        def run():
            if "requests" not in body:          # values().batchUpdate
                for d in body["data"]:
                    self._write(d["range"], d["values"])
                return {}
            for req in body["requests"]:
                (kind, r), = req.items()
                self.ops.append((kind,))
                if kind == "appendDimension":
                    g = self.grid[self._tab(r["sheetId"])]
                    g[0 if r["dimension"] == "ROWS" else 1] += r["length"]
                elif kind == "addSheet":
                    t = r["properties"]["title"]
                    self.tabs[t], self.grid[t], self.ids[t] = [[]], [1000, 26], len(self.ids)
                elif kind == "setDataValidation":
                    rg = r["range"]
                    self.validations[(self._tab(rg["sheetId"]), rg["startColumnIndex"])] = [
                        v["userEnteredValue"] for v in r["rule"]["condition"]["values"]]
                elif kind == "addProtectedRange":
                    pr = r["protectedRange"]
                    rg = pr["range"]
                    self.protected[f"P{len(self.protected) + len(self.ops)}"] = {
                        "tab": self._tab(rg["sheetId"]),
                        "cols": (rg.get("startColumnIndex"), rg.get("endColumnIndex")),
                        "description": pr["description"], "warningOnly": pr.get("warningOnly")}
                elif kind == "deleteProtectedRange":
                    self.protected.pop(r["protectedRangeId"], None)
            return {}
        return _Call(run)

    def _write(self, rng, values):
        m = re.match(r"'(.+?)'!([A-Z]+)(\d+)(?::[A-Z]+\d*)?$", rng)
        tab, c0, r0 = m.group(1), col_index(m.group(2)), int(m.group(3)) - 1
        g = self.grid[tab]
        if r0 + len(values) > g[0] or c0 + max(len(v) for v in values) > g[1]:
            raise GridError(f"Range ({rng}) exceeds grid limits. Max rows: {g[0]}, max columns: {g[1]}")
        rows = self.tabs.setdefault(tab, [])
        for k, vals in enumerate(values):
            while len(rows) <= r0 + k:
                rows.append([])
            row = rows[r0 + k]
            row.extend([""] * max(0, c0 + len(vals) - len(row)))
            for j, v in enumerate(vals):
                row[c0 + j] = v

    def update(self, spreadsheetId, range, valueInputOption, body):
        def run():
            self._write(range, body["values"])
            self.ops.append(("update", re.match(r"'(.+?)'", range).group(1), range.split("!")[1]))
            return {}
        return _Call(run)

    def clear(self, spreadsheetId, range, body):
        tab = re.match(r"'(.+?)'!1:1", range).group(1)
        def run():
            self.ops.append(("clear", tab))
            self.tabs[tab][0] = []
            return {}
        return _Call(run)

    def append(self, spreadsheetId, range, valueInputOption, body, insertDataOption=None):
        tab = re.match(r"'(.+?)'", range).group(1)
        def run():
            if self.fail_append:
                raise RuntimeError("append failed (simulated)")
            rows = self.tabs.setdefault(tab, [[]])
            rows.extend([list(v) for v in body["values"]])
            self.grid[tab][0] = max(self.grid[tab][0], len(rows))   # append grows the grid
            self.ops.append(("append", tab))
            return {}
        return _Call(run)
