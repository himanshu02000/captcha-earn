-- Lootably offerwall conversions: one row per transactionID so a
-- retried postback can never credit the same survey twice.
-- Run once in the Supabase SQL editor. Safe to re-run.
CREATE TABLE IF NOT EXISTS lootably_conversions (
  transaction_id TEXT PRIMARY KEY,
  user_id BIGINT NOT NULL,
  offer_name TEXT,
  offer_id TEXT,
  revenue_usd NUMERIC,
  reward_coins NUMERIC NOT NULL,
  status TEXT NOT NULL DEFAULT '1',
  credited BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
