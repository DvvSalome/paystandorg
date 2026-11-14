# Status — Grant Application 2027 (updated 2026-11-13, evening)

## Done
- **Site**: pixel-identical clone of paystand.org/grantapplication with our form in "Apply Online" (iframe, auto-height). Deployed on Vercel (`paystand-grant-form`, branch `claude/beautiful-goodall-psemmh`, redeployed by hand), still behind Vercel login.
- **Form**: **59 questions** (v3 IDs; A4 removed 2026-11-13 because G2 asks the same amount), conditional logic, validation, file uploads (PDF/JPG/PNG, 10 MB). One section per screen with a step bar that stays visible. Multi-part questions (D1, D3, E1, E2, E10, F2, F3, G3, I2) must be complete, with the same rule in the browser and the server.
- **Save and resume**: the email is asked on the first save and is the same value as D1's email both ways; format blocks on every email field; resume by code `GA27-XXX-XXX-XXX` from any device; draft deleted on submit. Files are not saved with drafts yet (spec below).
- **Backend (Supabase `gkaukpnmpfdpljofnlxy`)**: tables, private Storage bucket, Edge Function `intake` (`/submit`, `/finalize`, `/draft/save`, `/draft/load`), rate limits, honeypot, RLS closed.
- **Eva (installed on her server 2026-11-13, checksums verified)**: pipeline without A4 and without the $10,000 measurement tier (F2, F3, E10 required of everyone); `match_grantee` accent fix included; one watermark per environment (production starts empty on purpose); a run lock (a second run exits with code 75); the watermark no longer advances when the Sheet write fails. Her tests are in git and in CI; `regression_tests.py` was retired (written for the old numbering) and its valid parts moved to `eva/test_funciones_base.py`.

## Pending: Salomé, in this order
The order matters: the online Edge Function still requires A4, so publishing the new form first would reject every submission.
1. **Merge PR #1** into this branch.
2. **Supabase SQL Editor**: run `supabase/migrations/20261113000000_drafts.sql` (drafts table), if not done yet.
3. **Supabase Edge Functions → `intake`**: paste `dist/intake-function.ts` and deploy.
4. **Supabase SQL Editor**: run `supabase/migrations/20261112000000_eva_view.sql` (drop + create `intake_rows`, without A4). Eva's pipeline already expects this version.
5. **Vercel**: redeploy `site/`.
6. Check: save in one window, resume with the code in another; submit one test application.

## Cleanup before Eva's first production run
Production starts with an empty watermark, so anything left in `applications` is processed as real.
- Delete test applications (APP-2027-0002/0003 and any team "TEST%" rows), `delete from rate_events;`, `delete from drafts;`, `alter sequence application_seq restart with 1;` (only if nothing real has been submitted).
- Delete test files in Storage (dashboard; `application_files` rows go by cascade, the files do not), the empty Drive folder "ENSAYO intake 2027 (borrar)", optionally TEST sheet rows.

## Pending: Iván / Eva
- Rotate the Google token.
- Acceptance run with real 2026 applications (a mature NGO, a starting project, a renewal); if stage or traffic light disagree with the team on more than one in three, adjust before opening.
- Create the production cron (`--environment production`, e.g. every 30 min) only AFTER the cleanup above. Exit code 75 means another run was in progress: not an error, do not alert on it.
- Confirm opening date (Nov 18 vs 20; site says Nov 20).
- Give `ilaguilarm` repo access (GitHub → Settings → Collaborators), if confirmed.

## Specs ready for development (Salomé)
- **Email the draft code**: `docs/email-the-code.md`. The form side is done; missing the sending, then `emailCodes: true` in `site/assets/config.js`.
- **Attachments with drafts**: `docs/attachments-in-drafts.md`. `/draft/file`, one file per question (replaced on re-upload), everything deleted **30 days** after the last update by a scheduled job in Supabase (pg_cron), reminder on day 23. This replaces the earlier 60-day purge idea.

## Go public
- Remove `site/assets/demo.js` and its loader; set `ALLOWED_ORIGINS` in Supabase to the final origin; remove `noindex` on the real domain; turn off Vercel Authentication; custom domain (e.g. apply.paystand.org); point the Wix "Apply Online" button to it.
- Turnstile + Resend (confirmation email) are optional and not configured; the form must not promise an email until they are.
- Eva's correction package (AGENTS/skills) and the intake Q&A skill are still unapplied.
