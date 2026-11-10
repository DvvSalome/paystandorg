# Supabase setup (project `gkaukpnmpfdpljofnlxy`)

Run these from a machine with the Supabase CLI logged in (`supabase login`). Nothing here needs a key
pasted into chat or into the repo: the function gets `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` from Supabase itself.

## 1. Database and storage
```bash
supabase link --project-ref gkaukpnmpfdpljofnlxy
supabase db push          # applies supabase/migrations/20261110000000_intake.sql
```
(or paste that SQL file into Dashboard → SQL Editor). Creates `applications`, `application_files`,
`rate_events`, the `APP-2027-####` sequence and the private `applications` bucket. RLS is on with no
policies, so the browser can never read or write these tables directly.

## 2. Secrets
```bash
supabase secrets set ALLOWED_ORIGINS=https://YOUR-FORM-DOMAIN   # exact origin(s) of the form page
supabase secrets set IP_SALT=$(openssl rand -hex 16)
# later, when ready:
supabase secrets set TURNSTILE_SECRET=...                        # Cloudflare Turnstile secret key
supabase secrets set RESEND_API_KEY=... EMAIL_FROM="Paystand Foundation <grants@YOUR-DOMAIN>"
```
Until `TURNSTILE_SECRET` is set the captcha check is skipped; until `RESEND_API_KEY` is set no email is sent.

## 3. Deploy the function
```bash
./scripts/sync-questions.sh     # keep server and browser question definitions identical
supabase functions deploy intake --no-verify-jwt
```
Endpoint: `https://gkaukpnmpfdpljofnlxy.supabase.co/functions/v1/intake` (already in `site/assets/config.js`).

## 4. Check
Open the form with `?demo=1`, press Submit. Expected: an application ID appears, a row is in
`applications` with status `complete`, and two files are under Storage → `applications/APP-2027-0001/`.

## Notes
- The publishable key (`sb_publishable_...`) is not used by the form. Never paste the `sb_secret_...`
  / service-role key into chat, the repo or `config.js`.
- Eva's pipeline will read `applications` where `status = 'complete'` and `processed_at is null`
  with the service-role key kept in `/opt/openclaw.env`.
- Not built yet: save-progress codes, Turnstile widget script on the page, purge of old `rate_events`.
