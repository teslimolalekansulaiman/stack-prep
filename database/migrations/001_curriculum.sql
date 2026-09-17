-- StackPrep curriculum foundation (PostgreSQL 14+).
-- Deliberately contains no claim about the contents of an official NECO syllabus.
BEGIN;

CREATE SCHEMA IF NOT EXISTS stackprep;
SET LOCAL search_path = stackprep, public;

CREATE TABLE academic_reviewers (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  display_name text NOT NULL CHECK (btrim(display_name) <> ''),
  external_user_id text UNIQUE,
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE examinations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL CHECK (btrim(name) <> ''),
  short_name text NOT NULL CHECK (btrim(short_name) <> ''),
  exam_body text NOT NULL CHECK (btrim(exam_body) <> ''),
  country_code char(2) NOT NULL,
  description text,
  grading_system jsonb,
  status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'active', 'retired')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (exam_body, short_name, country_code),
  CHECK (grading_system IS NULL OR jsonb_typeof(grading_system) = 'object')
);

CREATE TABLE subjects (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  examination_id uuid NOT NULL REFERENCES examinations(id) ON DELETE RESTRICT,
  code text NOT NULL CHECK (btrim(code) <> ''),
  name text NOT NULL CHECK (btrim(name) <> ''),
  description text,
  status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'active', 'retired')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (examination_id, code),
  UNIQUE (id, examination_id)
);
CREATE INDEX subjects_examination_idx ON subjects(examination_id);

CREATE TABLE source_documents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  examination_id uuid NOT NULL REFERENCES examinations(id) ON DELETE RESTRICT,
  subject_id uuid,
  document_type text NOT NULL CHECK (document_type IN
    ('syllabus', 'paper', 'answer_key', 'marking_scheme', 'examiner_report', 'boundary_statement')),
  title text NOT NULL CHECK (btrim(title) <> ''),
  issuer text,
  publication_date date,
  document_year integer CHECK (document_year BETWEEN 1900 AND 2200),
  paper_code text,
  file_uri text NOT NULL CHECK (btrim(file_uri) <> ''),
  file_sha256 text NOT NULL CHECK (file_sha256 ~ '^[0-9a-f]{64}$'),
  mime_type text NOT NULL CHECK (btrim(mime_type) <> ''),
  page_count integer CHECK (page_count > 0),
  licence_status text NOT NULL DEFAULT 'pending' CHECK (licence_status IN ('pending', 'verified', 'blocked')),
  storage_permission boolean NOT NULL DEFAULT false,
  student_delivery_permission boolean NOT NULL DEFAULT false,
  model_context_permission boolean NOT NULL DEFAULT false,
  processing_status text NOT NULL DEFAULT 'uploaded' CHECK (processing_status IN
    ('uploaded', 'processed', 'failed')),
  review_status text NOT NULL DEFAULT 'pending' CHECK (review_status IN
    ('pending', 'approved', 'rejected', 'withdrawn')),
  uploaded_by uuid REFERENCES academic_reviewers(id) ON DELETE RESTRICT,
  reviewed_by uuid REFERENCES academic_reviewers(id) ON DELETE RESTRICT,
  reviewed_at timestamptz,
  uploaded_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (file_sha256),
  UNIQUE (id, subject_id),
  FOREIGN KEY (subject_id, examination_id) REFERENCES subjects(id, examination_id) ON DELETE RESTRICT,
  CHECK (licence_status = 'verified' OR NOT
    (storage_permission OR student_delivery_permission OR model_context_permission)),
  CHECK (review_status <> 'approved' OR (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL))
);
CREATE INDEX source_documents_subject_idx ON source_documents(subject_id);
CREATE INDEX source_documents_examination_idx ON source_documents(examination_id);

