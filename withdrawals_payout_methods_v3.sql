-- ============================================================
-- Captcha Earn India — payout methods (Nov 22, 2026)
-- File: withdrawals_payout_methods_v3.sql
-- Adds UPI / PayPal / USDT payout methods to create_withdrawal.
-- Base: withdrawals_fast_track_v2.sql (v2 is LIVE with the
-- 100/500/1000 UPI ladder — STEP 0 below confirms it).
-- v1 (withdrawals_fast_track.sql) is SUPERSEDED, do not run it.
--
-- WHY DROP + CREATE (not CREATE OR REPLACE):
-- The new function takes two extra parameters (p_payout_method,
-- p_network). Adding parameters via CREATE OR REPLACE would NOT
-- replace the live function — it would create a second, competing
-- copy, and the app's calls would hit the old one. So this file
-- DROPs the old 3-parameter function first, then CREATEs the new
-- 5-parameter one. Run this file ONCE. If STEP 0 already shows the
-- 5-parameter signature, v3 has landed — do NOT run STEP 1 again.
--
-- WHAT CHANGES (only this):
--   * Payout method: UPI (default), PayPal, USDT.
--   * USDT network: BSC (BEP20) or TRC20 (Tron), USDT only.
--   * Minimums: UPI ladder 100/500/1000 by pending/paid count
--     (unchanged); PayPal flat 25,000 coins ($5.00); USDT BSC flat
--     5,000 ($1.00); USDT TRC20 flat 50,000 ($10.00).
--   * Details are validated per method (UPI ID / PayPal email /
--     USDT address shape per network).
--   * payout_method and payout_details are stored as given. There
--     is NO network column in the withdrawals table, so for USDT
--     the network is stored prefixed in payout_details, e.g.
--     'BSC:0x...' or 'TRC20:T...'.
-- EVERYTHING ELSE is unchanged from v2: SECURITY DEFINER,
-- SET search_path TO '', balance check with FOR UPDATE,
-- multiple-of-50 rule, deduct + insert with the real columns
-- (telegram_id, amount_inr, coins_requested, payout_method,
-- payout_details, status), pending/paid counting rule (a rejected
-- withdrawal does not consume a tier), and the
-- 'Minimum withdrawal is % coins' error format.
-- NOTE: after running this, the API may need up to a minute to see
-- the new function (schema cache). If a withdrawal says "function
-- not found" right after, wait a minute and retry.
-- ============================================================
-- HOW TO RUN: paste this whole file into the Supabase SQL editor
-- (New query) and press Run. Do STEP 0 FIRST and check it before
-- running STEP 1. Then verify with STEP 2.
-- ============================================================

-- STEP 0 — verify the current function (read-only, safe to run)
-- It must show: create_withdrawal(p_telegram_id bigint,
-- p_coins bigint, p_upi text), SECURITY DEFINER, and the
-- 100/500/1000 ladder. If it shows a 5-parameter signature
-- instead, v3 already landed — STOP, do not run STEP 1.
-- If ANYTHING else looks different, STOP and send this output
-- to Pip first.
SELECT pg_get_functiondef(oid)
FROM pg_proc
WHERE proname = 'create_withdrawal';

-- STEP 1 — drop the old function, create the new one
-- (run only after STEP 0 checks out)
DROP FUNCTION IF EXISTS public.create_withdrawal(bigint, bigint, text);

