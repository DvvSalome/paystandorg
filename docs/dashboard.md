# Dashboard for the Paystand team (`site/admin/`)

Read-only page where the team reads every application that arrives: all answers, section by section, with the documents.
Same palette and fonts as the site (`docs/brand.md`). URL: `<site>/admin/` (it carries `noindex`).

## What it shows
- **Navbar** (always visible): Applications (with a badge of how many you have not opened), Overview, Help, a refresh button and your account menu (Export CSV, Sign out).
- **Applications**: tiles (received, total and average requested, Initial / Established, New / Renewal), a "last application" indicator, and the list: organization, project, country, applicant type, stage, amount requested (G2), date, files. A "NEW" badge stays until that application is opened on that browser.
  - Search looks inside ANY answer. Filters: stage, new/renewal, country, applicant type, sort. Active filters show as tags you click to remove.
- **Application detail** (click a row): header with key facts; a section list on the left that highlights the section you are reading (a scrolling strip on phones); one card per section (0, A–K) with every question and answer; tables for milestones (E10), other funders (G3) and budget (G4); documents open through a link valid 5 minutes. Previous / Next move through the list, plus Copy link and Print / PDF.
  - A question that does not apply to that applicant is skipped (and counted); a question with a stored answer is never hidden.
- **Drafts**: applications started and not submitted yet, with what each person has written so far.
  - Tiles: drafts in progress, active in the last 7 days, average progress, already submitted. The Applications page has a "Drafts in progress" tile that opens this tab; the tab shows a badge with the count.
  - List: organization and email, progress bar ("N of 40 required", counting the questions everybody must answer), sections started, last saved, started, status. Search looks inside any answer. By default only "In progress" drafts are listed; "All" also shows the expired ones and the ones whose email already submitted an application.
  - Click a draft to read it like an application, showing only the questions already answered. Files are never stored in a draft: only the file names are shown.
  - A draft is deleted when its owner submits, and is ignored after 60 days without changes (it shows as "Expired").
  - The resume code of a draft is never sent to the dashboard (whoever has it can open and overwrite the draft); the dashboard links drafts by a short hash.
  - Older drafts only kept the value of each control; the dashboard rebuilds their answers with the same rules as the form. Drafts saved from now on also carry the answers as the form built them. The only thing older drafts lack is the signing date in K5 (a read-only field the form fills itself).
- **Overview**: eight charts (applications per day, stage and route, amount requested by country, size of the request, applicant type, main measure F1, target stage E12, payment method G8). Hover or focus a mark for its value; every chart can be viewed as a table; clicking a country or applicant type opens the filtered list. One series = one validated blue; the two-part bars use blue + orange with a legend that carries the counts.
- **Help**: how to read an application, search, labels, export and privacy.
- **Export CSV**: one row per application, one column per question (respects the filters). Cells that start with `= + - @` get a leading `'` so Excel does not run applicant text as a formula.
- New applications show up by themselves (refresh every 90 seconds on the list, with a toast). Everything is written with `textContent`, never as HTML: applicants control this text.

## Access
One personal code per person, kept in the Edge Function secret `ADMIN_CODES`:

    ana:a-long-random-code,luis:another-long-random-code

- Supabase → Edge Functions → Secrets → add `ADMIN_CODES`. Codes under 16 characters are ignored.
- Generate each code with a password manager (20+ random characters). To revoke someone, delete their entry.
- The browser keeps the code only in `sessionStorage` (gone when the tab closes). 10 wrong codes in an hour from one IP lock that IP out for the hour.
- Never put a code in the repo, in `config.js` or in chat.
- The page itself holds no data: without a valid code `/admin/list` answers 401.

## API (Edge Function `intake`)
- `POST /admin/list` (header `x-admin-code`) → `{ viewer, applications: [{ application_id, finalized_at, profile, route, answers, files: [{question, name, size, type}] }] }`. Only `status = 'complete'`, newest first, up to 1000. Storage paths never leave the server.
- `POST /admin/drafts` (header `x-admin-code`) → `{ drafts: [{ id, email, created_at, updated_at, saved_sections, files, answers | fields }] }`, newest first, up to 500. No resume codes.
- `POST /admin/file` `{ application_id, question }` → `{ url }` (signed, 5 minutes).

## Deploy
1. Supabase → Edge Functions → `intake` → paste `dist/intake-function.ts` → Deploy.
2. Add the secret `ADMIN_CODES`.
3. Redeploy `site/` on Vercel. Open `<site>/admin/`.

## Tests
`node tests/admin.test.mjs` (access logic, drafts shape), `node tests/function-source.test.mjs` (the function source imports every shared helper it uses). `node tests/admin-dashboard.js <payload.json> <dir>` (browser: login, list, search, filters, detail, hostile text, CSV, 390 px) and `node tests/admin-drafts.js <payload.json> <snapshot.json> <dir>` (Drafts tab, old and new drafts, an old server without the drafts route), with the site served on :8099.

## Limits and next steps
- The dashboard shows what the applicants answered. Eva's result (score, traffic light, flags) lives in the intake Google Sheet; showing it here needs a read path from Eva's pipeline (not built).
- Above ~1000 applications the list needs paging (the API caps at 1000).
- Access by code is simple and revocable. If the team grows, move to Supabase Auth with an allow-list of emails.
