-- Upgrade databases created before `undecided` was available for pilot support.
BEGIN;

DO $$ BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'stackprep.curriculum_items'::regclass
      AND conname = 'curriculum_items_check1'
  ) THEN
    ALTER TABLE stackprep.curriculum_items DROP CONSTRAINT curriculum_items_check1;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'stackprep.curriculum_items'::regclass
      AND conname = 'curriculum_items_scope_support_check'
  ) THEN
    ALTER TABLE stackprep.curriculum_items
      ADD CONSTRAINT curriculum_items_scope_support_check
      CHECK (syllabus_status NOT IN ('excluded', 'uncertain', 'retired')
             OR pilot_support_status IN ('undecided', 'unsupported'));
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'stackprep.curriculum_items'::regclass
      AND conname = 'curriculum_items_pilot_support_status_check'
      AND pg_get_constraintdef(oid) NOT LIKE '%undecided%'
  ) THEN
    ALTER TABLE stackprep.curriculum_items
      DROP CONSTRAINT curriculum_items_pilot_support_status_check;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'stackprep.curriculum_items'::regclass
      AND conname = 'curriculum_items_pilot_support_status_check'
  ) THEN
    ALTER TABLE stackprep.curriculum_items
      ADD CONSTRAINT curriculum_items_pilot_support_status_check
      CHECK (pilot_support_status IN ('undecided', 'supported', 'planned', 'unsupported'));
  END IF;
END $$;

ALTER TABLE stackprep.curriculum_items
  ALTER COLUMN pilot_support_status SET DEFAULT 'undecided';

COMMIT;
