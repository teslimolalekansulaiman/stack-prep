#!/usr/bin/env python3
"""Load a transcribed past paper into the question bank as drafts.

    uv run python database/load_questions.py \
        --transcription docs/questions/waec/english/transcription_2013.yaml \
        --pdf "docs/questions/waec/english/WASSCE_2013_ENGLISH_LANGUAGE_2_Objective_test.pdf" \
        --dry-run

Everything it writes is a draft: questions are unreviewed, their answers are recorded as
`model_proposed` (or as `published_key` when the paper prints its own answer key and the
transcription says so), and their skill mappings as `proposed_by = 'model'`. The database will
not let any of it reach a student until a person verifies the answer and approves both the
question and its classification.

Re-running is safe. Identifiers are derived from the PDF's SHA-256 and the question number,
so a second run inserts nothing and reports what it skipped. Rows that fail validation are
never written: they are listed in the run's `question_import_batches` row with the reason.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import asyncpg
import yaml

ROOT = Path(__file__).resolve().parent.parent
FORMAT_VERSION = 1
IMPORT_FORMAT = "waec-objective-transcription-1"
CURRICULUM_NAMESPACE = "stackprep-curriculum-import-v1"
QUESTION_NAMESPACE = "stackprep-question-import-v1"
#: JAMB papers up to the mid-1990s offered five options; the modern ones offer four. The
#: schema allows A-F, so a paper's own shape decides how many a question has, and
#: option_count records it.
OPTION_KEYS = ("A", "B", "C", "D", "E")
MINIMUM_OPTIONS = 4
DEFAULT_IMPORTER = "Transcription import (model-proposed)"
#: Skill mappings come from a model at import time. The number is a placeholder for a real
#: estimate, and says only "this was proposed, not judged".
MODEL_CLASSIFICATION_CONFIDENCE = 0.5


def uuid_for(key: str, namespace: str = QUESTION_NAMESPACE) -> str:
    """Deterministic UUID, matching the scheme used by database/load_syllabus.rb."""
    digest = bytearray(hashlib.sha1(f"{namespace}:{key}".encode()).digest()[:16])
    digest[6] = (digest[6] & 0x0F) | 0x50
    digest[8] = (digest[8] & 0x3F) | 0x80
    hex_digest = digest.hex()
    return (
        f"{hex_digest[0:8]}-{hex_digest[8:12]}-{hex_digest[12:16]}-"
        f"{hex_digest[16:20]}-{hex_digest[20:32]}"
    )


def repo_relative(path: Path) -> str:
    """Path relative to the repository when it lives inside it, absolute otherwise."""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def normalise(text: str) -> str:
    """Collapse whitespace and unify unicode, for hashing and comparison."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip()


def content_hash(stem: str, options: dict[str, str]) -> str:
    payload = (
        normalise(stem)
        + "|"
        + "|".join(f"{key}:{normalise(options[key])}" for key in sorted(options))
    )
    return hashlib.sha256(payload.encode()).hexdigest()


@dataclass
class Rejection:
    number: Any
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {"question_number": self.number, "reason": self.reason}


@dataclass
class Prepared:
    questions: list[dict[str, Any]] = field(default_factory=list)
    rejections: list[Rejection] = field(default_factory=list)


