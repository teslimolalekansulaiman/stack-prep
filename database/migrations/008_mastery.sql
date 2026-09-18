-- What a student knows, and the evidence that made us believe it.
--
-- This follows packages/engine, not the v1.1 data model document -- the two
-- disagree on how a rating is stored, and docs/data-model-divergences.md sets out
-- why the engine wins. Column names match engine.mastery.SkillRating so nothing
-- is translated between the database and the rules.
--
-- The important structural decision: mastery_events is the source of truth and
-- student_skill_mastery is derived from it. You change what a student knows by
-- recording why, never by editing the number directly. packages/engine/version.py
-- already says derived state is rebuilt by replaying events under a known engine
-- version; this makes that literally true rather than a convention.
BEGIN;
SET LOCAL search_path = stackprep, public;

-- Lets the tables below prove they are pointing at a skill, not a topic.
ALTER TABLE curriculum_items ADD CONSTRAINT curriculum_items_id_item_type_key
  UNIQUE (id, item_type);

CREATE TABLE student_skill_mastery (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  student_id uuid NOT NULL REFERENCES student_profiles(id) ON DELETE RESTRICT,
  curriculum_item_id uuid NOT NULL,
  -- Constant, so the composite key can only resolve against an assessable skill.
  item_type text NOT NULL GENERATED ALWAYS AS ('skill') STORED,

  -- engine.mastery.SkillRating, stored exactly as the engine holds it.
  theta double precision NOT NULL DEFAULT 0,
  scored_attempts integer NOT NULL DEFAULT 0 CHECK (scored_attempts >= 0),
  levels_seen smallint[] NOT NULL DEFAULT '{}',

  -- Derived by the engine from the three fields above. Cached here because SQL
  -- cannot call the engine, and the planner has to filter and sort on them.
  -- The thresholds that produce these belong to the engine, not to this schema:
  -- engine_version records which rules were in force.
  band text NOT NULL DEFAULT 'not_assessed' CHECK (band IN
    ('not_assessed', 'weak', 'developing', 'exam_ready', 'strong', 'maintained')),
  mastery_score numeric(5,4) CHECK (mastery_score BETWEEN 0 AND 1),
  confidence text NOT NULL DEFAULT 'low' CHECK (confidence IN ('low', 'medium', 'high')),
  engine_version text NOT NULL,

  last_assessed_at timestamptz,
  -- When they last got one right. Retention decays from here towards the item's
  -- chance level (engine.mastery.retained_mastery).
  last_success_at timestamptz,
  next_review_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),

  UNIQUE (student_id, curriculum_item_id),
  FOREIGN KEY (curriculum_item_id, item_type)
    REFERENCES curriculum_items(id, item_type) ON DELETE RESTRICT,
  -- A rating nobody has evidence for cannot claim a band.
  CHECK (scored_attempts > 0 OR band = 'not_assessed'),
  -- Levels are 1..5 (engine.mastery.LEVEL_DIFFICULTY).
  CHECK (levels_seen <@ ARRAY[1, 2, 3, 4, 5]::smallint[])
);
CREATE INDEX student_skill_mastery_student_idx ON student_skill_mastery(student_id, band);
CREATE INDEX student_skill_mastery_review_idx ON student_skill_mastery(next_review_at)
  WHERE next_review_at IS NOT NULL;

