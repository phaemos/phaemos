-- migration 034: phone numbers confirmed by a code
-- a critical alert is sent by text to the number on an account, so a number is now used only after a six digit code sent to it
-- was typed back. phone_confirmed_at is when that happened. Existing numbers start unconfirmed, so texts stop until each person
-- confirms theirs. The other columns hold a pending code: its keyed hash, the number it was sent to, its expiry and the wrong
-- tries so far. 032 had already been written for a clean run, so this is a new file.
-- every statement is conditional, so a re-run on an up-to-date database takes no lock and a change that has to wait gives
-- up after 5 seconds. It needs the table owner and no superuser right.

SET lock_timeout = '5s';

DO $$
DECLARE
    col text;
BEGIN
    FOREACH col IN ARRAY ARRAY['phone_confirmed_at', 'phone_code_hash', 'phone_code_number', 'phone_code_expires_at', 'phone_code_attempts'] LOOP
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = current_schema() AND table_name = 'users' AND column_name = col
        ) THEN
            EXECUTE format('ALTER TABLE users ADD COLUMN %I %s', col, CASE col
                WHEN 'phone_confirmed_at' THEN 'TIMESTAMP WITH TIME ZONE'
                WHEN 'phone_code_hash' THEN 'VARCHAR(64)'
                WHEN 'phone_code_number' THEN 'VARCHAR(30)'
                WHEN 'phone_code_expires_at' THEN 'TIMESTAMP WITH TIME ZONE'
                ELSE 'INTEGER NOT NULL DEFAULT 0' END);
        END IF;
    END LOOP;
END
$$;
