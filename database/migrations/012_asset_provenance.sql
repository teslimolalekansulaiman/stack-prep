-- Where a figure came from, and who described it.
--
-- Every other claim in this database carries its source: curriculum items cite a page and an
-- excerpt, exam sections cite the line that prints their question count, answers and levels
-- record whether a model or a person decided them. A figure has been the exception, and it
-- is about to stop being one: the JAMB Mathematics papers draw their diagrams as vector art,
-- so each one reaches us as a rectangle of a rendered page that some code chose. A reviewer
-- looking at a crop has to be able to ask "chosen from where?" and get an answer.
--
-- alt_text is the other half. It is required before approval because it is what a blind
-- student reads and what the AI tutor reads — which makes it a claim about mathematics. A
-- description assembled from the labels inside a diagram is a reasonable starting point and
-- is not the same thing as a person having looked at the picture, so it records which it is.
BEGIN;
SET LOCAL search_path = stackprep, public;

ALTER TABLE question_assets
  ADD COLUMN source_location text,
  ADD COLUMN alt_text_source text NOT NULL DEFAULT 'unverified'
    CHECK (alt_text_source IN ('unverified', 'model_proposed', 'expert_verified'));

COMMENT ON COLUMN question_assets.source_location IS
  'Where the image came from, e.g. "PDF page 51, crop (330,225)-(580,335)pt". Free text so '
  'a hand-drawn replacement can cite its own origin.';
COMMENT ON COLUMN question_assets.alt_text_source IS
  'unverified: no description yet. model_proposed: assembled or written by a model, pending '
  'a human check. expert_verified: a person looked at the image and confirmed it.';

-- check_question_version() already refuses to approve a question whose asset has no alt text
-- or an unverified licence. This adds the third requirement as its own trigger rather than
-- by rewriting that function: it has been amended twice already (004 and 006 both extended
-- the immutability check), and restating a long body to add one condition is how a guard
-- gets dropped by accident. Two small triggers both fire; neither can delete the other.
CREATE FUNCTION check_question_version_asset_descriptions() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.review_status = 'approved' AND EXISTS (
    SELECT 1 FROM question_assets a
    WHERE a.question_version_id = NEW.id
      AND a.alt_text_source <> 'expert_verified'
  ) THEN
    RAISE EXCEPTION
      'an approved question needs alt text a person has confirmed, not a proposed one';
  END IF;
  RETURN NEW;
END $$;

-- Named to sort after question_version_guard, so the older, broader checks report first.
CREATE TRIGGER question_version_guard_assets
  BEFORE INSERT OR UPDATE ON question_versions
  FOR EACH ROW EXECUTE FUNCTION check_question_version_asset_descriptions();

COMMIT;
