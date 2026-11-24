-- migration 018: retired
-- this file added users.provider_signin_at, the time of a person's last return from their sign-in provider. That
-- time moved onto the session that made the return (migration 022), because a time kept on the user could be used
-- by any other session of the account. The file stays so the numbering has no gap and does nothing. Migration 022
-- drops the column where an earlier run of this file added it.
SELECT 1;