CREATE TABLE syllabus_versions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  subject_id uuid NOT NULL REFERENCES subjects(id) ON DELETE RESTRICT,
  version_label text NOT NULL CHECK (btrim(version_label) <> ''),
  authority_identifier text,
  valid_from date,
  valid_to date,
  source_document_id uuid,
  status text NOT NULL DEFAULT 'draft' CHECK (status IN
    ('draft', 'approved', 'superseded', 'withdrawn')),
  is_current boolean NOT NULL DEFAULT false,
  approved_by uuid REFERENCES academic_reviewers(id) ON DELETE RESTRICT,
  approved_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (subject_id, version_label),
  UNIQUE (id, subject_id),
  FOREIGN KEY (source_document_id, subject_id) REFERENCES source_documents(id, subject_id) ON DELETE RESTRICT,
  CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from),
  CHECK (status <> 'approved' OR (source_document_id IS NOT NULL AND approved_by IS NOT NULL AND approved_at IS NOT NULL)),
  CHECK (NOT is_current OR status = 'approved')
);
CREATE UNIQUE INDEX syllabus_one_current_per_subject_idx ON syllabus_versions(subject_id) WHERE is_current;
CREATE INDEX syllabus_versions_subject_idx ON syllabus_versions(subject_id, status);

CREATE TABLE curriculum_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  syllabus_version_id uuid NOT NULL,
  subject_id uuid NOT NULL,
  parent_id uuid,
  item_type text NOT NULL CHECK (item_type IN ('topic', 'subtopic', 'skill')),
  code text NOT NULL CHECK (btrim(code) <> ''),
  name text NOT NULL CHECK (btrim(name) <> ''),
  learning_objective text,
  examinable_scope text,
  expected_depth text,
  boundary_notes text,
  syllabus_status text NOT NULL DEFAULT 'uncertain' CHECK (syllabus_status IN
    ('explicit', 'implied', 'prerequisite_only', 'excluded', 'uncertain', 'retired')),
  pilot_support_status text NOT NULL DEFAULT 'undecided' CHECK (pilot_support_status IN
    ('undecided', 'supported', 'planned', 'unsupported')),
  display_order integer NOT NULL DEFAULT 0,
  review_status text NOT NULL DEFAULT 'draft' CHECK (review_status IN
    ('draft', 'pending', 'approved', 'rejected', 'withdrawn')),
  approved_by uuid REFERENCES academic_reviewers(id) ON DELETE RESTRICT,
  approved_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (syllabus_version_id, code),
  UNIQUE (id, syllabus_version_id),
  FOREIGN KEY (syllabus_version_id, subject_id) REFERENCES syllabus_versions(id, subject_id) ON DELETE RESTRICT,
  FOREIGN KEY (parent_id, syllabus_version_id) REFERENCES curriculum_items(id, syllabus_version_id) ON DELETE RESTRICT,
  CHECK ((item_type = 'topic' AND parent_id IS NULL) OR (item_type <> 'topic' AND parent_id IS NOT NULL)),
  CHECK (syllabus_status NOT IN ('excluded', 'uncertain', 'retired') OR pilot_support_status IN ('undecided', 'unsupported')),
  CHECK (review_status <> 'approved' OR (approved_by IS NOT NULL AND approved_at IS NOT NULL))
);
CREATE INDEX curriculum_items_parent_idx ON curriculum_items(parent_id);
CREATE INDEX curriculum_items_version_idx ON curriculum_items(syllabus_version_id, item_type, display_order);

-- An item can have several independent sources. Academic boundary decisions are
-- first-class evidence even when no source PDF contains an explicit statement.
CREATE TABLE curriculum_evidence (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  curriculum_item_id uuid NOT NULL REFERENCES curriculum_items(id) ON DELETE RESTRICT,
  source_document_id uuid REFERENCES source_documents(id) ON DELETE RESTRICT,
  evidence_kind text NOT NULL CHECK (evidence_kind IN
    ('inclusion', 'explicit_exclusion', 'prerequisite', 'academic_boundary')),
  source_location text,
  source_excerpt text,
  decision_rationale text,
  decision_evidence_reference text,
  review_status text NOT NULL DEFAULT 'pending' CHECK (review_status IN
    ('pending', 'approved', 'rejected', 'withdrawn')),
  reviewed_by uuid REFERENCES academic_reviewers(id) ON DELETE RESTRICT,
  reviewed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (
    (evidence_kind = 'academic_boundary'
      AND decision_rationale IS NOT NULL AND btrim(decision_rationale) <> ''
      AND decision_evidence_reference IS NOT NULL AND btrim(decision_evidence_reference) <> '')
    OR
    (evidence_kind <> 'academic_boundary' AND source_document_id IS NOT NULL AND source_location IS NOT NULL)
  ),
  CHECK (review_status <> 'approved' OR (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL))
);
CREATE INDEX curriculum_evidence_item_idx ON curriculum_evidence(curriculum_item_id, review_status);
CREATE INDEX curriculum_evidence_document_idx ON curriculum_evidence(source_document_id);

