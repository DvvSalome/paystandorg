import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

// Dates are shown as MM/DD/YYYY and stored as YYYY-MM-DD.
//
// Stored as ISO because Eva's pipeline tries %d/%m/%Y before %m/%d/%Y, so a
// stored "03/04/2027" would silently become 3 April. Shown in US format by
// our own field because <input type="date"> takes its format from the
// browser's language, not from the page.
//
// Run: node tests/dates.test.mjs

const form = readFileSync("site/assets/form.js", "utf8");
const a = form.indexOf("function isoToUS"), b = form.indexOf("var CAL_SVG");
assert.ok(a > 0 && b > a, "form.js must define isoToUS, usToISO and maskUS before CAL_SVG");
const { isoToUS, usToISO, maskUS } = new Function(form.slice(a, b) + "; return { isoToUS, usToISO, maskUS };")();

assert.equal(isoToUS("2027-03-15"), "03/15/2027");
assert.equal(usToISO("03/15/2027"), "2027-03-15");
assert.equal(usToISO("12/31/2027"), "2027-12-31");
assert.equal(usToISO("02/29/2028"), "2028-02-29", "leap year");
for (const bad of ["02/29/2027", "02/30/2028", "04/31/2027", "13/01/2027", "00/10/2027", "03/15/27", "3/15/2027", "15/03/2027", ""])
  assert.equal(usToISO(bad), "", `must reject ${JSON.stringify(bad)}`);

// typing digits builds the shape; pasting ISO or restoring an old draft converts
assert.equal(maskUS("03152027"), "03/15/2027");
assert.equal(maskUS("0315"), "03/15");
assert.equal(maskUS("03/15/2027x9"), "03/15/2027");
assert.equal(maskUS("2027-03-15"), "03/15/2027", "ISO from a draft saved before the change");

// no native date input is shown to the applicant: the only one is the hidden picker
const natives = form.match(/type = "date"/g) || [];
assert.equal(natives.length, 1, "only the hidden calendar picker may be a native date input");
assert.match(form, /pick\.type = "date"; pick\.className = "usdate-pick"/);

console.log("dates: all checks passed");
