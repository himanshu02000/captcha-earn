-- Idle-reminder state for the "you stopped earning" nudge (1/day).
-- Run once in the Supabase SQL editor. Safe to re-run.
CREATE TABLE IF NOT EXISTS idle_reminders (
  user_id BIGINT PRIMARY KEY,          -- Telegram user id
  last_reminded_at TIMESTAMPTZ,        -- last nudge sent (NULL = never)
  streak_count INT NOT NULL DEFAULT 0, -- nudges in current idle streak
  blocked BOOLEAN NOT NULL DEFAULT FALSE -- user blocked the bot: never retry
);
