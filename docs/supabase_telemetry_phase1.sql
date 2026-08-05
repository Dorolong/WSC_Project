-- Telemetry Phase 1 schema.
-- Run this in the Supabase SQL editor before deploying the telemetry upload UI.

create table if not exists public.telemetry_logs (
  id text primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  file_name text not null,
  status text not null check (status in ('queued', 'running', 'done', 'error', 'lost', 'interrupted')),
  frame_count integer not null default 0,
  min_timestamp text,
  max_timestamp text,
  error text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  finished_at timestamptz
);

create table if not exists public.telemetry_frames (
  id bigserial primary key,
  log_id text not null references public.telemetry_logs(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  frame_index integer not null,
  timestamp_text text,
  can_id text not null,
  raw_data_hex text not null,
  seg_one double precision,
  seg_two double precision,
  created_at timestamptz not null default now()
);

create index if not exists telemetry_logs_user_created_idx
  on public.telemetry_logs (user_id, created_at desc);

create index if not exists telemetry_frames_log_can_frame_idx
  on public.telemetry_frames (log_id, can_id, frame_index);

alter table public.telemetry_logs enable row level security;
alter table public.telemetry_frames enable row level security;

grant select, insert, update, delete on public.telemetry_logs to authenticated;
grant select, insert, update, delete on public.telemetry_frames to authenticated;
grant usage, select on sequence public.telemetry_frames_id_seq to authenticated;

drop policy if exists telemetry_logs_select_own on public.telemetry_logs;
create policy telemetry_logs_select_own
  on public.telemetry_logs
  for select
  to authenticated
  using (auth.uid() = user_id);

drop policy if exists telemetry_logs_insert_own on public.telemetry_logs;
create policy telemetry_logs_insert_own
  on public.telemetry_logs
  for insert
  to authenticated
  with check (auth.uid() = user_id);

drop policy if exists telemetry_logs_update_own on public.telemetry_logs;
create policy telemetry_logs_update_own
  on public.telemetry_logs
  for update
  to authenticated
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

drop policy if exists telemetry_logs_delete_own on public.telemetry_logs;
create policy telemetry_logs_delete_own
  on public.telemetry_logs
  for delete
  to authenticated
  using (auth.uid() = user_id);

drop policy if exists telemetry_frames_select_own on public.telemetry_frames;
create policy telemetry_frames_select_own
  on public.telemetry_frames
  for select
  to authenticated
  using (auth.uid() = user_id);

drop policy if exists telemetry_frames_insert_own on public.telemetry_frames;
create policy telemetry_frames_insert_own
  on public.telemetry_frames
  for insert
  to authenticated
  with check (auth.uid() = user_id);

drop policy if exists telemetry_frames_delete_own on public.telemetry_frames;
create policy telemetry_frames_delete_own
  on public.telemetry_frames
  for delete
  to authenticated
  using (auth.uid() = user_id);
