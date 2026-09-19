#!/usr/bin/env python3
"""Split the UTME "Basic Grammar" run into the skills the syllabus actually lists.

    uv run python database/reclassify_english.py \
        --transcriptions docs/questions/utme/english --apply

WHY ONLY THIS RUN. Most UTME English questions were classified from a printed direction that
says exactly what is being tested — "choose the option opposite in meaning", "the same vowel
sound" — and those mappings are right. One direction is not specific: the paper prints
"Basic Grammar - 10 questions", while the syllabus splits that ground into clause and
sentence patterns, word classes, mood and tense and concord, mechanics, and idiomatic usage.
All 139 went to clause and sentence patterns, and four of those five subtopics were left
holding nothing.

So this touches only the questions currently filed under clause and sentence patterns, and
leaves every direction-derived mapping alone. Questions the direction classified correctly
are not second-guessed by a weaker signal.

HOW. The stem is a gap; the options are the evidence. Four options that differ only in tense
and auxiliary are testing tense. Four that are the same verb with different particles are
testing idiom. Four pronouns are testing word classes. Four unrelated content words are
testing ordinary usage, not sentence structure. What is left — options that differ in the
order or shape of a clause — really is clause and sentence patterns, and stays.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from collections import Counter
from pathlib import Path

import asyncpg
import yaml

ROOT = Path(__file__).resolve().parent.parent

#: The subject this script is for. Always resolved together with the UTME examination,
#: because subject codes repeat across examinations.
SUBJECT_CODE = "ENG"

#: The one skill whose questions this script is willing to move.
SOURCE_SKILL = "ENG.B.3.i"

PRONOUNS = {
    "i", "me", "my", "mine", "myself", "you", "your", "yours", "yourself", "he", "him", "his",
    "himself", "she", "her", "hers", "herself", "it", "its", "it's", "itself", "we", "us",
    "our", "ours", "ourselves", "they", "them", "their", "theirs", "theirs'", "their's",
    "themselves", "who", "whom", "whose", "who's", "which", "that", "each other", "one another",
}
AUXILIARIES = re.compile(
    r"\b(?:would|could|should|shall|will|might|must|ought|have|has|had|been|being|was|were|"
    r"am|is|are|did|does|do)\b", re.I)
PARTICLES = re.compile(
    r"\b(?:up|off|out|in|on|down|over|through|about|around|away|back|by|for|into|to|with|"
    r"upon|at|after|against)\b$", re.I)
DEGREE = re.compile(r"\b(?:more|most|less|least)\b|(?:er|est)$", re.I)
QUESTION_TAG = re.compile(r"[?]\s*$")
PUNCTUATION_CHOICE = re.compile(r"^[^\w\s]+$|\b(?:comma|full stop|semi-?colon|apostrophe|"
                                r"hyphen|colon|question mark)\b", re.I)


def _words(option: str) -> list[str]:
    return re.findall(r"[A-Za-z']+", option.lower())


def decide(options: dict[str, str]) -> tuple[str, str] | None:
    """Which part of Lexis and Structure these four options are really testing."""
    values = [value.strip() for value in options.values() if value.strip()]
    if len(values) < 3:
        return None
    lowered = [value.lower() for value in values]
    heads = [_words(value)[0] if _words(value) else "" for value in values]

    if all(PUNCTUATION_CHOICE.search(value) for value in values):
        return "ENG.B.6.i", "every option is a punctuation mark, which is mechanics"

    if all(value in PRONOUNS for value in lowered):
        return "ENG.B.4.i", "every option is a pronoun, which is word classes and their functions"

    # A tag is an auxiliary and a pronoun — "didn't he", "isn't it" — and the question mark
    # usually sits at the end of the stem rather than inside the options.
    def is_tag(value: str) -> bool:
        parts = _words(value)
        return (
            bool(QUESTION_TAG.search(value))
            or (len(parts) == 2 and parts[-1] in PRONOUNS and bool(AUXILIARIES.match(parts[0])))
        )

    if sum(1 for value in values if is_tag(value)) >= 3:
        return "ENG.B.5.i", "the options are question tags, which is mood, tense and concord"

    # A pair of verb forms separated by a slash — "sells/have", "sell/has" — is a concord
    # question: which verb agrees with which subject.
    if sum(1 for value in values if "/" in value) >= 3:
        return (
            "ENG.B.5.i",
            "each option pairs two verb forms, which is agreement and concord",
        )

    # The same words in a different order test where a phrase may sit, not what tense it is
    # in: "is gifted not only" against "is only gifted" is correlative placement, and belongs
    # to clause and sentence patterns where it already is.
    shapes = {" ".join(sorted(_words(value))) for value in values}
    if len(shapes) == 1:
        return None

    # The same verb four times over, changed only by its particle: an idiom, not a structure.
    if (
        len(set(heads)) == 1
        and heads[0]
        and all(len(_words(v)) >= 2 for v in values)
        and sum(1 for value in values if PARTICLES.search(value.strip())) >= 3
    ):
        return (
            "ENG.B.7.i",
            f"every option is '{heads[0]}' with a different particle, which is idiomatic usage",
        )

    # Degrees of comparison: naughty, naughtier, naughtiest.
    if sum(1 for value in values if DEGREE.search(value)) >= 3 and len(set(heads)) <= 2:
        return "ENG.B.5.i", "the options are degrees of comparison, which is mood, tense and degree"

    # Tense and auxiliary: would have rushed, would not have rushed, could not have rushed.
    auxiliary_options = sum(1 for value in values if AUXILIARIES.search(value))
    if auxiliary_options >= 3 and len({" ".join(sorted(_words(v))) for v in values}) > 1:
        shared = set(_words(values[0]))
        for value in values[1:]:
            shared &= set(_words(value))
        if shared:
            return (
                "ENG.B.5.i",
                "the options are the same statement in different tenses or moods, which is "
                "mood, tense, aspect and concord",
            )

    # Four bare particles — off, over, up, out — complete a phrasal verb in the stem.
    if all(len(_words(value)) == 1 for value in values) and all(
        PARTICLES.search(value.strip()) for value in values
    ):
        return (
            "ENG.B.7.i",
            "the options are particles completing a phrasal verb, which is idiomatic usage",
        )

    # Four unrelated single words: this is vocabulary, not sentence structure.
    if all(len(_words(value)) == 1 for value in values) and len(set(lowered)) == len(values):
        return "ENG.B.7.i", "the options are four unrelated words, which is ordinary usage"

    return None


async def apply_to_database(
    updates: dict[str, tuple[str, str]], dsn: str | None
) -> tuple[int, int]:
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
        # Scope every write to ONE subject. The subject code is not unique on its own —
        # "ENG" is UTME's Use of English and also WAEC's English Language, and both sat 2011
        # and 2013 papers — so matching on exam_year and question_number alone reaches across
        # examinations. The foreign key caught it; the query should not have relied on that.
        subject_id = await conn.fetchval(
            """
            SELECT s.id FROM subjects s
            JOIN examinations e ON e.id = s.examination_id
            WHERE s.code = $1 AND e.short_name = 'UTME'
            """,
            SUBJECT_CODE,
        )
        if subject_id is None:
            raise SystemExit(f"no UTME subject with code {SUBJECT_CODE}")
        skills = {
            row["code"]: row["id"]
            for row in await conn.fetch(
                """
                SELECT ci.code, ci.id FROM curriculum_items ci
                JOIN syllabus_versions v ON v.id = ci.syllabus_version_id
                WHERE ci.item_type = 'skill' AND v.subject_id = $1
                """,
                subject_id,
            )
        }
        changed = skipped = 0
        transaction = conn.transaction()
        await transaction.start()
        for key, (skill_code, reason) in updates.items():
            year, number = key.split(":")
            target = skills.get(skill_code)
            if target is None:
                continue
            result = await conn.execute(
                """
                UPDATE question_classifications c
                   SET curriculum_item_id = $1, classification_reason = $2,
                       proposed_by = 'model', confidence = 0.6
                  FROM questions q
                 WHERE q.id = c.question_id
                   AND c.classification_role = 'primary'
                   AND c.review_status = 'draft'
                   AND q.subject_id = $5
                   AND q.exam_year = $3 AND q.question_number = $4
                   AND c.curriculum_item_id <> $1
                """,
                target, reason, int(year), number, subject_id,
            )
            if result.endswith(" 0"):
                skipped += 1
            else:
                changed += 1
        await transaction.commit()
        return changed, skipped
    finally:
        await conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transcriptions", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--database-url", default=None)
    args = parser.parse_args()

    folder = Path(args.transcriptions).resolve()
    moved: Counter[str] = Counter()
    considered = 0
    updates: dict[str, tuple[str, str]] = {}

    for path in sorted(folder.glob("transcription_*.yaml")):
        document = yaml.safe_load(path.read_text())
        year = document["source"]["exam_year"]
        for question in document["questions"]:
            if question.get("proposed_skill") != SOURCE_SKILL:
                continue
            considered += 1
            decision = decide(question.get("options") or {})
            if decision is None:
                moved["ENG.B.3.i (unchanged)"] += 1
                continue
            skill, reason = decision
            moved[skill] += 1
            question["proposed_skill"] = skill
            question["skill_reason"] = (
                f"Read from the options: {reason}. The paper calls this whole run "
                '"Basic Grammar", which the syllabus divides further.'
            )
            updates[f"{year}:{question['number']}"] = (skill, question["skill_reason"])
        if args.apply:
            header = "".join(
                line + "\n" for line in path.read_text().splitlines() if line.startswith("#")
            )
            path.write_text(
                header + yaml.dump(document, sort_keys=False, allow_unicode=True, width=100)
            )

    print(f"{considered} questions were filed under {SOURCE_SKILL}. They divide as:")
    for skill, count in moved.most_common():
        print(f"  {count:4d}  {skill}")

    if args.apply:
        changed, skipped = asyncio.run(apply_to_database(updates, args.database_url))
        print(f"\nDatabase: {changed} re-pointed, {skipped} already correct or approved.")
    else:
        print("\nDry run; pass --apply to write the change.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
