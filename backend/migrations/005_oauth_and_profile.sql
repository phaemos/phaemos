-- Add OAuth provider columns so users can sign in with Google or GitHub
-- without needing a password. Also adds phone number for SMS alerts and
-- TOTP fields for two-factor authentication.
ALTER TABLE users ALTER COLUMN password_hash DROP NOT NULL;

ALTER TABLE users ADD COLUMN IF NOT EXISTS oauth_provider VARCHAR(50);
ALTER TABLE users ADD COLUMN IF NOT EXISTS oauth_id      VARCHAR(200);
ALTER TABLE users ADD COLUMN IF NOT EXISTS phone_number  VARCHAR(30);
ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_secret   VARCHAR(64);
ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_enabled  BOOLEAN NOT NULL DEFAULT FALSE;
