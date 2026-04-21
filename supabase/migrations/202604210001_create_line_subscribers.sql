create table if not exists public.line_subscribers (
  user_id text primary key,
  source_type text null,
  display_name text null,
  subscribed boolean not null default true,
  created_at timestamp without time zone not null default current_timestamp,
  updated_at timestamp without time zone not null default current_timestamp
);

create index if not exists line_subscribers_subscribed_idx
  on public.line_subscribers (subscribed);