CREATE TABLE curriculum_mastery_levels (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  curriculum_item_id uuid NOT NULL REFERENCES curriculum_items(id) ON DELETE RESTRICT,
  level_number smallint NOT NULL CHECK (level_number > 0),
  name text NOT NULL CHECK (btrim(name) <> ''),
  description text NOT NULL CHECK (btrim(description) <> ''),
  cognitive_demand text,
  entry_criteria jsonb,
  exit_criteria jsonb,
  recommended_question_count integer CHECK (recommended_question_count > 0),
  review_status text NOT NULL DEFAULT 'pending' CHECK (review_status IN
    ('pending', 'approved', 'rejected', 'withdrawn')),
  reviewed_by uuid REFERENCES academic_reviewers(id) ON DELETE RESTRICT,
  reviewed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (curriculum_item_id, level_number),
  UNIQUE (id, curriculum_item_id),
  CHECK (entry_criteria IS NULL OR jsonb_typeof(entry_criteria) = 'object'),
  CHECK (exit_criteria IS NULL OR jsonb_typeof(exit_criteria) = 'object'),
  CHECK (review_status <> 'approved' OR (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL))
);
CREATE INDEX curriculum_mastery_levels_item_idx ON curriculum_mastery_levels(curriculum_item_id);

CREATE TABLE curriculum_prerequisites (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  curriculum_item_id uuid NOT NULL REFERENCES curriculum_items(id) ON DELETE RESTRICT,
  prerequisite_item_id uuid NOT NULL REFERENCES curriculum_items(id) ON DELETE RESTRICT,
  minimum_level_id uuid,
  strength text NOT NULL CHECK (strength IN ('required', 'recommended', 'supporting')),
  reason text NOT NULL CHECK (btrim(reason) <> ''),
  review_status text NOT NULL DEFAULT 'pending' CHECK (review_status IN
    ('pending', 'approved', 'rejected', 'withdrawn')),
  reviewed_by uuid REFERENCES academic_reviewers(id) ON DELETE RESTRICT,
  reviewed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (curriculum_item_id, prerequisite_item_id),
  FOREIGN KEY (minimum_level_id, prerequisite_item_id)
    REFERENCES curriculum_mastery_levels(id, curriculum_item_id) ON DELETE RESTRICT,
  CHECK (curriculum_item_id <> prerequisite_item_id),
  CHECK (review_status <> 'approved' OR (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL))
);
CREATE INDEX curriculum_prerequisites_target_idx ON curriculum_prerequisites(curriculum_item_id, review_status);
CREATE INDEX curriculum_prerequisites_prior_idx ON curriculum_prerequisites(prerequisite_item_id);

