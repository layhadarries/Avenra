-- Apply after existing migrations, in the private avenra schema. No existing contact is opted in.
BEGIN;
ALTER TABLE avenra.contacts ADD COLUMN IF NOT EXISTS sms_opt_in INTEGER NOT NULL DEFAULT 0 CHECK(sms_opt_in IN (0,1));
INSERT INTO avenra.app_metadata(key,value) VALUES('contact_sms_opt_in_v1','applied') ON CONFLICT(key) DO NOTHING;
COMMIT;
