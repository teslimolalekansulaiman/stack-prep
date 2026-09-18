#!/usr/bin/env python3
"""Accept the published answer keys for UTME Use of English, and approve the questions.

    uv run python database/publish_english_questions.py \
        --reviewer <academic_reviewers.id> --apply

WHAT THIS RECORDS, and what it does not. The reviewer named on the command line is accepting,
in one decision, that the answer key printed with the past-question compilation is our answer
for these questions, and that the proposed difficulty levels are good enough to start with.
That is a real decision a person is entitled to make, and every row says who made it and
when, so a later pass can revisit any of them.

It is not a claim that anybody read 754 questions. The explanations this writes are generated
and are marked `solution_source = 'model_proposed'`, which puts every one of them in
`questions_awaiting_explanation_check` — including, and especially, the approved ones, which
are the ones students are now being shown. That view is the list of work this script creates.

WHY THE EXPLANATIONS ARE THIN ON PURPOSE. A UTME English question is set against a printed
direction that says exactly what is being tested: the option nearest in meaning, the option
opposite in meaning, the word with the same vowel sound. A hint that names the strategy for
that kind of question is true for every question of that kind, and useful. A solution that
names the key and the rule is true. Neither invents a gloss for a word nobody checked, which
is the thing a generated explanation would otherwise be tempted to do and the thing a student
would be misled by. Thin and true beats full and invented.

Timing comes from the level, on the JAMB clock: sixty questions in an hour is a minute each
on average, so an easy question is given less and a hard one more.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parent.parent

EXAMINATION = "UTME"
SUBJECT = "ENG"

#: Seconds allowed per question by proposed level. The paper gives sixty questions in an
#: hour; these spread that minute according to how hard the question was judged to be.
SECONDS_BY_LEVEL = {1: 30, 2: 45, 3: 60, 4: 80, 5: 100}

#: A hint and a solution opening for each skill the syllabus lists. Keyed on the skill rather
#: than the printed direction because the direction's wording drifts from year to year — 59
#: variants across nine papers — while what is being tested does not.
BY_SKILL: dict[str, tuple[str, str]] = {
    "ENG.A.1.i": (
        "Find the part of the passage the question is about before you look at the options. "
        "The answer is stated or implied there, not in what you already know about the topic.",
        "This asks what the passage says. The published key gives {key}.",
    ),
    "ENG.A.2.i": (
        "Read the whole sentence the word sits in. A word's meaning here is the one the "
        "sentence needs, which is often not its most common meaning.",
        "This asks what a word or phrase means in this passage. The published key gives {key}.",
    ),
    "ENG.A.3.i": (
        "Ask what the writer is doing in that line — giving a reason, drawing a conclusion, "
        "conceding a point — rather than what they are talking about.",
        "This asks about the reasoning in the passage. The published key gives {key}.",
    ),
    "ENG.A.4.i": (
        "This is set on the approved reading text for your year. Answer from the book, not "
        "from a summary of it.",
        "This is set on the approved reading text. The published key gives {key}.",
    ),
    "ENG.A.5.i": (
        "A summary answer keeps the writer's point and drops the example. If an option "
        "repeats a detail, it is usually the wrong one.",
        "This asks you to combine the passage's ideas into one statement. The published key "
        "gives {key}.",
    ),
    "ENG.A.6.i": (
        "Read past the gap to the end of the sentence before choosing. A cloze gap is fixed "
        "by what follows it at least as often as by what comes before.",
        "This is a cloze gap: the option that fits the sentence and the passage around it. "
        "The published key gives {key}.",
    ),
    "ENG.B.1.i": (
        "Put each option back into the original sentence. The nearest in meaning is the one "
        "that leaves the sentence saying the same thing.",
        "This asks for the option nearest in meaning to the word in italics. The published "
        "key gives {key}.",
    ),
    "ENG.B.2.i": (
        "Decide what the word means in this sentence first, then look for its opposite. An "
        "option that is merely different, rather than opposite, is the usual trap.",
        "This asks for the option opposite in meaning to the word in italics. The published "
        "key gives {key}.",
    ),
    "ENG.B.3.i": (
        "Read the whole sentence with each option in the gap. The one that is grammatical "
        "all the way to the full stop is the answer.",
        "This asks for the option that completes the sentence. The published key gives {key}.",
    ),
    "ENG.B.3.ii": (
        "Say the sentence back in your own words before reading the options, then find the "
        "option that matches what you said.",
        "This asks which option best explains the sentence. The published key gives {key}.",
    ),
    "ENG.B.4.i": (
        "Ask what job the word is doing in the sentence — naming, describing, joining — "
        "rather than what kind of word it usually is.",
        "This is about word classes and the work they do in a sentence. The published key "
        "gives {key}.",
    ),
    "ENG.B.5.i": (
        "Find the subject first, then make the verb agree with it. The word nearest the verb "
        "is often not the subject.",
        "This is about tense, mood or agreement. The published key gives {key}.",
    ),
    "ENG.B.6.i": (
        "Say the word slowly and count its parts. Most spelling errors set here are a doubled "
        "letter that should be single, or the reverse.",
        "This is about correct spelling. The published key gives {key}.",
    ),
    "ENG.B.7.i": (
        "An idiom does not mean what its words mean separately. If one option is the literal "
        "reading, it is usually there to be rejected.",
        "This is about ordinary, figurative or idiomatic usage. The published key gives {key}.",
    ),
    "ENG.C.1.i": (
        "Say the words aloud and listen to the vowel, not the spelling. English spells one "
        "vowel sound many ways.",
        "This asks which option has the same vowel sound. The published key gives {key}.",
    ),
    "ENG.C.2.i": (
        "Listen to the consonant itself, and to whether your voice is on or off when you say "
        "it. Spelling will mislead you here.",
        "This asks about consonant sounds. The published key gives {key}.",
    ),
    "ENG.C.3.i": (
        "Rhyme is about the sound from the last stressed vowel onwards. Words that look alike "
        "often do not rhyme, and words that look nothing alike often do.",
        "This asks which options rhyme, or sound alike. The published key gives {key}.",
    ),
    "ENG.C.4.i": (
        "Say the word naturally and feel which syllable you push hardest. Saying it "
        "syllable-by-syllable hides the stress rather than showing it.",
        "This asks which syllable carries the stress. The published key gives {key}.",
    ),
    "ENG.C.5.i": (
        "Emphatic stress answers a question. Work out what question the sentence is "
        "answering, and stress the word that answers it.",
        "This asks which word carries the emphatic stress. The published key gives {key}.",
    ),
}

#: Said on every generated explanation, so a student is never told this was checked and a
#: reviewer can see at a glance which ones still need writing.
UNCHECKED = (
    "A fuller explanation is still being written for this question."
)


async def run(reviewer_id: str, dsn: str | None, apply: bool) -> int:
    conn = await asyncpg.connect(
        dsn=dsn,
        host=None if dsn else str(ROOT / ".local/run"),
        port=None if dsn else 55439,
        database=None if dsn else "scorepilot",
    )
    try:
        await conn.execute("SET search_path = stackprep, public")
        reviewer = await conn.fetchrow(
            "SELECT id, display_name FROM academic_reviewers WHERE id = $1 AND active",
            reviewer_id,
        )
        if reviewer is None:
            raise SystemExit("no active reviewer with that id")
        subject_id = await conn.fetchval(
            """
            SELECT s.id FROM subjects s
            JOIN examinations e ON e.id = s.examination_id
            WHERE s.code = $1 AND e.short_name = $2
            """,
            SUBJECT,
            EXAMINATION,
        )
        if subject_id is None:
            raise SystemExit(f"no {EXAMINATION} subject with code {SUBJECT}")

        rows = await conn.fetch(
            """
            SELECT q.id AS question_id, v.id AS version_id, v.mastery_level_number AS level,
                   ci.code AS skill_code,
                   (SELECT o.option_key FROM question_options o
                     WHERE o.question_version_id = v.id AND o.is_correct) AS key,
                   v.authored_by
            FROM questions q
            JOIN question_versions v ON v.id = q.current_version_id
            JOIN question_classifications c
              ON c.question_id = q.id AND c.classification_role = 'primary'
            JOIN curriculum_items ci ON ci.id = c.curriculum_item_id
            WHERE q.subject_id = $1 AND q.retired_at IS NULL
              AND v.review_status = 'draft'
            ORDER BY q.exam_year, q.question_number
            """,
            subject_id,
        )
        unknown = sorted({row["skill_code"] for row in rows} - set(BY_SKILL))
        if unknown:
            raise SystemExit(f"no explanation written for these skills yet: {unknown}")
        conflicts = [row for row in rows if str(row["authored_by"]) == str(reviewer_id)]
        if conflicts:
            raise SystemExit(
                f"{len(conflicts)} of these questions were authored by this reviewer; "
                "approval needs a second pair of eyes"
            )

        print(f"{len(rows)} draft questions, to be approved by {reviewer['display_name']}.")
        if not apply:
            print("\nDry run; pass --apply to record the decision.")
            return 0

        async with conn.transaction():
            for row in rows:
                hint, solution = BY_SKILL[row["skill_code"]]
                steps = json.dumps([solution.format(key=row["key"] or "no option"), UNCHECKED])
                await conn.execute(
                    """
                    UPDATE question_versions
                       SET answer_source = 'expert_verified',
                           answer_confidence = 'medium',
                           level_source = 'expert_verified',
                           level_confidence = 'low',
                           solution_steps = $2::jsonb,
                           hints = $3::jsonb,
                           solution_source = 'model_proposed',
                           expected_seconds = $4
                     WHERE id = $1
                    """,
                    row["version_id"],
                    steps,
                    json.dumps([hint]),
                    SECONDS_BY_LEVEL.get(int(row["level"] or 3), 60),
                )
                await conn.execute(
                    """
                    UPDATE question_classifications
                       SET review_status = 'approved', reviewed_by = $2, reviewed_at = now()
                     WHERE question_id = $1 AND classification_role = 'primary'
                       AND review_status <> 'approved'
                    """,
                    row["question_id"],
                    reviewer_id,
                )
                await conn.execute(
                    """
                    UPDATE question_versions
                       SET review_status = 'approved', reviewed_by = $2, reviewed_at = now()
                     WHERE id = $1
                    """,
                    row["version_id"],
                    reviewer_id,
                )

        deliverable = await conn.fetchval(
            "SELECT count(*) FROM deliverable_questions WHERE subject_id = $1", subject_id
        )
        waiting = await conn.fetchval(
            """
            SELECT count(*) FROM questions_awaiting_explanation_check
            WHERE subject_id = $1
            """,
            subject_id,
        )
        print(f"{deliverable} questions are now deliverable.")
        print(
            f"{waiting} carry a generated explanation and are listed in "
            "questions_awaiting_explanation_check, which is the work this created."
        )
        return 0
    finally:
        await conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    return asyncio.run(run(args.reviewer, args.database_url, args.apply))


if __name__ == "__main__":
    sys.exit(main())
