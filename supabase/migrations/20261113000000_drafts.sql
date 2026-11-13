-- Saved progress ("save and come back with a code"). Only the Edge Function (service role) can touch it.
-- A draft holds personal data typed by the applicant: it is deleted when the application is submitted
-- and ignored after 60 days (purge old rows with the statement at the bottom).
create table if not exists drafts (
  code            text primary key check (code ~ '^GA27-[A-Z0-9]{3}-[A-Z0-9]{3}-[A-Z0-9]{3}$'),
  state           jsonb not null,                       -- snapshot of the form controls (see site/assets/form.js)
  saved_sections  text[] not null default '{}',
  email           text,                                 -- from question D1, lower-case, for a future "email me my code"
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);
create index if not exists drafts_updated_idx on drafts (updated_at);
alter table drafts enable row level security;
revoke all on drafts from anon, authenticated;
grant  all on drafts to service_role;

-- Purge (run by hand or schedule with pg_cron):  delete from drafts where updated_at < now() - interval '60 days';
