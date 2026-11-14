# Paystand Impact Foundation — Grant Application 2027

Context for any Claude session working in this repo. Keep it short and current.

## What this repo is
- `site/index.html` (+ `site/wix/`): a static copy of https://www.paystand.org/grantapplication (pixel-identical at 1440, 768 and 390 px, no Wix JavaScript, no requests to Wix) with our form in a section "Apply Online" (an iframe to `site/form/`, auto-height by `postMessage`). The mobile menu is a small replacement script. Header links still point to the live paystand.org pages. It carries `noindex` until it lives on the real domain.
  - Regenerate (needs network access to paystand.org and the Wix CDNs): `node scripts/clone/capture.js 1440` (also 768 and 390), then `python3 scripts/clone/build_clone.py cap`. Never edit `site/index.html` by hand: re-run the build.
  - Test params: `?noform=1` hides our section (for pixel comparison with the live page), `?demo=1` fills fictitious data.
- `site/form/index.html`: the application form page (59 questions, v3 IDs). Opened standalone it has its own banner; with `?embed=1` it drops the banner and uses the site's look. Questions: `site/assets/questions.js`; engine: `site/assets/form.js`. Fonts are self-hosted in `site/assets/fonts/`.
- `dist/form.html`: the form as one file with fonts inlined (`python3 scripts/build-single.py`). `dist/intake-function.ts`: the Edge Function as one file for the Supabase dashboard (`scripts/build-function-single.py`).
- `supabase/`: schema (`migrations/`), Edge Function `intake` (receives submissions), the view Eva reads (`intake_rows`), the patch for Eva's pipeline C1 download (`eva_patches/`).
- Deployed: Vercel project `paystand-grant-form` (https://paystand-grant-form.vercel.app, still behind Vercel login), serving `site/`. Supabase project `gkaukpnmpfdpljofnlxy`.

## Flow
Form (Vercel) → Edge Function `intake` → Supabase (`applications`, `application_files`, Storage bucket `applications`) → view `intake_rows` → Eva's `intake_pipeline.py` v3 (ingest source = supabase) → results in the intake Google Sheet tabs 2–8 for the committee.

## Rules that matter
- Eva pre-classifies, never decides. The form never mentions scoring.
- Question IDs are v3 (60-entry QUESTION_MAP incl. timestamp; A4 removed 2026-11-13). 17 IDs changed meaning vs the 5-Nov draft: never map by old meaning. Source of truth for column names: `supabase/eva_question_map.json`; regenerate the view with `python3 scripts/gen-eva-view.py`, never edit it by hand.
- Secrets never go in the repo, chat or `config.js`: the service_role key lives only in Supabase and in a chmod-600 key file on Eva's server.
- After editing `site/assets/questions.js`, run `scripts/sync-questions.sh` **and** `python3 scripts/build-function-single.py`: the browser, the Edge Function and `dist/` each hold a copy, and a stale one means the server rejects what the form accepted, with no useful message. `node tests/questions.test.mjs` fails if they drift — it also pins the question count at 59 and keeps the eligibility path open (0.2 must not require all four boxes; K2 carries the explanation instead). CI runs it on every push.
- Eva's server is changed by Iván (approves technical changes). Eva cannot receive files over Telegram; code is pasted as text. Her replies cut off around 8k tokens: ask for one piece per message.

## Before going public
- Remove `site/assets/demo.js` and its loader; set `ALLOWED_ORIGINS` in Supabase to the final origin; remove `noindex` once the page is on the real domain; take Vercel Authentication off.

## Details
- Integration with Eva, decisions and open questions: `docs/eva-integration.md`
- Supabase setup: `docs/supabase-setup.md`. Submission API contract: `docs/submission-api.md`. Brand palette: `docs/brand.md`.
