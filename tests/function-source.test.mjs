// The Edge Function source (supabase/functions/intake/index.ts) must import every shared helper it uses.
// dist/intake-function.ts is built by concatenation, so it works even when an import is missing; the multi-file
// source would not. This test catches that.
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";

const dir = new URL("../supabase/functions/", import.meta.url);
const index = readFileSync(new URL("intake/index.ts", dir), "utf8");
const importLines = index.split("\n").filter((l) => /^import\s/.test(l)).join("\n");
const body = index.split("\n").filter((l) => !/^import\s/.test(l)).join("\n").replace(/\/\/.*$/gm, "");

let checked = 0;
for (const file of readdirSync(new URL("_shared/", dir)).filter((f) => f.endsWith(".js") && f !== "questions.js")) {
  const src = readFileSync(new URL("_shared/" + file, dir), "utf8");
  for (const m of src.matchAll(/^export\s+(?:async\s+)?(?:function|const)\s+([A-Za-z0-9_]+)/gm)) {
    const name = m[1];
    if (new RegExp("\\b" + name + "\\b").test(body)) {
      assert.ok(new RegExp("import\\s*\\{[^}]*\\b" + name + "\\b[^}]*\\}\\s*from\\s*\"\\.\\./_shared/" + file.replace(".", "\\.") + "\"").test(importLines),
        `index.ts uses ${name} from _shared/${file} but does not import it`);
      checked++;
    }
  }
}
assert.ok(checked >= 10, "expected to check at least 10 shared helpers, checked " + checked);
console.log("function source: " + checked + " shared helpers used and imported");