CREATE FUNCTION check_syllabus_version() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE d record;
BEGIN
  IF TG_OP = 'UPDATE' AND OLD.status = 'approved' THEN
    IF ROW(NEW.subject_id, NEW.version_label, NEW.authority_identifier,
           NEW.valid_from, NEW.valid_to, NEW.source_document_id)
       IS DISTINCT FROM
       ROW(OLD.subject_id, OLD.version_label, OLD.authority_identifier,
           OLD.valid_from, OLD.valid_to, OLD.source_document_id) THEN
      RAISE EXCEPTION 'approved syllabus content is immutable; create a new version';
    END IF;
    IF NEW.status NOT IN ('approved', 'superseded', 'withdrawn') THEN
      RAISE EXCEPTION 'approved syllabus cannot return to draft';
    END IF;
  END IF;
  IF NEW.status = 'approved' THEN
    SELECT * INTO d FROM source_documents WHERE id = NEW.source_document_id;
    IF d.id IS NULL OR d.document_type <> 'syllabus' OR d.subject_id <> NEW.subject_id
       OR d.review_status <> 'approved' OR d.licence_status <> 'verified'
       OR NOT d.storage_permission THEN
      RAISE EXCEPTION 'approved syllabus requires a reviewed, rights-verified syllabus document for the same subject';
    END IF;
    -- Serialise approvals for this subject before checking date ranges.
    PERFORM 1 FROM subjects WHERE id = NEW.subject_id FOR UPDATE;
    IF EXISTS (
      SELECT 1 FROM syllabus_versions v
      WHERE v.subject_id = NEW.subject_id AND v.id <> NEW.id AND v.status = 'approved'
        AND daterange(v.valid_from, v.valid_to, '[]') &&
            daterange(NEW.valid_from, NEW.valid_to, '[]')
    ) THEN
      RAISE EXCEPTION 'approved syllabus validity periods overlap';
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER syllabus_version_guard BEFORE INSERT OR UPDATE ON syllabus_versions
  FOR EACH ROW EXECUTE FUNCTION check_syllabus_version();

CREATE FUNCTION check_curriculum_item() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE p record;
BEGIN
  IF NEW.parent_id IS NOT NULL THEN
    SELECT * INTO p FROM curriculum_items WHERE id = NEW.parent_id;
    IF p.id IS NULL OR p.syllabus_version_id <> NEW.syllabus_version_id OR
       (NEW.item_type = 'subtopic' AND p.item_type <> 'topic') OR
       (NEW.item_type = 'skill' AND p.item_type <> 'subtopic') THEN
      RAISE EXCEPTION 'item parent must be a topic/subtopic in the same syllabus version';
    END IF;
    IF TG_OP = 'UPDATE' AND EXISTS (
      WITH RECURSIVE ancestors(id, parent_id) AS (
        SELECT id, parent_id FROM curriculum_items WHERE id = NEW.parent_id
        UNION ALL
        SELECT c.id, c.parent_id FROM curriculum_items c JOIN ancestors a ON c.id = a.parent_id
      ) SELECT 1 FROM ancestors WHERE id = NEW.id
    ) THEN
      RAISE EXCEPTION 'curriculum hierarchy cannot contain a cycle';
    END IF;
  END IF;
  IF TG_OP = 'UPDATE' AND OLD.review_status = 'approved' THEN
    IF ROW(NEW.syllabus_version_id, NEW.subject_id, NEW.parent_id, NEW.item_type,
           NEW.code, NEW.name, NEW.learning_objective, NEW.examinable_scope,
           NEW.expected_depth, NEW.boundary_notes, NEW.syllabus_status)
       IS DISTINCT FROM
       ROW(OLD.syllabus_version_id, OLD.subject_id, OLD.parent_id, OLD.item_type,
           OLD.code, OLD.name, OLD.learning_objective, OLD.examinable_scope,
           OLD.expected_depth, OLD.boundary_notes, OLD.syllabus_status) THEN
      RAISE EXCEPTION 'approved curriculum content is immutable; create a new syllabus version';
    END IF;
  END IF;
  IF NEW.review_status = 'approved' AND (TG_OP = 'INSERT' OR OLD.review_status <> 'approved') THEN
    IF NOT EXISTS (SELECT 1 FROM syllabus_versions WHERE id = NEW.syllabus_version_id AND status = 'approved') THEN
      RAISE EXCEPTION 'curriculum approval requires an approved syllabus version';
    END IF;
    IF NEW.parent_id IS NOT NULL AND NOT EXISTS (
      SELECT 1 FROM curriculum_items WHERE id = NEW.parent_id AND review_status = 'approved'
    ) THEN
      RAISE EXCEPTION 'curriculum approval requires an approved parent';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM curriculum_evidence WHERE curriculum_item_id = NEW.id AND review_status = 'approved') THEN
      RAISE EXCEPTION 'curriculum approval requires reviewed evidence';
    END IF;
    IF NEW.syllabus_status = 'excluded' AND NOT EXISTS (
      SELECT 1 FROM curriculum_evidence WHERE curriculum_item_id = NEW.id
        AND review_status = 'approved' AND evidence_kind IN ('explicit_exclusion', 'academic_boundary')
    ) THEN
      RAISE EXCEPTION 'exclusion requires an approved explicit boundary or academic decision';
    END IF;
    IF NEW.syllabus_status = 'prerequisite_only' AND NOT EXISTS (
      SELECT 1 FROM curriculum_evidence WHERE curriculum_item_id = NEW.id
        AND review_status = 'approved' AND evidence_kind IN ('prerequisite', 'academic_boundary')
    ) THEN
      RAISE EXCEPTION 'prerequisite-only item requires reviewed prerequisite evidence';
    END IF;
  END IF;
  NEW.updated_at := now();
  RETURN NEW;
