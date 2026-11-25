-- =====================================================================
-- AquaGrid migration 002  -  NON-DESTRUCTIVE upgrade of 001_initial_schema.sql
-- Safe to run on the existing database: it only ADDS columns, tables,
-- indexes, policies and triggers. No existing table or row is dropped.
-- Run once in Supabase > SQL Editor (after 001 has been applied).
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. readings: mark simulated data explicitly
-- ---------------------------------------------------------------------
alter table readings add column if not exists is_simulated boolean default false;
-- every existing virtual-node row came from simulator.py
update readings set is_simulated = true where node_id like 'SV-%' and is_simulated is distinct from true;

-- ---------------------------------------------------------------------
-- 2. potholes: full DrainX detection record
-- ---------------------------------------------------------------------
alter table potholes add column if not exists detection_id    uuid default gen_random_uuid();
alter table potholes add column if not exists severity        text;          -- LOW | MEDIUM | HIGH (heuristic)
alter table potholes add column if not exists box_area_pct    real;          -- largest box as % of frame
alter table potholes add column if not exists location_source text default 'none';
      -- gps_exif | gps_device | gps_browser | manual | none | legacy_random
alter table potholes add column if not exists source_type     text;          -- image | video | webcam | upload
alter table potholes add column if not exists source_ref      text;          -- file name / storage path
alter table potholes add column if not exists image_url       text;          -- annotated frame (Supabase Storage)
alter table potholes add column if not exists verification    text default 'unverified';
      -- unverified | confirmed | false_positive
alter table potholes add column if not exists model_version   text;
create unique index if not exists potholes_detection_id on potholes (detection_id);

-- Rows written by the first version of pothole_detect.py used RANDOM coordinates
-- around Silk Board. Flag them so they are never shown as real GPS positions.
update potholes set location_source = 'legacy_random'
where lat is not null and (location_source is null or location_source = 'none')
  and severity is null and source_type is null;

-- ---------------------------------------------------------------------
-- 3. alerts: severity, duplicate prevention, delivery status, location
-- ---------------------------------------------------------------------
alter table alerts add column if not exists severity      text default 'info';   -- info | warning | critical
alter table alerts add column if not exists dedupe_key    text;
alter table alerts add column if not exists sent_telegram boolean default false;
alter table alerts add column if not exists lat           double precision;
alter table alerts add column if not exists lng           double precision;
alter table alerts add column if not exists segment       text;
create unique index if not exists alerts_dedupe_key on alerts (dedupe_key) where dedupe_key is not null;

-- ---------------------------------------------------------------------
-- 4. commands: result text
-- ---------------------------------------------------------------------
alter table commands add column if not exists result text;

-- ---------------------------------------------------------------------
-- 5. road_risk: transparency columns + history
-- ---------------------------------------------------------------------
alter table road_risk add column if not exists flood_available boolean default false;
alter table road_risk add column if not exists severity_score  real;
alter table road_risk add column if not exists explanation     text;

create table if not exists road_risk_history (
  id              bigint generated always as identity primary key,
  segment         text,
  risk            real,
  label           text,
  flood_score     real,
  pothole_score   real,
  pothole_count   int,
  flood_available boolean,
  created_at      timestamptz default now()
);
create index if not exists road_risk_history_seg_time on road_risk_history (segment, created_at desc);

-- ---------------------------------------------------------------------
-- 6. Repair priority management
-- ---------------------------------------------------------------------
create table if not exists repair_tickets (
  segment           text primary key,
  name              text,
  lat               double precision,
  lng               double precision,
  priority_score    real,
  priority_rank     int,
  urgency           text,            -- IMMEDIATE | HIGH | MEDIUM | LOW | MONITOR
  reasons           jsonb,           -- list of human-readable reasons
  factors           jsonb,           -- the numbers behind the score
  status            text default 'Reported'
                    check (status in ('Reported','Under Review','Repair Scheduled','In Progress','Completed')),
  status_note       text,
  updated_by        text,
  status_updated_at timestamptz,
  computed_at       timestamptz default now()
);

create table if not exists repair_status_log (
  id          bigint generated always as identity primary key,
  segment     text,
  old_status  text,
  new_status  text,
  note        text,
  changed_by  text,
  created_at  timestamptz default now()
);

