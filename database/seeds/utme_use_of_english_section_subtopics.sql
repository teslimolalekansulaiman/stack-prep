-- Point each printed section of the UTME Use of English paper at the subtopic it examines.
--
-- The sections were loaded pointing at their topic, because that is all topic weights needed.
-- Subtopic weights need more, and page 3 mostly supplies it: eleven of the thirteen sections
-- name something the syllabus also names, word for word or near enough to be checkable.
--
-- Two are left at topic level on purpose, because the document does not divide them:
--
--   * "Comprehension passage - 5 questions" sets questions on the passage as a whole, on
--     words in context, and on logical reasoning - the syllabus's A.1, A.2 and A.3 - without
--     saying how many of each.
--   * "Basic grammar - 10 questions" is one label over five subtopics: clause patterns, word
--     classes, mood and tense, mechanics and idiomatic usage.
--
-- Those two stay attributed to their topic, and subtopic_exam_weight shares their questions
-- out across the subtopics no section names. That is a rule, not a reading of the document,
-- and it is written down in the view rather than here.
--
-- The one mapping that is an inference rather than a match is A-SUMMARY -> Synthesis of
-- ideas. The section is "Summary passage"; the syllabus's own NOTE on page 2 defines
-- synthesis of ideas as "the art of combining distinct or separate pieces of information to
-- form a complete whole as summary". The definition is printed, so the link is citable, and
-- the citation below says exactly where it comes from.
--
-- These rows are already approved, and this changes what they claim. It does not withdraw
-- them: the finer attribution is the same printed fact read more closely, not a new one. But
-- reviewed_by and reviewed_at are refreshed, so the record says who made the finer claim and
-- when, rather than leaving it under the earlier approval.
--
-- Safe to re-run.
BEGIN;
SET LOCAL search_path = stackprep, public;

WITH reviewer AS (
  SELECT id FROM academic_reviewers WHERE display_name = 'Teslim Sulaiman' AND active LIMIT 1
),
subject AS (
  SELECT s.id FROM subjects s
  JOIN examinations e ON e.id = s.examination_id
  WHERE s.code = 'ENG' AND e.short_name = 'UTME'
  LIMIT 1
),
version AS (
  SELECT v.id FROM syllabus_versions v, subject
  WHERE v.subject_id = subject.id AND v.version_label = 'utme-2027'
  LIMIT 1
),
mapping (section_code, item_code, citation) AS (
  VALUES
    ('A-SUMMARY',     'ENG.A.5',
     'PDF page 3, Section A: "Summary passage - 5 questions"; read against the page 2 NOTE '
     'defining synthesis of ideas as combining information "to form a complete whole as summary".'),
    ('A-CLOZE',       'ENG.A.6',
     'PDF page 3, Section A: "Cloze passage - 10 questions". The syllabus names the cloze test '
     'in the passage-setting note on page 2.'),
    ('A-READING-TEXT', 'ENG.A.4',
     'PDF page 3, Section A: "Reading text - 5 questions", and the content list entry '
     '"Approved Reading Text".'),
    ('B-SYNONYMS',    'ENG.B.1',
     'PDF page 3, Section B: "Synonyms - 5 questions", and the content list entry "Synonyms".'),
    ('B-ANTONYMS',    'ENG.B.2',
     'PDF page 3, Section B: "Antonyms - 5 questions", and the content list entry "Antonyms".'),
    ('B-SENTENCES',   'ENG.B.3',
     'PDF page 3, Section B: "Sentence interpretation - 5 questions", and the printed '
     'objective "Interpret information conveyed in sentences" under clause and sentence patterns.'),
    ('C-VOWELS',      'ENG.C.1',
     'PDF page 3, Section C: "Vowels - 2 questions", and the content list entry "Vowels '
     '(monophthongs, diphthongs and triphthongs)".'),
    ('C-CONSONANTS',  'ENG.C.2',
     'PDF page 3, Section C: "Consonants - 2 questions", and the content list entry '
     '"Consonants (including clusters)".'),
    ('C-RHYMES',      'ENG.C.3',
     'PDF page 3, Section C: "Rhymes - 2 questions", and the content list entry "Rhymes '
     '(including homophones)".'),
    ('C-WORD-STRESS', 'ENG.C.4',
     'PDF page 3, Section C: "Word stress - 2 questions", and the content list entry "Word '
     'stress (monosyllabic and polysyllabic)".'),
    ('C-EMPHATIC',    'ENG.C.5',
     'PDF page 3, Section C: "Emphatic stress - 2 questions", and the content list entry '
     '"Emphatic stress (in connected speech)".')
)
UPDATE exam_paper_sections s
   SET curriculum_item_id = ci.id,
       syllabus_version_id = version.id,
       source_location = mapping.citation,
       reviewed_by = reviewer.id,
       reviewed_at = now()
FROM mapping, version, reviewer, subject, curriculum_items ci
WHERE s.subject_id = subject.id
  AND s.section_code = mapping.section_code
  AND ci.syllabus_version_id = version.id
  AND ci.code = mapping.item_code
  AND s.curriculum_item_id IS DISTINCT FROM ci.id;

COMMIT;