CREATE OR REPLACE FUNCTION public.create_withdrawal(
    p_telegram_id bigint,
    p_coins bigint,
    p_payout_details text,
    p_payout_method text DEFAULT 'UPI',
    p_network text DEFAULT NULL
)
RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO ''
AS $function$
    DECLARE
        v_balance NUMERIC;
        v_withdrawal_id BIGINT;
        v_withdrawal_count BIGINT;
        v_minimum BIGINT;
        v_method_raw TEXT;
        v_method TEXT;
        v_network_raw TEXT;
        v_network TEXT;
        v_details TEXT;
        v_stored_details TEXT;
    BEGIN
        -- Normalise the payout method (UPI default).
        v_method_raw := lower(trim(coalesce(p_payout_method, 'UPI')));
        IF v_method_raw = 'upi' THEN
            v_method := 'UPI';
        ELSIF v_method_raw = 'paypal' THEN
            v_method := 'PayPal';
        ELSIF v_method_raw = 'usdt' THEN
            v_method := 'USDT';
        ELSE
            RAISE EXCEPTION 'Invalid payout method';
        END IF;

        -- Network matters only for USDT.
        IF v_method = 'USDT' THEN
            v_network_raw := upper(trim(coalesce(p_network, '')));
            IF v_network_raw IN ('BSC', 'BEP20') THEN
                v_network := 'BSC';
            ELSIF v_network_raw IN ('TRC20', 'TRON') THEN
                v_network := 'TRC20';
            ELSE
                RAISE EXCEPTION 'Invalid network';
            END IF;
        ELSE
            v_network := NULL;
        END IF;

        -- Count previous non-rejected withdrawals.
        -- Rejected withdrawals do not consume the first-withdrawal tier.
        SELECT COUNT(*)
        INTO v_withdrawal_count
        FROM public.withdrawals
        WHERE telegram_id = p_telegram_id
          AND status IN ('pending', 'paid');

        -- Minimums: UPI ladder by count; PayPal / USDT flat.
        IF v_method = 'PayPal' THEN
            v_minimum := 25000;   -- $5.00
        ELSIF v_method = 'USDT' AND v_network = 'TRC20' THEN
            v_minimum := 50000;   -- $10.00
        ELSIF v_method = 'USDT' THEN
            v_minimum := 5000;    -- $1.00 (BSC)
        ELSIF v_withdrawal_count = 0 THEN
            v_minimum := 100;     -- first payout fast-track
        ELSIF v_withdrawal_count = 1 THEN
            v_minimum := 500;
        ELSE
            v_minimum := 1000;
        END IF;

        IF p_coins IS NULL OR p_coins < v_minimum THEN
            RAISE EXCEPTION 'Minimum withdrawal is % coins', v_minimum;
        END IF;

        -- Amount must be a positive multiple of 50 coins.
        IF p_coins IS NULL OR p_coins <= 0 THEN
            RAISE EXCEPTION 'Invalid withdrawal amount';
        END IF;

        IF p_coins % 50 <> 0 THEN
            RAISE EXCEPTION 'Withdrawal amount must be a multiple of 50 coins';
        END IF;

        -- Payout details must match the method (and network).
        v_details := trim(coalesce(p_payout_details, ''));
        IF v_method = 'UPI' THEN
            IF length(v_details) < 3
               OR length(v_details) > 200
               OR v_details ~ '\s' THEN
                RAISE EXCEPTION 'Invalid UPI details';
            END IF;
            v_stored_details := v_details;
        ELSIF v_method = 'PayPal' THEN
            IF length(v_details) > 254
               OR v_details ~ '\s'
               OR v_details !~ '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$' THEN
                RAISE EXCEPTION 'Invalid PayPal email';
            END IF;
            v_stored_details := v_details;
        ELSIF v_network = 'BSC' THEN
            IF v_details !~ '^0x[0-9a-fA-F]{40}$' THEN
                RAISE EXCEPTION 'Invalid USDT address';
            END IF;
            v_stored_details := 'BSC:' || v_details;
        ELSE
            IF v_details !~ '^T[1-9A-HJ-NP-Za-km-z]{33}$' THEN
                RAISE EXCEPTION 'Invalid USDT address';
            END IF;
            v_stored_details := 'TRC20:' || v_details;
        END IF;

        -- The user must exist.
        SELECT u.balance
        INTO v_balance
        FROM public.users AS u
        WHERE u.telegram_id = p_telegram_id
        FOR UPDATE;

        IF NOT FOUND THEN
            RAISE EXCEPTION 'User account not found';
        END IF;

        IF v_balance IS NULL OR v_balance < p_coins THEN
            RAISE EXCEPTION 'Insufficient balance';
        END IF;

        -- Deduct the coins and record the request as pending.
        UPDATE public.users
        SET balance = balance - p_coins
        WHERE telegram_id = p_telegram_id;

        INSERT INTO public.withdrawals (
            telegram_id,
            amount_inr,
            coins_requested,
            payout_method,
            payout_details,
            status
        )
        VALUES (
            p_telegram_id,
            p_coins::NUMERIC / 50,
            p_coins,
            v_method,
            v_stored_details,
            'pending'
        )
        RETURNING id INTO v_withdrawal_id;

        RETURN v_withdrawal_id;
    END;
$function$;

-- STEP 2 — verify the new rule landed (run this after STEP 1)
-- Re-run: SELECT pg_get_functiondef(oid) FROM pg_proc WHERE proname = 'create_withdrawal';
-- The definition should now show the 5-parameter signature and the
-- 25000 / 50000 / 5000 / 100 / 500 / 1000 minimums.
-- Live checks (with a test user who has enough balance):
--   * UPI, no prior withdrawals, 100 coins -> succeeds.
--   * UPI, no prior withdrawals, 50 coins -> fails
--     "Minimum withdrawal is 100 coins".
--   * PayPal, 5,000 coins -> fails "Minimum withdrawal is 25000 coins".
--   * USDT + BSC, 5,000 coins -> succeeds.
--   * USDT + TRC20, 5,000 coins -> fails
--     "Minimum withdrawal is 50000 coins".
