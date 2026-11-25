-- =====================================================================
-- DrainX database  -  paste ALL of this into Supabase > SQL Editor > Run
-- =====================================================================

create table if not exists nodes (
  id         text primary key,
  name       text,
  lat        double precision,
  lng        double precision,
  kind       text default 'virtual',          -- 'real' or 'virtual'
  swmm_node  text,                            -- junction in the digital twin (J1..J4) or null
  created_at timestamptz default now()
);

create table if not exists readings (
  id           bigint generated always as identity primary key,
  node_id      text references nodes(id),
  level_pct    real,  pit_pct real,  turbidity real,  tds real,  soil_pct real,
  flow_lpm     real,  litres_total real,
  gate_open    boolean, rain_on boolean, quality_ok boolean, first_flush boolean,
  mode         text,  reason text,  threshold real,
  created_at   timestamptz default now()
);
create index if not exists readings_node_time on readings (node_id, id desc);

create table if not exists commands (
  id         bigint generated always as identity primary key,
  node_id    text not null,                   -- 'SS-01' (real node), 'SIM', 'BRAIN'
  command    text not null,
  status     text default 'pending',
  created_at timestamptz default now(),
  sent_at    timestamptz
);

create table if not exists runs (
  id                 bigint generated always as identity primary key,
  scenario           text,
  rain_total_mm      real,
  flood_m3_baseline  real,
  flood_m3_threshold real,
  flood_m3_optimised real,
  reduction_pct      real,
  captured_m3        real,
  sensor_factor      real,
  details            jsonb,
  created_at         timestamptz default now()
);

create table if not exists alerts (
  id         bigint generated always as identity primary key,
  kind       text,
  message    text,
  node_id    text,
  created_at timestamptz default now()
);

create table if not exists subscribers (
  chat_id    bigint primary key,
  name       text,
  created_at timestamptz default now()
);

create table if not exists potholes (
  id           bigint generated always as identity primary key,
  lat          double precision,
  lng          double precision,
  confidence   real,
  boxes        int,
  road_segment text,
  created_at   timestamptz default now()
);

create table if not exists road_risk (
  segment       text primary key,
  name          text, lat double precision, lng double precision,
  flood_score   real, pothole_count int, pothole_score real,
  risk          real, label text,
  updated_at    timestamptz default now()
);

-- ---------- live updates for the dashboard ----------
alter publication supabase_realtime add table readings, runs, alerts, potholes, road_risk;

-- ---------- security (DEMO setup) ----------
-- Laptop scripts use the service-role key (bypasses these rules).
-- The public dashboard uses the anon key: it may READ data and SEND commands only.
alter table nodes       enable row level security;
alter table readings    enable row level security;
alter table commands    enable row level security;
alter table runs        enable row level security;
alter table alerts      enable row level security;
alter table subscribers enable row level security;   -- no public policy = private
alter table potholes    enable row level security;
alter table road_risk   enable row level security;

create policy "public read nodes"     on nodes     for select using (true);
create policy "public read readings"  on readings  for select using (true);
create policy "public read runs"      on runs      for select using (true);
create policy "public read alerts"    on alerts    for select using (true);
create policy "public read potholes"  on potholes  for select using (true);
create policy "public read road_risk" on road_risk for select using (true);
create policy "dashboard sends commands" on commands for insert with check (true);