def fail(message: str) -> None:
    print(f"Loader error: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_levels(path: Path | None) -> dict[int, dict[str, Any]]:
    """Read proposed difficulty levels, keyed by question number."""
    if path is None:
        return {}
    doc = yaml.safe_load(path.read_text())
    if doc.get("format_version") != FORMAT_VERSION:
        fail(f"unsupported levels format_version: {doc.get('format_version')!r}")
    levels: dict[int, dict[str, Any]] = {}
    for entry in doc.get("levels") or []:
        number = entry.get("number")
        level = entry.get("proposed_level")
        confidence = str(entry.get("level_confidence") or "").strip().lower()
        if not isinstance(number, int) or level not in (1, 2, 3, 4, 5):
            fail(f"levels entry {entry!r} needs an integer number and a level of 1-5")
        if confidence not in {"low", "medium", "high"}:
            fail(f"levels entry for question {number} has confidence {confidence!r}")
        levels[number] = {"level": level, "confidence": confidence}
    return levels


def prepare(
    doc: dict[str, Any], skills: dict[str, str], allow_incomplete: bool = False,
    allow_unanswered: bool = False,
) -> Prepared:
    """Validate every transcribed question. Bad rows are rejected, not written."""
    prepared = Prepared()
    seen_numbers: set[int] = set()
    seen_hashes: dict[str, int] = {}
    # A passage whose scan lost text cannot carry a cloze question: the candidate would be
    # asked to complete a sentence we cannot show them in full.
    passage_ids: set[str] = set()
    incomplete_passages: set[str] = set()
    for passage in doc.get("passages") or []:
        key = str(passage.get("id") or "")
        if not key:
            continue
        if "[unclear]" in str(passage.get("text") or "").lower():
            incomplete_passages.add(key)
        else:
            passage_ids.add(key)

    for raw in doc.get("questions") or []:
        number = raw.get("number")
        if not isinstance(number, int):
            prepared.rejections.append(
                Rejection(number, "question number is missing or not an integer")
            )
            continue
        if number in seen_numbers:
            prepared.rejections.append(
                Rejection(number, "duplicate question number in the transcription")
            )
            continue

        stem = normalise(str(raw.get("stem") or ""))
        if not stem:
            prepared.rejections.append(Rejection(number, "empty stem"))
            continue
        incomplete = "[unclear]" in stem.lower()
        if incomplete and not allow_incomplete:
            prepared.rejections.append(
                Rejection(number, "stem contains [unclear]; needs a human read")
            )
            continue

        options_raw = raw.get("options") or {}
        options = {
            key: normalise(str(options_raw.get(key, "")))
            for key in OPTION_KEYS
            if str(options_raw.get(key, "")).strip()
        }
        # A gap in the middle is damage; a missing E on a four-option paper is not.
        expected = OPTION_KEYS[:len(options)]
        missing = [key for key in expected if not options.get(key)]
        if len(options) < MINIMUM_OPTIONS or missing:
            prepared.rejections.append(
                Rejection(number, "missing option(s): "
                          + (", ".join(missing) or f"only {len(options)} provided"))
            )
            continue
        if any("[unclear]" in value.lower() for value in options.values()):
            if not allow_incomplete:
                prepared.rejections.append(
                    Rejection(number, "an option contains [unclear]; needs a human read")
                )
                continue
            incomplete = True

        answer: str | None = str(raw.get("proposed_answer") or "").strip().upper() or None
        confidence: str | None = str(raw.get("answer_confidence") or "").strip().lower() or None
        # A paper that ships no answer key leaves the question unanswered rather than
        # guessed: no option is marked correct, and the database refuses to approve it. The
        # JAMB Mathematics compilation is the first source like this.
        if allow_unanswered and answer is None:
            confidence = None
        else:
            if answer not in OPTION_KEYS:
                prepared.rejections.append(
                    Rejection(number, f"proposed answer {answer!r} is not one of A-D")
                )
                continue
            if confidence not in {"low", "medium", "high"}:
                prepared.rejections.append(
                    Rejection(number, f"answer_confidence {confidence!r} is not low/medium/high")
                )
                continue

        skill_code = str(raw.get("proposed_skill") or "").strip()
        if skill_code not in skills:
            prepared.rejections.append(
                Rejection(
                    number, f"skill code {skill_code!r} is not a skill in this syllabus version"
                )
            )
            continue

        # A cloze item is unanswerable without its passage, so a dangling reference is a
        # rejection rather than a question that merely looks odd later.
        passage_ref = raw.get("passage_ref")
        if passage_ref is not None and str(passage_ref) in incomplete_passages:
            if not allow_incomplete:
                prepared.rejections.append(
                    Rejection(
                        number, f"passage {passage_ref} is incomplete in the scan; re-scan the page"
                    )
                )
                continue
            incomplete = True
        elif passage_ref is not None and str(passage_ref) not in passage_ids:
            prepared.rejections.append(
                Rejection(
                    number, f"passage_ref {passage_ref!r} is not in this transcription's passages"
                )
            )
            continue

        digest = content_hash(stem, options)
        if digest in seen_hashes:
            prepared.rejections.append(
                Rejection(number, f"duplicate of question {seen_hashes[digest]}")
            )
            continue

        seen_numbers.add(number)
        seen_hashes[digest] = number
        prepared.questions.append(
            {
                "number": number,
                "page": raw.get("page"),
                "section": raw.get("section"),
                "instruction": normalise(str(raw.get("instruction") or "")) or None,
                "stem": stem,
                "options": options,
                "option_keys": list(options),
                "answer": answer,
                "answer_confidence": confidence,
                "skill_id": skills[skill_code],
                "skill_code": skill_code,
                "skill_reason": normalise(str(raw.get("skill_reason") or ""))
                or "Proposed by a model during import; not yet reviewed.",
                "passage_ref": str(passage_ref) if passage_ref is not None else None,
                "incomplete": incomplete,
                "figures": raw.get("figures") or [],
                "content_hash": digest,
            }
        )

    return prepared


async def resolve_target(
    conn: asyncpg.Connection, subject_code: str, version_label: str
) -> tuple[asyncpg.Record, dict[str, str]]:
    subject = await conn.fetchrow(
        """
        SELECT s.id AS subject_id, s.examination_id, v.id AS syllabus_version_id
        FROM subjects s
        JOIN syllabus_versions v ON v.subject_id = s.id
        WHERE s.code = $1 AND v.version_label = $2
        """,
        subject_code,
        version_label,
    )
    if subject is None:
        fail(
            f"no {subject_code} subject with syllabus version {version_label!r}; "
            "import the syllabus first"
        )

    rows = await conn.fetch(
        """
        SELECT code, id FROM curriculum_items
        WHERE syllabus_version_id = $1 AND item_type = 'skill'
        """,
        subject["syllabus_version_id"],
    )
    return subject, {row["code"]: str(row["id"]) for row in rows}


async def apply_keys(conn: asyncpg.Connection, subject: asyncpg.Record, path: Path) -> None:
    """Attach worked-out answers to questions that were imported without any.

    The JAMB Mathematics compilation prints no key, so its questions load with no correct
    option at all. The answers live in their own file, computed separately and carrying one
    line of working each, because a bare letter is unreviewable: a marker would have to redo
    the question from scratch to disagree with it.

    Answers land as `model_proposed`, which is what they are, and the working is stored as
    the question's first solution step. Only drafts are touched.
    """
    doc = yaml.safe_load(path.read_text())
    if doc.get("format_version") != FORMAT_VERSION:
        fail(f"unsupported keys format_version: {doc.get('format_version')!r}")
    year = doc.get("exam_year")
    if not year:
        fail("keys file must name its exam_year")

    applied = skipped = 0
    for entry in doc.get("answers") or []:
        number = str(entry.get("number"))
        answer = str(entry.get("answer") or "").strip().upper()
        confidence = str(entry.get("confidence") or "").strip().lower()
        working = normalise(str(entry.get("working") or ""))
        if answer not in OPTION_KEYS:
            fail(f"{year} Q{number}: answer {answer!r} is not one of A-D")
        if confidence not in {"low", "medium", "high"}:
            fail(f"{year} Q{number}: confidence {confidence!r} is not low/medium/high")
        if not working:
            fail(f"{year} Q{number}: an answer without working cannot be reviewed")

        version = await conn.fetchrow(
            """
            SELECT v.id, v.review_status
            FROM questions q JOIN question_versions v ON v.id = q.current_version_id
            WHERE q.subject_id = $1 AND q.exam_year = $2 AND q.question_number = $3
            """,
            subject["subject_id"], int(year), number,
        )
        if version is None or version["review_status"] != "draft":
            skipped += 1
            continue
        await conn.execute(
            """
            UPDATE question_versions
               SET answer_source = 'model_proposed', answer_confidence = $2,
                   solution_steps = $3::jsonb
             WHERE id = $1 AND review_status = 'draft'
            """,
            version["id"], confidence, json.dumps([working]),
        )
        # Two statements: the partial unique index allows only one correct option per
        # version, and clearing first keeps a re-run from colliding with itself.
        await conn.execute(
            "UPDATE question_options SET is_correct = false WHERE question_version_id = $1",
            version["id"],
        )
        await conn.execute(
            """
            UPDATE question_options SET is_correct = true
             WHERE question_version_id = $1 AND option_key = $2
            """,
            version["id"], answer,
        )
        applied += 1
    print(f"Answers: {applied} attached, {skipped} skipped (missing or no longer draft).")


async def load(args: argparse.Namespace) -> int:
    transcription_path = Path(args.transcription).resolve()
    pdf_path = Path(args.pdf).resolve()
    if not transcription_path.is_file():
        fail(f"transcription not found: {transcription_path}")
    if not pdf_path.is_file():
        fail(f"PDF not found: {pdf_path}")

    doc = yaml.safe_load(transcription_path.read_text())
    if doc.get("format_version") != FORMAT_VERSION:
        fail(f"unsupported transcription format_version: {doc.get('format_version')!r}")

    source = doc.get("source") or {}
    for required in ("exam_year", "paper_label"):
        if not source.get(required):
            fail(f"source.{required} is required")

    pdf_sha = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    transcription_sha = hashlib.sha256(transcription_path.read_bytes()).hexdigest()
    paper_code = str(source.get("paper_code") or f"{source['exam_year']}-OBJ")
    # Where the answers came from. A model's proposal is the default because that is what a
    # transcription produces; a paper that prints its own key says so and gets recorded as
    # such. Neither can be approved without a person — the database sees to that — but a
    # reviewer checking a key is doing a different job from a reviewer checking a guess.
    answer_source = str(source.get("answer_source") or "model_proposed").strip()
    if answer_source not in ("unverified", "model_proposed", "published_key"):
        fail(
            f"source.answer_source {answer_source!r} is not one of unverified, "
            "model_proposed, published_key; a key that needs no checking is not something "
            "an import may claim"
        )
    duration_minutes = source.get("duration_minutes")
    total_marks = source.get("marks")

    dsn = (args.database_url or "").replace("+asyncpg", "", 1) or None
    conn = await asyncpg.connect(
        dsn=dsn,
        # TCP, not the Unix socket under ROOT: ROOT is this working copy, so from a git
        # worktree the socket path points at a directory that does not exist — and a
        # socket path is capped at 103 bytes, which a worktree path can exceed on its own.
        host=None if dsn else "127.0.0.1",
        port=None if dsn else 55439,
        database=None if dsn else "scorepilot",
    )
    try:
        await conn.execute("SET search_path = stackprep, public")
        subject, skills = await resolve_target(conn, args.subject, args.syllabus_version)
        prepared = prepare(doc, skills, allow_incomplete=args.allow_incomplete_passages,
                           allow_unanswered=answer_source == "unverified")
        levels = load_levels(Path(args.levels).resolve() if args.levels else None)
        if levels:
            missing = [q["number"] for q in prepared.questions if q["number"] not in levels]
            print(
                f"Levels file covers {len(levels)} questions; "
                f"{len(missing)} loaded questions have none."
            )

        total = len(doc.get("questions") or [])
        print(
            f"Transcription: {total} questions, {len(prepared.questions)} valid, "
            f"{len(prepared.rejections)} rejected."
        )
        for rejection in prepared.rejections:
            print(f"  rejected Q{rejection.number}: {rejection.reason}")
        if not prepared.questions:
            fail("nothing to import")

        # Per-question marks and time come from the paper as a whole, so a transcription
        # that is missing pages does not inflate them.
        paper_questions = source.get("question_count") or total
        marks_each = round(total_marks / paper_questions, 2) if total_marks else None
        seconds_each = (
            max(10, min(1800, round(duration_minutes * 60 / paper_questions)))
            if duration_minutes
            else None
        )
        # The note has to describe THIS source. The WAEC papers print duration and marks on
        # the cover; the JAMB compilation prints neither, and saying otherwise would put a
        # false citation next to a defaulted number.
        printed = [
            name for name, value in
            (("duration", duration_minutes), ("marks", total_marks)) if value
        ]
        confirmation_note = (
            (f"{' and '.join(printed).capitalize()} as printed with the paper. "
             if printed else "")
            + ("Marks are not printed with this paper; score_out_of is the schema default. "
               if not total_marks else "")
            + ("Duration is not printed with this paper. " if not duration_minutes else "")
            + "The question count is what the transcription contains and has not been "
              "checked against the paper."
        )
        print(f"Answers recorded as {answer_source}.")
        print(
            f"Paper {paper_code}: {marks_each if marks_each else 'unknown'} marks and "
            f"{seconds_each if seconds_each else 'unknown'} seconds per question."
        )

        if args.dry_run:
            print("Dry run complete; no database changes.")
            return 0

        document_id = uuid_for(f"document:{pdf_sha}", CURRICULUM_NAMESPACE)
        paper_id = uuid_for(f"paper:{subject['subject_id']}:{paper_code}")
        batch_id = uuid_for(f"batch:{transcription_sha}")
        importer_id = uuid_for(f"reviewer:{args.importer}")

        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO academic_reviewers (id, display_name, active)
                VALUES ($1, $2, true) ON CONFLICT (id) DO NOTHING
                """,
                importer_id,
                args.importer,
            )
            await conn.execute(
                """
                INSERT INTO source_documents (id, examination_id, subject_id, document_type,
                  title, file_uri, file_sha256, mime_type, page_count, document_year,
                  paper_code, licence_status, processing_status, review_status, uploaded_by)
                VALUES ($1, $2, $3, 'paper', $4, $5, $6, 'application/pdf', $7, $8, $9,
                  'pending', 'processed', 'pending', $10)
                ON CONFLICT (id) DO NOTHING
                """,
                document_id,
                subject["examination_id"],
                subject["subject_id"],
                f"{source['paper_label']} ({source['exam_year']})",
                repo_relative(pdf_path),
                pdf_sha,
                source.get("page_count"),
                source["exam_year"],
                paper_code,
                importer_id,
            )
            await conn.execute(
                """
                INSERT INTO exam_papers (id, subject_id, paper_code, name, response_mode,
                  question_count, duration_minutes, options_per_question, score_out_of,
                  values_confirmed, confirmation_note, pilot_support_status, status)
                -- score_out_of is NOT NULL with a default of 100. A paper that does not
                -- print its mark allocation gets that default, and the note below says so
                -- rather than letting the number pass for a fact about the paper.
                VALUES ($1, $2, $3, $4, 'objective', $5, $6, 4, coalesce($7, 100), false, $8,
                  'undecided', 'draft')
                -- A later, fuller transcription of the same paper corrects the count. A
                -- structure a reviewer has confirmed is never overwritten.
                ON CONFLICT (id) DO UPDATE SET
                  question_count = EXCLUDED.question_count,
                  duration_minutes = COALESCE(EXCLUDED.duration_minutes,
                                              exam_papers.duration_minutes),
                  score_out_of = COALESCE(EXCLUDED.score_out_of, exam_papers.score_out_of),
                  confirmation_note = EXCLUDED.confirmation_note,
                  updated_at = now()
                WHERE NOT exam_papers.values_confirmed
                """,
                paper_id,
                subject["subject_id"],
                paper_code,
                f"{source['paper_label']} ({source['exam_year']})",
                paper_questions,
                duration_minutes,
                total_marks,
                confirmation_note,
            )
            await conn.execute(
                """
                INSERT INTO question_import_batches (id, subject_id, source_document_id,
                  import_file_uri, import_file_sha256, format_version, row_count,
                  created_count, skipped_count, rejected_count, rejected_rows, imported_by)
                VALUES ($1, $2, $3, $4, $5, $6, $7, 0, 0, $8, $9, $10)
                ON CONFLICT (id) DO NOTHING
                """,
                batch_id,
                subject["subject_id"],
                document_id,
                repo_relative(transcription_path),
                transcription_sha,
                IMPORT_FORMAT,
                total,
                len(prepared.rejections),
                json.dumps([r.as_dict() for r in prepared.rejections]),
                importer_id,
            )

            # Cloze and comprehension items share one passage; it is stored once and
            # referenced, so rights and reading time live in a single place.
            passage_uuids: dict[str, str] = {}
            for passage in doc.get("passages") or []:
                key = str(passage.get("id"))
                body = str(passage.get("text") or "").strip()
                if not key or not body:
                    continue
                if "[unclear]" in body.lower() and not args.allow_incomplete_passages:
                    continue
                passage_uuids[key] = uuid_for(f"passage:{pdf_sha}:{key}")
                await conn.execute(
                    """
                    INSERT INTO passages (id, subject_id, source_document_id, title, body,
                      passage_type, licence_status, review_status)
                    VALUES ($1, $2, $3, $4, $5, 'prose', 'pending', 'draft')
                    ON CONFLICT (id) DO NOTHING
                    """,
                    passage_uuids[key],
                    subject["subject_id"],
                    document_id,
                    passage.get("label"),
                    body,
                )
            if passage_uuids:
                print(f"Stored {len(passage_uuids)} shared passage(s).")

            created = 0
            skipped = 0
            corrected = 0
            levelled = 0
            flagged = 0
            for item in prepared.questions:
                question_id = uuid_for(f"question:{pdf_sha}:{paper_code}:{item['number']}")
                version_id = uuid_for(f"version:{question_id}:1")

                # Against the version the question is ON, not the one it arrived as. A
                # question that has since been corrected — a repaired option list, a key put
                # right — is on version 2 or 3, and version 1 still holds the text that was
                # wrong. Comparing with version 1 asks whether the transcription matches a row
                # nobody reads, and the answer for every corrected question is no: the whole
                # paper is refused on the strength of a difference that was the point.
                existing = await conn.fetchrow(
                    """
                    SELECT v.id, v.stem, v.marks, v.expected_seconds, v.review_status
                    FROM questions q
                    JOIN question_versions v ON v.id = q.current_version_id
                    WHERE q.id = $1
                    """,
                    question_id,
                )
                if existing is not None:
                    version_id = existing["id"]
                    if normalise(existing["stem"]) != item["stem"]:
                        fail(
                            f"question {item['number']} already exists with different text; "
                            "import a correction as a new version instead"
                        )
                    # Marks and timing are derived from the paper, so a fuller transcription
                    # corrects them. Only drafts: approved content is frozen by design.
                    stale = existing["review_status"] == "draft" and (
                        existing["marks"] != marks_each
                        or existing["expected_seconds"] != seconds_each
                    )
                    if stale:
                        await conn.execute(
                            """
                            UPDATE question_versions SET marks = $2, expected_seconds = $3
                            WHERE id = $1
                            """,
                            version_id,
                            marks_each,
                            seconds_each,
                        )
                        corrected += 1
                    level = levels.get(item["number"])
                    if level and existing["review_status"] == "draft":
                        await conn.execute(
                            """
                            UPDATE question_versions
                            SET mastery_level_number = $2, level_source = 'model_proposed',
                                level_confidence = $3
                            WHERE id = $1 AND level_source IN ('unverified', 'model_proposed')
                            """,
                            version_id,
                            level["level"],
                            level["confidence"],
                        )
                        levelled += 1
                    skipped += 1
                    continue

                await conn.execute(
                    """
                    INSERT INTO questions (id, subject_id, exam_paper_id, origin,
                      source_document_id, exam_year, paper_code, question_number,
                      import_batch_id, usage_pool, created_by)
                    VALUES ($1, $2, $3, 'past_paper', $4, $5, $6, $7, $8, $9, $10)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    question_id,
                    subject["subject_id"],
                    paper_id,
                    document_id,
                    source["exam_year"],
                    paper_code,
                    str(item["number"]),
                    batch_id,
                    args.pool,
                    importer_id,
                )
                await conn.execute(
                    """
                    INSERT INTO question_versions (id, question_id, subject_id, version, stem,
                      instructions, passage_id, response_format, marking_method, solution_steps,
                      hints, marks, expected_seconds, option_count, content_hash, authored_by,
                      answer_source, answer_confidence, mastery_level_number, level_source,
                      level_confidence, review_status)
                    VALUES ($1, $2, $3, 1, $4, $5, $6, 'mcq_single', 'auto_key', '[]'::jsonb,
                      '[]'::jsonb, $7, $8, $16, $9, $10, $15, $11, $12, $13, $14,
                      'draft')
                    """,
                    version_id,
                    question_id,
                    subject["subject_id"],
                    item["stem"],
                    item["instruction"],
                    passage_uuids.get(item["passage_ref"]) if item["passage_ref"] else None,
                    marks_each,
                    seconds_each,
                    item["content_hash"],
                    importer_id,
                    item["answer_confidence"],
                    (levels.get(item["number"]) or {}).get("level"),
                    "model_proposed" if levels.get(item["number"]) else "unverified",
                    (levels.get(item["number"]) or {}).get("confidence"),
                    answer_source,
                    len(item["option_keys"]),
                )
                if levels.get(item["number"]):
                    levelled += 1
                if item["incomplete"]:
                    # The scan lost text. Recorded against the question so it cannot be
                    # approved by someone who does not notice the gap.
                    await conn.execute(
                        """
                        INSERT INTO question_reports (id, question_version_id, reporter_kind,
                          reason, detail, status)
                        VALUES ($1, $2, 'system', 'other', $3, 'open')
                        ON CONFLICT (id) DO NOTHING
                        """,
                        uuid_for(f"report:incomplete:{version_id}"),
                        version_id,
                        "Imported from a cropped scan: some text is missing and marked "
                        "[unclear]. Replace from a cleaner copy of the page before approving.",
                    )
                    flagged += 1
                await conn.execute(
                    "UPDATE questions SET current_version_id = $1 WHERE id = $2",
                    version_id,
                    question_id,
                )
                for position, key in enumerate(item["option_keys"], start=1):
                    await conn.execute(
                        """
                        INSERT INTO question_options (id, question_version_id, subject_id,
                          option_key, body, is_correct, display_order)
                        VALUES ($1, $2, $3, $4, $5, $6, $7)
                        """,
                        uuid_for(f"option:{version_id}:{key}"),
                        version_id,
                        subject["subject_id"],
                        key,
                        item["options"][key],
                        key == item["answer"],
                        position,
                    )
                for figure in item["figures"]:
                    if not figure.get("file"):
                        continue
                    await conn.execute(
                        """
                        INSERT INTO question_assets (id, question_version_id, storage_uri,
                          mime_type, byte_size, width, height, alt_text, alt_text_source,
                          source_location, licence_status, display_order)
                        VALUES ($1, $2, $3, 'image/png', $4, $5, $6, $7, $8, $9, 'pending', $10)
                        ON CONFLICT (id) DO NOTHING
                        """,
                        uuid_for(f"asset:{version_id}:{figure.get('sha256')}"),
                        version_id,
                        str(figure["file"]),
                        figure.get("byte_size"),
                        figure.get("width"),
                        figure.get("height"),
                        figure.get("alt_text"),
                        str(figure.get("alt_text_source") or "unverified"),
                        figure.get("source_location"),
                        figure.get("display_order", 0),
                    )
                await conn.execute(
                    """
                    INSERT INTO question_classifications (id, question_id, subject_id,
                      curriculum_item_id, syllabus_version_id, classification_role,
                      proposed_by, confidence, classification_reason, review_status)
                    VALUES ($1, $2, $3, $4, $5, 'primary', 'model', $6, $7, 'draft')
                    ON CONFLICT (id) DO NOTHING
                    """,
                    uuid_for(f"classification:{question_id}:{item['skill_id']}"),
                    question_id,
                    subject["subject_id"],
                    item["skill_id"],
                    subject["syllabus_version_id"],
                    MODEL_CLASSIFICATION_CONFIDENCE,
                    item["skill_reason"],
                )
                created += 1

            # The batch row describes the most recent run of this file, so every count is
            # refreshed together: a re-run with different options rejects a different set.
            await conn.execute(
                """
                UPDATE question_import_batches
                SET created_count = $2, skipped_count = $3, rejected_count = $4,
                    rejected_rows = $5, imported_at = now()
                WHERE id = $1
                """,
                batch_id,
                created,
                skipped,
                len(prepared.rejections),
                json.dumps([r.as_dict() for r in prepared.rejections]),
            )

        print(
            f"Imported {created} questions, skipped {skipped} already present"
            + (f" ({corrected} had stale marks or timing corrected)." if corrected else ".")
        )
        if levelled:
            print(
                f"Applied proposed difficulty levels to {levelled} questions "
                "(level_source = model_proposed)."
            )
        if flagged:
            print(
                f"Flagged {flagged} questions as imported from a cropped scan; "
                "see question_reports."
            )
        if args.keys:
            await apply_keys(conn, subject, Path(args.keys).resolve())

        print(
            f"All rows are drafts. Answers are recorded as {answer_source} and cannot be "
            "approved until a person verifies them (see stackprep.questions_awaiting_answer_check)."
        )
    finally:
        await conn.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transcription", required=True, help="Transcribed paper, YAML")
    parser.add_argument("--pdf", required=True, help="The source PDF the transcription came from")
    parser.add_argument("--subject", default="ENG", help="Subject code (default ENG)")
    parser.add_argument(
        "--syllabus-version", default="waec-2027", help="Syllabus version label to classify against"
    )
    parser.add_argument(
        "--pool", default="practice", choices=["practice", "diagnostic", "held_out"]
    )
    parser.add_argument(
        "--importer", default=DEFAULT_IMPORTER, help="Name recorded as the importer"
    )
    parser.add_argument("--levels", default=None, help="Proposed difficulty levels, YAML")
    parser.add_argument("--keys", default=None,
                        help="Worked-out answers for a paper that printed none, YAML")
    parser.add_argument(
        "--allow-incomplete-passages",
        action="store_true",
        help="Import questions whose scan lost text, flagging each one for re-scanning",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="PostgreSQL URL; defaults to the local project database",
    )
    parser.add_argument("--dry-run", action="store_true", help="Validate without writing")
    return asyncio.run(load(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
