-- migration 033: one account for one mailbox
-- the part of an address before the @ was compared as typed, so "Jane@example.com" and "jane@example.com" could be two
-- accounts for one mailbox. Addresses are now stored and compared in lower case.
-- rows are lowered one at a time and a row is left alone when lowering it would clash with another account's address
-- (two accounts that already differ only in case need a person's decision, so the migration stops with a message that says what to do).
-- the unique index on lower(email) stops a new clash. Conditional with a lock timeout, safe to run twice.

SET lock_timeout = '5s';

DO $$
DECLARE
    r record;
    clashes text;
BEGIN
    FOR r IN SELECT id, email FROM users WHERE email <> lower(email) LOOP
        IF NOT EXISTS (SELECT 1 FROM users u WHERE lower(u.email) = lower(r.email) AND u.id <> r.id) THEN
            UPDATE users SET email = lower(email) WHERE id = r.id;
        END IF;
    END LOOP;
    IF to_regclass('idx_users_email_lower') IS NULL THEN
        SELECT string_agg(g.ids, '; ') INTO clashes FROM (
            SELECT string_agg(id::text, ', ' ORDER BY id) AS ids FROM users GROUP BY lower(email) HAVING count(*) > 1
        ) g;
        IF clashes IS NOT NULL THEN
            -- the halt is meant: which of two accounts keeps the address is a decision for a person and the whole block
            -- rolls back so nothing is half done. The message says what to do
            RAISE EXCEPTION 'migration 033 stopped: these groups of accounts have addresses that differ only in case (ids in each group: %). Decide which account keeps each address, then rename or delete the others, for example UPDATE users SET email = ''old-name+duplicate@example.invalid'' WHERE id = ''<id of the account to rename>''; or remove the account in the admin page. Then run the migrations again. See "Migration 033 stops on duplicate addresses" in docs/deployment.md', clashes;
        END IF;
        CREATE UNIQUE INDEX idx_users_email_lower ON users (lower(email));
    END IF;
END
$$;
