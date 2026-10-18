-- Daily Surprise table for Captcha Earn India
-- Paste this whole block into Supabase -> SQL Editor -> New query -> Run.
-- You should see "Success. No rows returned."
-- (If it warns about Row Level Security, choose "Run without RLS":
--  only the bot's server ever touches this table.)

-- One claim row per user per day; coins = the 1-5 surprise amount
CREATE TABLE IF NOT EXISTS daily_surprises (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id BIGINT NOT NULL,          -- Telegram user id
  claim_date DATE NOT NULL DEFAULT ((now() AT TIME ZONE 'Asia/Kolkata')::date),
  coins INT NOT NULL,               -- 1..5
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (user_id, claim_date)       -- one surprise per user per day, enforced
);

CREATE INDEX IF NOT EXISTS idx_daily_surprises_user
  ON daily_surprises (user_id);

-- Allow the app's service role to read/write this table
ALTER TABLE daily_surprises ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE tablename = 'daily_surprises' AND policyname = 'service_role_all_daily_surprises'
  ) THEN
    CREATE POLICY "service_role_all_daily_surprises"
      ON daily_surprises FOR ALL TO service_role USING (true) WITH CHECK (true);
  END IF;
END $$;
