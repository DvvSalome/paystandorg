# Paystand Impact Foundation — Grant Application 2027

Context for any Claude session working in this repo. Keep it short and current.

## What this repo is
- `site/`: the public application form (60 questions, v3 IDs). `site/assets/questions.js` holds the questions; `form.js` is the engine. `?demo=1` fills fictitious data (remove `demo.js` before going public).
- `dist/form.html`: the same form as one file (`python3 scripts/build-single.py`). `dist/intake-function.ts`: the Edge Function as one file for the Supabase dashboard (`scripts/build-function-single.py`).
- `supabase/`: schema (`migrations/`), Edge Function `intake` (receives submissions), the view Eva reads (`intake_rows`), patches for Eva's pipeline (`eva_patches/`).
- Deployed: Vercel project `paystand-grant-form` (https://paystand-grant-form.vercel.app, still behind Vercel login). Supabase project `gkaukpnmpfdpljofnlxy`.

## Flow
Form (Vercel) → Edge Function `intake` → Supabase (`applications`, `application_files`, Storage bucket `applications`) → view `intake_rows` → Eva's `intake_pipeline.py` v3 (ingest source = supabase) → results in the intake Google Sheet tabs 2–8 for the committee.

## Rules that matter
- Eva pre-classifies, never decides. The form never mentions scoring.
- Question IDs are v3 (61-entry QUESTION_MAP incl. timestamp). 17 IDs changed meaning vs the 5-Nov draft: never map by old meaning. Source of truth for column names: `supabase/eva_question_map.json`; regenerate the view with `python3 scripts/gen-eva-view.py`, never edit it by hand.
- Secrets never go in the repo, chat or `config.js`: the service_role key lives only in Supabase and in a chmod-600 key file on Eva's server.
- After editing `site/assets/questions.js`, run `scripts/sync-questions.sh` so the Edge Function validates the same questions.
- Eva's server is changed by Iván (approves technical changes). Eva cannot receive files over Telegram; code is pasted as text. Her replies cut off around 8k tokens: ask for one piece per message.

## Details
- Integration with Eva, decisions and open questions: `docs/eva-integration.md`
- Supabase setup: `docs/supabase-setup.md`. Submission API contract: `docs/submission-api.md`. Brand palette: `docs/brand.md`.
