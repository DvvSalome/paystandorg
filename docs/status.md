# Status — Grant Application 2027 (updated 2026-11-13)

## Done
- **Site**: pixel-identical clone of paystand.org/grantapplication with our form in "Apply Online" (iframe, auto-height). Deployed on Vercel (`paystand-grant-form`, branch `claude/beautiful-goodall-psemmh`, redeployed by hand), still behind Vercel login.
- **Form**: 60 questions (v3 IDs), conditional logic, validation, file uploads (PDF/JPG/PNG, 10 MB).
- **Save and resume**: global "Save and get my code", "Save section X" with per-section status, resume by code `GA27-XXX-XXX-XXX` from any device, draft deleted on submit, files not saved (re-attach). Tested: roundtrip identical on 60 fields.
- **Backend (Supabase `gkaukpnmpfdpljofnlxy`)**: tables, private Storage bucket, Edge Function `intake` (`/submit`, `/finalize`, `/draft/save`, `/draft/load`), rate limits, honeypot, RLS closed.
- **Eva**: view `intake_rows` (63 columns, generated from her QUESTION_MAP), Storage download patch (C1), `with_retry` fix, rehearsal passed (score 85, GREEN).

## Pending: needs a person
1. **Supabase SQL Editor**: run `supabase/migrations/20261113000000_drafts.sql` (drafts table).
2. **Supabase Edge Functions → `intake`**: paste `dist/intake-function.ts` and deploy (adds draft routes). Until 1 and 2 are done, Save shows an error; normal submit still works.
3. After 1–2: save in one window, resume with the code in another.
4. **Iván/Eva**: approve and apply `match_grantee` accent fix (`supabase/eva_patches/match_grantee_accents.py`); create the production cron (`--environment production`, e.g. every 30 min) only AFTER the cleanup below; later: separate watermark per environment and a Slack notify toggle.
5. Confirm opening date (Nov 18 vs 20; site says Nov 20).
6. Give `ilaguilarm` repo access (GitHub → Settings → Collaborators), if confirmed.

## Cleanup before launch
- Delete test applications (APP-2027-0002/0003 and any team "TEST%" rows), `delete from rate_events;`, `delete from drafts;`, `alter sequence application_seq restart with 1;`.
- Delete test files in Storage (dashboard), the empty Drive folder "ENSAYO intake 2027 (borrar)", optionally TEST sheet rows.

## Go public
- Remove `site/assets/demo.js` and its loader; set `ALLOWED_ORIGINS` in Supabase to the final origin; remove `noindex` on the real domain; turn off Vercel Authentication; custom domain (e.g. apply.paystand.org); point the Wix "Apply Online" button to it.
- Turnstile + Resend (confirmation email) are optional and not configured; the form must not promise an email until they are.
- Eva's correction package (AGENTS/skills) and the intake Q&A skill are still unapplied.
- Purge old drafts: `delete from drafts where updated_at < now() - interval '60 days';`