END $$;
CREATE TRIGGER curriculum_item_guard BEFORE INSERT OR UPDATE ON curriculum_items
  FOR EACH ROW EXECUTE FUNCTION check_curriculum_item();

CREATE FUNCTION check_curriculum_evidence() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE item_subject uuid; doc_subject uuid; doc_type text;
BEGIN
  IF TG_OP = 'UPDATE' AND OLD.review_status = 'approved' THEN
    IF ROW(NEW.curriculum_item_id, NEW.source_document_id, NEW.evidence_kind,
           NEW.source_location, NEW.source_excerpt, NEW.decision_rationale,
           NEW.decision_evidence_reference)
       IS DISTINCT FROM
       ROW(OLD.curriculum_item_id, OLD.source_document_id, OLD.evidence_kind,
           OLD.source_location, OLD.source_excerpt, OLD.decision_rationale,
           OLD.decision_evidence_reference) THEN
      RAISE EXCEPTION 'approved evidence is immutable; withdraw and add a new record';
    END IF;
    IF NEW.review_status NOT IN ('approved', 'withdrawn') THEN
      RAISE EXCEPTION 'approved evidence can only be withdrawn';
    END IF;
  END IF;
  SELECT subject_id INTO item_subject FROM curriculum_items WHERE id = NEW.curriculum_item_id;
  IF NEW.source_document_id IS NOT NULL THEN
    SELECT subject_id, document_type INTO doc_subject, doc_type
      FROM source_documents WHERE id = NEW.source_document_id;
    IF doc_subject IS DISTINCT FROM item_subject THEN
      RAISE EXCEPTION 'evidence document must match the curriculum subject';
    END IF;
    IF NEW.evidence_kind = 'inclusion' AND doc_type <> 'syllabus' THEN
      RAISE EXCEPTION 'direct inclusion evidence must come from a syllabus document';
    END IF;
    IF NEW.evidence_kind = 'explicit_exclusion' AND doc_type NOT IN ('syllabus', 'boundary_statement') THEN
      RAISE EXCEPTION 'explicit exclusion needs a syllabus or boundary statement';
    END IF;
    IF NEW.review_status = 'approved' AND NOT EXISTS (
      SELECT 1 FROM source_documents WHERE id = NEW.source_document_id
        AND review_status = 'approved' AND licence_status = 'verified'
        AND storage_permission
    ) THEN
      RAISE EXCEPTION 'approved evidence needs a reviewed, rights-verified source document';
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER curriculum_evidence_guard BEFORE INSERT OR UPDATE ON curriculum_evidence
  FOR EACH ROW EXECUTE FUNCTION check_curriculum_evidence();

CREATE FUNCTION check_mastery_level() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM curriculum_items WHERE id = NEW.curriculum_item_id AND item_type = 'skill') THEN
    RAISE EXCEPTION 'mastery levels belong to skills';
  END IF;
  IF NEW.review_status = 'approved' AND NOT EXISTS (
    SELECT 1 FROM curriculum_items WHERE id = NEW.curriculum_item_id AND review_status = 'approved'
  ) THEN
    RAISE EXCEPTION 'approved mastery level requires an approved skill';
  END IF;
  NEW.updated_at := now();
  RETURN NEW;
END $$;
CREATE TRIGGER mastery_level_guard BEFORE INSERT OR UPDATE ON curriculum_mastery_levels
  FOR EACH ROW EXECUTE FUNCTION check_mastery_level();

