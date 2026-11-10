// questions.js is shared with the browser and writes to `window.GA27`.
// Deno has no `window`, so give it one before questions.js is evaluated.
globalThis.window = globalThis.window || {};
