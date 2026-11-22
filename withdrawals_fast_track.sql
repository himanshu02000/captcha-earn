-- ============================================================
-- Captcha Earn India — first-payout fast-track (Nov 22, 2026)
-- Withdrawal ladder: 100 -> 500 -> 1,000 coins
--   1st withdrawal ever: minimum 100 coins (one-time fast-track)
--   2nd withdrawal:      minimum 500 coins
--   3rd and later:       minimum 1,000 coins
-- ============================================================
-- Run this ONCE in the Supabase SQL editor (same as Oct 12).
-- It replaces ONLY the minimum-threshold ladder inside
-- create_withdrawal. Everything else (balance check, multiple
-- of 50, UPI check, deduct + record, returned id) is kept
-- exactly as the current function behaves.
--
-- IMPORTANT — READ BEFORE RUNNING:
-- 1. The app code (bot.py + index.html) MUST already be deployed
--    with the same ladder, or the app text will disagree with
--    this database rule. Deploy the code first, then run this.
-- 2. STEP 0 below prints the CURRENT function. Check it before
--    running STEP 1:
--      - params must be (p_telegram_id, p_coins, p_upi)
--      - it must already enforce min 500 first / 1,000 later
--      - the withdrawals table must have columns
--        (id, telegram_id, coins, upi, status)
--    If ANY of that looks different, DO NOT run STEP 1 — send the
--    STEP 0 output to Pip first so the replacement can be fixed.
-- 3. Counting rule (same as the app's progress check): the ladder
--    counts ALL prior withdrawal rows for the user. A rejected
--    first request therefore moves the next minimum to 500, not 100.
-- ============================================================

-- STEP 0 — verify the current function (read-only, safe to run)
SELECT pg_get_functiondef(oid)
FROM pg_proc
WHERE proname = 'create_withdrawal';

-- STEP 1 — replacement function (run only after STEP 0 checks out)
CREATE OR REPLACE FUNCTION public.create_withdrawal(
    p_telegram_id bigint,
    p_coins integer,
    p_upi text
)
RETURNS bigint
LANGUAGE plpgsql
AS $$
DECLARE
    v_balance numeric;
    v_prior_count integer;
    v_minimum integer;
    v_withdrawal_id bigint;
BEGIN
    -- The user must exist.
    SELECT balance INTO v_balance
    FROM public.users
    WHERE telegram_id = p_telegram_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'User account not found';
    END IF;

    -- Amount must be a positive multiple of 50 coins.
    IF p_coins IS NULL OR p_coins <= 0 THEN
        RAISE EXCEPTION 'Invalid withdrawal amount';
    END IF;

    IF p_coins % 50 <> 0 THEN
        RAISE EXCEPTION 'The amount must be a multiple of 50 coins';
    END IF;

    -- UPI must look like an id (no spaces).
    IF p_upi IS NULL
        OR length(trim(p_upi)) < 3
        OR p_upi ~ '\s'
    THEN
        RAISE EXCEPTION 'Invalid UPI details';
    END IF;

    -- Ladder: how many withdrawals has this user already made?
    SELECT count(*) INTO v_prior_count
    FROM public.withdrawals
    WHERE telegram_id = p_telegram_id;

    IF v_prior_count = 0 THEN
        v_minimum := 100;   -- first payout fast-track
    ELSIF v_prior_count = 1 THEN
        v_minimum := 500;
    ELSE
        v_minimum := 1000;
    END IF;

    IF p_coins < v_minimum THEN
        RAISE EXCEPTION 'Minimum withdrawal is % coins for this withdrawal', v_minimum;
    END IF;

    -- The user must have the balance.
    IF v_balance < p_coins THEN
        RAISE EXCEPTION 'Insufficient balance';
    END IF;

    -- Deduct the coins and record the request as pending.
    UPDATE public.users
    SET balance = balance - p_coins
    WHERE telegram_id = p_telegram_id;

    INSERT INTO public.withdrawals (telegram_id, coins, upi, status)
    VALUES (p_telegram_id, p_coins, p_upi, 'pending')
    RETURNING id INTO v_withdrawal_id;

    RETURN v_withdrawal_id;
END;
$$;

-- STEP 2 — verify the new rule landed (read-only, safe to run)
-- Re-run the STEP 0 query: the definition should now show the
-- 100 / 500 / 1,000 ladder. Then a live check: a user with no
-- prior withdrawals and 100+ coins should be able to request
-- exactly 100 coins, and a request for 50 coins must fail with
-- "Minimum withdrawal is 100 coins".