CREATE FUNCTION check_prerequisite() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE target_version uuid; prior_version uuid;
BEGIN
  SELECT syllabus_version_id INTO target_version FROM curriculum_items
    WHERE id = NEW.curriculum_item_id AND item_type = 'skill';
  SELECT syllabus_version_id INTO prior_version FROM curriculum_items
    WHERE id = NEW.prerequisite_item_id AND item_type = 'skill';
  IF target_version IS NULL OR prior_version IS NULL OR target_version <> prior_version THEN
    RAISE EXCEPTION 'prerequisites must link skills in one syllabus version';
  END IF;
  IF NEW.review_status = 'approved' THEN
    IF NOT EXISTS (SELECT 1 FROM curriculum_items WHERE id = NEW.curriculum_item_id AND review_status = 'approved')
       OR NOT EXISTS (SELECT 1 FROM curriculum_items WHERE id = NEW.prerequisite_item_id AND review_status = 'approved') THEN
      RAISE EXCEPTION 'approved prerequisite requires two approved skills';
    END IF;
    IF NEW.minimum_level_id IS NOT NULL AND NOT EXISTS (
      SELECT 1 FROM curriculum_mastery_levels WHERE id = NEW.minimum_level_id AND review_status = 'approved'
    ) THEN
      RAISE EXCEPTION 'minimum prerequisite level must be approved';
    END IF;
    IF NEW.strength = 'required' THEN
      -- Lock the version to prevent concurrent approvals from forming a cycle.
      PERFORM 1 FROM syllabus_versions WHERE id = target_version FOR UPDATE;
      IF EXISTS (
        WITH RECURSIVE prior_chain(id) AS (
          SELECT NEW.prerequisite_item_id
          UNION
          SELECT p.prerequisite_item_id FROM curriculum_prerequisites p
          JOIN prior_chain c ON p.curriculum_item_id = c.id
          WHERE p.strength = 'required' AND p.review_status = 'approved' AND p.id <> NEW.id
        ) SELECT 1 FROM prior_chain WHERE id = NEW.curriculum_item_id
      ) THEN
        RAISE EXCEPTION 'required prerequisites cannot form a cycle';
      END IF;
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER prerequisite_guard BEFORE INSERT OR UPDATE ON curriculum_prerequisites
  FOR EACH ROW EXECUTE FUNCTION check_prerequisite();

-- Candidate-facing scope. Source excerpts and internal boundary rationale stay out.
CREATE VIEW published_curriculum_scope AS
SELECT e.id AS examination_id, e.name AS examination_name,
       s.id AS subject_id, s.name AS subject_name,
       v.id AS syllabus_version_id, v.version_label,
       c.id AS curriculum_item_id, c.parent_id, c.item_type,
       c.code, c.name, c.learning_objective, c.examinable_scope,
       c.expected_depth, c.syllabus_status, c.pilot_support_status,
       c.display_order
FROM curriculum_items c
JOIN syllabus_versions v ON v.id = c.syllabus_version_id
JOIN source_documents d ON d.id = v.source_document_id
JOIN subjects s ON s.id = v.subject_id
JOIN examinations e ON e.id = s.examination_id
WHERE v.status = 'approved' AND v.is_current
  AND c.review_status = 'approved'
  AND c.syllabus_status <> 'retired'
  AND d.review_status = 'approved' AND d.licence_status = 'verified'
  AND d.student_delivery_permission
  AND EXISTS (
    SELECT 1 FROM curriculum_evidence ev
    LEFT JOIN source_documents ed ON ed.id = ev.source_document_id
    WHERE ev.curriculum_item_id = c.id AND ev.review_status = 'approved'
      AND (ev.source_document_id IS NULL OR
           (ed.review_status = 'approved' AND ed.licence_status = 'verified'
            AND ed.student_delivery_permission))
  )
  AND s.status = 'active' AND e.status = 'active';

CREATE VIEW teachable_skills AS
SELECT * FROM published_curriculum_scope
WHERE item_type = 'skill' AND pilot_support_status = 'supported'
  AND syllabus_status IN ('explicit', 'implied', 'prerequisite_only');

COMMIT;
