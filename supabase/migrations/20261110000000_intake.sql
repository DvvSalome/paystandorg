-- Grant Application 2027: intake storage. All tables are locked (RLS on, no policies):
-- only the Edge Function (service role) and Eva's pipeline (service role) can touch them.

create sequence if not exists application_seq start 1;

create or replace function next_application_id() returns text
language sql as $$ select 'APP-2027-' || lpad(nextval('application_seq')::text, 4, '0') $$;

create table if not exists applications (
  id              uuid primary key default gen_random_uuid(),
  application_id  text not null unique,
  status          text not null default 'received' check (status in ('received','complete')),
  answers         jsonb not null,
  profile         text,              -- Initial | Established (derived, for convenience)
  route           text,              -- New | Renewal
  legal_name      text,              -- B1
  country         text,              -- B2
  contact_email   text,              -- D1 email, lower-case
  finalize_token_hash text not null,
  ip_hash         text,
  user_agent      text,
  created_at      timestamptz not null default now(),
  finalized_at    timestamptz,
  processed_at    timestamptz        -- set by Eva's pipeline when ingested
);
create index if not exists applications_status_idx on applications (status, created_at);
create index if not exists applications_email_idx on applications (contact_email);

create table if not exists application_files (
  id              uuid primary key default gen_random_uuid(),
  application_id  text not null references applications (application_id) on delete cascade,
  question        text not null check (question in ('C1','C2','I2','J3')),
  storage_path    text not null,
  file_name       text not null,
  mime_type       text,
  size_bytes      bigint,
  created_at      timestamptz not null default now(),
  unique (application_id, question)
);

create table if not exists rate_events (
  id   bigint generated always as identity primary key,
  key  text not null,
  at   timestamptz not null default now()
);
create index if not exists rate_events_key_at_idx on rate_events (key, at);

alter table applications      enable row level security;
alter table application_files enable row level security;
alter table rate_events       enable row level security;

-- Private bucket for uploaded documents.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('applications', 'applications', false, 10485760,
        array['application/pdf','image/jpeg','image/png'])
on conflict (id) do update
  set public = false, file_size_limit = 10485760,
      allowed_mime_types = array['application/pdf','image/jpeg','image/png'];
