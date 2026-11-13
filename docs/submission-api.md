# Submission API (contract used by site/assets/form.js)

Base URL = `GA27_CONFIG.endpoint` (Supabase Edge Function). Empty = preview build, nothing is sent.

## 1. `POST {endpoint}/submit`
Request (JSON):
```json
{
  "answers": { "A1": "...", "E1": "...", "E1__title": "...", "G4__cats": { "...": "..." } },
  "files":   [ { "question": "C1", "name": "registro.pdf", "type": "application/pdf", "size": 123456 } ],
  "meta":    { "lang": "es-CO", "submitted_from": "https://apply.example.org" },
  "captcha": "<Turnstile token>"
}
```
Server must: verify captcha, rate-limit by IP/email, re-validate every required/conditional rule
(never trust the client), check file type (magic bytes) and size <= 10 MB, strip leading `= + - @`
from text before it reaches any Sheet, create the application row, issue one signed upload URL per file.

Response: `{ "application_id": "APP-2027-0001", "token": "<one-time>", "uploads": [ { "question": "C1", "url": "<signed PUT url>" } ] }`

## 2. `PUT <signed url>` per file (direct to private Storage, no base64)

## 3. `POST {endpoint}/finalize`
`{ "application_id": "...", "token": "..." }` — marks the application complete, sends the confirmation
email with the application ID. Errors: `{ "error": "message" }` with a non-2xx status.

## Implementation
`supabase/functions/intake` + `supabase/functions/_shared/validate.js`; schema in `supabase/migrations/`.
Setup steps: `docs/supabase-setup.md`. Client uploads each file as a multipart PUT (the request supabase-js sends).

## Not built yet
Saving progress with a return code (needs a drafts table) and the Turnstile widget on the page.

## Save and resume (drafts)
- `POST /draft/save` `{ code?, state, saved_sections }` → `{ code }`. No `code` = new draft (the server makes `GA27-XXX-XXX-XXX`); with `code` it updates that draft (404 if unknown: the client cannot invent codes). `state` is the snapshot of form controls built by `site/assets/form.js` (max 200 KB). Limits: 60 saves/h and 10 new drafts/day per IP.
- `POST /draft/load` `{ code }` → `{ code, state, saved_sections, updated_at }`. 404 if missing or older than 60 days. Limit: 20 tries/h per IP.
- `POST /finalize` also takes `draft_code`; on success the draft is deleted.
- Files are never saved in a draft (only their names): the applicant attaches them again.
- Table `drafts` (migration `20261113000000_drafts.sql`). Purge: `delete from drafts where updated_at < now() - interval '60 days';`
- Tests: `node tests/drafts.test.mjs`; browser roundtrip `node tests/draft-roundtrip.js` (site served on :8099).