CREATE TABLE mastery_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  -- Filled in by the trigger below; the event may be the first thing that ever
  -- mentions this student and skill.
  mastery_id uuid REFERENCES student_skill_mastery(id) ON DELETE RESTRICT,
  student_id uuid NOT NULL REFERENCES student_profiles(id) ON DELETE RESTRICT,
  curriculum_item_id uuid NOT NULL,
  item_type text NOT NULL GENERATED ALWAYS AS ('skill') STORED,

  previous_band text CHECK (previous_band IS NULL OR previous_band IN
    ('not_assessed', 'weak', 'developing', 'exam_ready', 'strong', 'maintained')),
  new_band text NOT NULL CHECK (new_band IN
    ('not_assessed', 'weak', 'developing', 'exam_ready', 'strong', 'maintained')),
  previous_theta double precision,
  new_theta double precision NOT NULL,
  scored_attempts integer NOT NULL CHECK (scored_attempts >= 0),
  levels_seen smallint[] NOT NULL DEFAULT '{}',
  mastery_score numeric(5,4) CHECK (mastery_score BETWEEN 0 AND 1),
  confidence text NOT NULL CHECK (confidence IN ('low', 'medium', 'high')),

  -- The answer that caused this, where there was one. Rebuilt ratings and
  -- scheduled decay have no single triggering response.
  trigger_response_id uuid REFERENCES student_responses(id) ON DELETE RESTRICT,
  evidence_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  decision_reason text NOT NULL CHECK (btrim(decision_reason) <> ''),
  -- Which rules decided this. Without it the transition cannot be replayed.
  engine_version text NOT NULL CHECK (btrim(engine_version) <> ''),
  decided_at timestamptz NOT NULL DEFAULT now(),

  FOREIGN KEY (curriculum_item_id, item_type)
    REFERENCES curriculum_items(id, item_type) ON DELETE RESTRICT,
  CHECK (jsonb_typeof(evidence_refs) = 'array'),
  CHECK (scored_attempts > 0 OR new_band = 'not_assessed')
);
CREATE INDEX mastery_events_mastery_idx ON mastery_events(mastery_id, decided_at);
CREATE INDEX mastery_events_student_idx ON mastery_events(student_id, decided_at);

-- ------------------------------------------------------------------ rules ---

CREATE OR REPLACE FUNCTION apply_mastery_event() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  current student_skill_mastery%ROWTYPE;
BEGIN
  SELECT * INTO current FROM student_skill_mastery
   WHERE student_id = NEW.student_id AND curriculum_item_id = NEW.curriculum_item_id
   FOR UPDATE;

  IF NOT FOUND THEN
    IF NEW.previous_theta IS NOT NULL OR NEW.previous_band IS NOT NULL THEN
      RAISE EXCEPTION 'first event for this skill cannot claim a previous state';
    END IF;
    INSERT INTO student_skill_mastery(student_id, curriculum_item_id, theta,
      scored_attempts, levels_seen, band, mastery_score, confidence, engine_version,
      last_assessed_at)
      VALUES (NEW.student_id, NEW.curriculum_item_id, NEW.new_theta, NEW.scored_attempts,
        NEW.levels_seen, NEW.new_band, NEW.mastery_score, NEW.confidence,
        NEW.engine_version, NEW.decided_at)
      RETURNING * INTO current;
  ELSE
    -- The event has to agree with the state it claims to be replacing, or the
    -- history stops reconstructing the current value.
    IF NEW.previous_theta IS DISTINCT FROM current.theta
       OR NEW.previous_band IS DISTINCT FROM current.band THEN
      RAISE EXCEPTION
        'event does not follow the current state (has theta %, band %)',
        current.theta, current.band;
    END IF;
    UPDATE student_skill_mastery
       SET theta = NEW.new_theta,
           scored_attempts = NEW.scored_attempts,
           levels_seen = NEW.levels_seen,
           band = NEW.new_band,
           mastery_score = NEW.mastery_score,
           confidence = NEW.confidence,
           engine_version = NEW.engine_version,
           last_assessed_at = NEW.decided_at,
           updated_at = now()
     WHERE id = current.id
     RETURNING * INTO current;
  END IF;

  NEW.mastery_id := current.id;
  RETURN NEW;
END $$;

CREATE TRIGGER mastery_events_apply
  BEFORE INSERT ON mastery_events
  FOR EACH ROW EXECUTE FUNCTION apply_mastery_event();

CREATE OR REPLACE FUNCTION mastery_events_are_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'mastery history is append-only; record a new event instead';
END $$;

CREATE TRIGGER mastery_events_immutable
  BEFORE UPDATE OR DELETE ON mastery_events
  FOR EACH ROW EXECUTE FUNCTION mastery_events_are_append_only();

CREATE OR REPLACE FUNCTION mastery_is_derived() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  -- Depth 1 means somebody wrote to this table directly. Everything legitimate
  -- arrives through apply_mastery_event(), which runs one level deeper.
  IF pg_trigger_depth() = 1 THEN
    RAISE EXCEPTION
      'student_skill_mastery is derived; change it by inserting a mastery_events row';
  END IF;
  RETURN CASE TG_OP WHEN 'DELETE' THEN OLD ELSE NEW END;
END $$;

CREATE TRIGGER student_skill_mastery_derived
  BEFORE INSERT OR UPDATE OR DELETE ON student_skill_mastery
  FOR EACH ROW EXECUTE FUNCTION mastery_is_derived();

COMMIT;