create or replace function log_repair_status() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if new.status is distinct from old.status then
    new.status_updated_at := now();
    new.updated_by := coalesce(auth.jwt() ->> 'email', new.updated_by, 'service');
    insert into repair_status_log (segment, old_status, new_status, note, changed_by)
    values (new.segment, old.status, new.status, new.status_note, new.updated_by);
  end if;
  return new;
end $$;

drop trigger if exists repair_status_trigger on repair_tickets;
create trigger repair_status_trigger before update on repair_tickets
for each row execute function log_repair_status();

-- ---------------------------------------------------------------------
-- 7. DrainX upload queue (dashboard -> Python worker)
-- ---------------------------------------------------------------------
create table if not exists detection_jobs (
  id              bigint generated always as identity primary key,
  file_path       text not null,        -- path inside the 'detections' storage bucket
  file_type       text,                 -- image | video
  segment         text,
  lat             double precision,
  lng             double precision,
  location_source text default 'none',
  status          text default 'queued' check (status in ('queued','processing','done','failed')),
  result          jsonb,
  error           text,
  created_by      text,
  created_at      timestamptz default now(),
  processed_at    timestamptz
);

-- ---------------------------------------------------------------------
-- 8. Service heartbeats (System Health page)
-- ---------------------------------------------------------------------
create table if not exists service_status (
  service    text primary key,      -- bridge | simulator | brain | alerts | road_risk | repair_priority | drainx
  status     text,                  -- ok | warning | error | offline
  detail     jsonb,
  last_seen  timestamptz default now()
);

-- ---------------------------------------------------------------------
-- 9. Realtime
-- ---------------------------------------------------------------------
do $$
declare t text;
begin
  foreach t in array array['commands','repair_tickets','detection_jobs','service_status','road_risk_history'] loop
    begin
      execute format('alter publication supabase_realtime add table %I', t);
    exception when duplicate_object then null;
    end;
  end loop;
end $$;

-- ---------------------------------------------------------------------
-- 10. Row Level Security
--   anon (public dashboard)  : read everything public, send control commands
--   authenticated (team)     : upload detections, verify potholes, update repair status
--   service_role (scripts)   : bypasses RLS
-- ---------------------------------------------------------------------
alter table road_risk_history enable row level security;
alter table repair_tickets    enable row level security;
alter table repair_status_log enable row level security;
alter table detection_jobs    enable row level security;
alter table service_status    enable row level security;

do $$ begin
  create policy "public read commands" on commands for select using (true);
exception when duplicate_object then null; end $$;
do $$ begin
  create policy "public read risk history" on road_risk_history for select using (true);
exception when duplicate_object then null; end $$;
do $$ begin
  create policy "public read repairs" on repair_tickets for select using (true);
exception when duplicate_object then null; end $$;
do $$ begin
  create policy "public read repair log" on repair_status_log for select using (true);
exception when duplicate_object then null; end $$;
do $$ begin
  create policy "public read jobs" on detection_jobs for select using (true);
exception when duplicate_object then null; end $$;
do $$ begin
  create policy "public read service status" on service_status for select using (true);
exception when duplicate_object then null; end $$;

do $$ begin
  create policy "team updates repairs" on repair_tickets for update to authenticated using (true) with check (true);
exception when duplicate_object then null; end $$;
do $$ begin
  create policy "team queues detections" on detection_jobs for insert to authenticated with check (true);
exception when duplicate_object then null; end $$;
do $$ begin
  create policy "team verifies potholes" on potholes for update to authenticated using (true) with check (true);
exception when duplicate_object then null; end $$;

-- column-level limits: the team may only change status fields, never scores
revoke update on repair_tickets from authenticated, anon;
grant  update (status, status_note) on repair_tickets to authenticated;
revoke update on potholes from authenticated, anon;
grant  update (verification) on potholes to authenticated;

-- ---------------------------------------------------------------------
-- 11. Storage bucket for uploaded images/videos and annotated frames
-- ---------------------------------------------------------------------
insert into storage.buckets (id, name, public)
values ('detections', 'detections', true)
on conflict (id) do nothing;

do $$ begin
  create policy "public read detections" on storage.objects for select using (bucket_id = 'detections');
exception when duplicate_object then null; end $$;
do $$ begin
  create policy "team uploads detections" on storage.objects for insert to authenticated
    with check (bucket_id = 'detections');
exception when duplicate_object then null; end $$;
