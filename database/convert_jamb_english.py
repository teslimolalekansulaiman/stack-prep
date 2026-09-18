#!/usr/bin/env python3
"""Turn the JAMB Use of English past-questions compilation into transcription YAML.

    uv run python database/convert_jamb_english.py \
        --pdf docs/questions/utme/english/JAMB-USE-OF-ENGLISH-PAST-QUESTIONS.pdf \
        --out docs/questions/utme/english

One file per year, in the format database/load_questions.py already reads.

Why a parser and not a transcription. The WAEC papers were scans with no text layer, so
every question had to be read off page images by hand. This PDF has a real text layer, so
the questions can be extracted exactly as printed — no re-keying, and no chance of a
transcription slip. What the parser must not do is paper over the source: anything it
cannot read cleanly is rejected with a reason rather than guessed at, and the rejections
are printed and written to the YAML header.

Three things about the source shape the code:

  * Two columns. pdftotext -layout interleaves them, so the text is rebuilt from word
    bounding boxes: words left of the gutter first, then the right column. The only text
    that crosses the gutter is the centred footer, which is dropped.

  * The paper states its own directions, with question ranges — "In each of question 36 to
    50, choose the option opposite in meaning...". Those drive the skill mapping, so a
    question is classified by what the examiner said it tests, not by our reading of it.
    Comprehension questions carry no such direction and are mapped from the stem's own
    wording; those mappings are the weakest and are flagged as such.

  * It ships an answer key per year. The key is a third party's (toppers.com.ng), not
    JAMB's marking scheme, and it has gaps ("71. NO ANSWER") and OCR noise, so answers are
    written as `published_key`: better than a guess, still not something a student should
    see before a person checks it. The database refuses to approve either way.
"""

# ruff: noqa: RUF001  (the dashes and curly quotes here are the ones the PDF prints)
from __future__ import annotations

import argparse
import html
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
GUTTER_X = 300.0          # page is 595pt wide; the columns meet here
LINE_BUCKET = 4.0         # words within this many points of each other share a line
OPTION_KEYS = ("A", "B", "C", "D")

YEAR_RE = re.compile(r"^(\d{4})\s+JAMB\s+USE\s+OF")
# Case-SENSITIVE and anchored to a short line: the key's heading is printed in capitals,
# while "answer to this new battle" is ordinary prose that would otherwise cut a year in
# half — which is exactly what it did to 2018.
ANSWER_HEADER_RE = re.compile(r"^(ANSWERS|ANSWER\s+KEYS?)\b[\s:.]*$")
# "1." or "1)" at the start of a line, and the lowercase-letter option style some years use.
QUESTION_RE = re.compile(r"^(\d{1,3})\s*[.)]\s*(.*)$")
OPTION_RE = re.compile(r"^[(\[]?([A-Da-d])[).\]]\s*(.*)$")
PASSAGE_RE = re.compile(r"^PASSAGE\s+([IVXAB]+|ll|l)\b", re.I)
FOOTER_RE = re.compile(r"toppers\.com\.ng|NOT FOR SALE", re.I)
# "In each of question 36 to 50, ..." / "In each of questions, 92 to 94, ..."
RANGE_RE = re.compile(r"questions?,?\s+(\d{1,3})\s*(?:to|-|–)\s*(\d{1,3})", re.I)
GAPS_RE = re.compile(r"gaps?\s+numbered\s+(\d{1,3})\s*(?:to|-|–)\s*(\d{1,3})", re.I)
# Only some years number the cloze gaps in the direction. The rest just say "the passage
# below has gaps", so the range has to be read off the gaps themselves.
CLOZE_DIRECTION_RE = re.compile(
    r"passage below has gaps|gaps?\s+numbered|option for each gap", re.I)
#: A gap printed in the prose: dots or dashes, a number, then a bracketed option list.
GAP_HINT_RE = re.compile(r"[.…]{2,}\s*\d{1,3}\s*[.…]{0,}\s*[\[(]\s*[A-Da-d][.) ]")
KEY_ENTRY_RE = re.compile(r"(\d{1,3})\s*[.)]\s*([A-D])\b")
NO_ANSWER_RE = re.compile(r"(\d{1,3})\s*[.)]\s*NO\s+ANSWER", re.I)

#: A printed direction, the skill it maps to, and why. Matched against the direction text
#: the paper prints above a run of questions, so the mapping is the examiner's own words.
DIRECTION_RULES: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"opposite in meaning", re.I), "ENG.B.2.i",
     "Printed direction asks for the option opposite in meaning."),
    (re.compile(r"nearest in meaning|same meaning|closest in meaning", re.I), "ENG.B.1.i",
     "Printed direction asks for the option nearest in meaning."),
    (re.compile(r"interpretation|best explains the information|explains? the information", re.I),
     "ENG.B.3.ii", "Printed direction asks what information the sentence conveys."),
    # A cloze direction, for the years that print the gaps as a numbered list rather than
    # inline: those questions reach the classifier as ordinary ones.
    (re.compile(r"passage below has gaps", re.I), "ENG.A.6.i",
     "Printed direction is the cloze passage."),
    (re.compile(r"best completes? the gap", re.I), "ENG.B.3.i",
     "Printed direction is the Basic Grammar run: choose what completes the gap."),
    (re.compile(r"vowel sound", re.I), "ENG.C.1.i",
     "Printed direction asks for the same vowel sound."),
    (re.compile(r"consonant sound", re.I), "ENG.C.2.i",
     "Printed direction asks for the same consonant sound."),
    (re.compile(r"rhymes? with", re.I), "ENG.C.3.i",
     "Printed direction asks which option rhymes with the given word."),
    (re.compile(r"stress (?:pattern|item)|stressed syllables?", re.I), "ENG.C.4.i",
     "Printed direction asks for the stress pattern."),
    # Some years drop the word "vowel" or "consonant" and just say "the same sound as the
    # one represented by the letter(s) underlined". That is still a pronunciation item, so
    # it maps to the pronunciation skill rather than being left to the comprehension
    # default — but the direction does not say which, and the reason says so.
    (re.compile(r"same sound as the one represented", re.I), "ENG.C.3.i",
     "Printed direction asks for the same sound as the underlined letters; it does not say "
     "whether the sound is a vowel or a consonant."),
    (re.compile(r"option to which the given sentence relates", re.I), "ENG.C.5.i",
     "Printed direction is the emphatic-stress format: which question the sentence answers."),
    # 2010 prints "has the emphatic." with the noun missing, so match the adjective alone.
    # This rule sits after the stress-pattern one, which also mentions capital letters.
    (re.compile(r"emphatic", re.I), "ENG.C.5.i",
     "Printed direction is about emphatic stress in an utterance."),
]

#: Comprehension questions carry no direction of their own, so they are mapped from the
#: stem. These are the weakest mappings in the file and are counted separately.
STEM_RULES: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"\b(means?|as used in the passage|expression|word|phrase|refers? to)\b", re.I),
     "ENG.A.2.i", "Stem asks what a word or expression means in the passage."),
    (re.compile(r"\b(attitude|mood|tone|posture|intention|writer'?s?)\b", re.I),
     "ENG.A.3.i", "Stem asks about the writer's attitude, mood or intention."),
    (re.compile(r"\b(deduced?|inferred?|conclude|implies|suggests)\b", re.I),
     "ENG.A.3.i", "Stem asks for a deduction or inference."),
]
COMPREHENSION_DEFAULT = ("ENG.A.1.i", "Comprehension question on a set passage.")
CLOZE_SKILL = ("ENG.A.6.i", "Gap in the cloze passage printed with the year's paper.")

#: Not an English question at all: every JAMB paper opens by asking which paper type the
#: candidate holds. It tests nothing and must not enter the bank.
PAPER_TYPE_RE = re.compile(r"which\s+use\s+of\s+english\s+paper\s+type", re.I)


@dataclass
class Line:
    page: int
    text: str


@dataclass
class Question:
    number: int
    page: int
    stem: str = ""
    options: dict[str, str] = field(default_factory=dict)
    instruction: str | None = None
    section: str | None = None
    passage_ref: str | None = None
    skill: str | None = None
    skill_reason: str = ""
    weak_mapping: bool = False


def read_lines(pdf: Path) -> list[Line]:
    """Page text in true reading order: left column top-to-bottom, then right column."""
    xml = subprocess.run(
        ["pdftotext", "-bbox", str(pdf), "-"],
        check=True, capture_output=True, text=True, errors="replace",
    ).stdout
    pages = re.findall(r'<page width="[\d.]+" height="[\d.]+">(.*?)</page>', xml, re.S)
    word_re = re.compile(
        r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>',
        re.S,
    )
    out: list[Line] = []
    for page_number, body in enumerate(pages, 1):
        words = [
            (float(x0), float(y0), float(x1), html.unescape(text))
            for x0, y0, x1, _y1, text in word_re.findall(body)
        ]
        for low, high in ((0.0, GUTTER_X), (GUTTER_X, 1e9)):
            column = [w for w in words if low <= (w[0] + w[2]) / 2 < high]
            rows: dict[int, list[tuple[float, str]]] = {}
            for x0, y0, _x1, text in column:
                rows.setdefault(round(y0 / LINE_BUCKET), []).append((x0, text))
            for key in sorted(rows):
                text = " ".join(t for _, t in sorted(rows[key])).strip()
                if text and not FOOTER_RE.search(text):
                    out.append(Line(page_number, text))
    return out


def split_years(lines: list[Line]) -> list[tuple[int, list[Line]]]:
    starts = [(i, int(m.group(1))) for i, line in enumerate(lines)
              if (m := YEAR_RE.match(line.text))]
    blocks = []
    for position, (index, year) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
        blocks.append((year, lines[index:end]))
    return blocks


def parse_answer_key(lines: list[Line]) -> tuple[dict[int, str], set[int]]:
    """The year's printed key, plus the numbers it explicitly has no answer for."""
    key: dict[int, str] = {}
    blank: set[int] = set()
    for line in lines:
        for number in NO_ANSWER_RE.findall(line.text):
            blank.add(int(number))
        for number, letter in KEY_ENTRY_RE.findall(line.text):
            value = int(number)
            if value not in blank:
                key[value] = letter
    return key, blank


#: The last option on a page has nothing after it to stop at, so it swallows the next
#: direction, the next passage, or the rest of the cloze sentence. These are the things that
#: can only be the start of something else.
OPTION_END_RE = re.compile(
    r"\]|\bIn each of\b|\bChoose the (?:option|most|word)\b|\bSelect the option\b|"
    r"\bPASSAGE\b|\bThe passage below\b|\bFrom the words\b", re.I)

#: A run of shouted words is the paper's own section heading — "LEXIS, STRUCTURE AND ORAL
#: FORMS" — set between the last option of one section and the first question of the next.
#: It is matched case-sensitively, because the same words in ordinary case are ordinary
#: words, and an option that legitimately shouts one word is left alone.
HEADING_RE = re.compile(r"\b[A-Z]{3,}(?:[ ,]+[A-Z]{2,})+")


def trim_option(text: str) -> str:
    """Cut an option at the point where the next thing on the page begins."""
    for pattern in (OPTION_END_RE, HEADING_RE):
        match = pattern.search(text)
        if match and match.start() > 0:
            text = text[:match.start()]
    return clean(text)


def clean(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    text = text.replace("‘", "'").replace("’", "'").replace("“", '"').replace("”", '"')
    return text.strip(" .;:")


def parse_cloze(lines: list[Line], first: int | None,
                last: int | None) -> tuple[list[Question], str]:
    """Gaps numbered inside the passage prose.

    Every year prints these differently: `...16... [A. one B. two]`, `……16…. [A one, B two]`,
    `..... 11 (a) one (b) two .....`. Rather than one regex per year, the gap markers and
    the option markers are found separately and then walked in order, so any mixture of
    brackets, parentheses, dots, dashes and letter case comes out the same.
    """
    body = " ".join(line.text for line in lines)
    page_of: dict[int, int] = {}
    for line in lines:
        for number in re.findall(r"(?:[-.…]\s*){1,10}(\d{1,3})\b", line.text):
            page_of.setdefault(int(number), line.page)

    gap_re = re.compile(r"(?:[-.…]\s*){1,12}(\d{1,3})\s*(?:[-.…]\s*)*")
    option_re = re.compile(r"[(\[]\s*([A-Da-d])\s*[).\]]\s*|(?:(?<=\s)|^)([A-Da-d])[.)]\s+")
    gaps = [(m.start(), m.end(), int(m.group(1))) for m in gap_re.finditer(body)]
    options = [(m.start(), m.end(), (m.group(1) or m.group(2)).upper())
               for m in option_re.finditer(body)]

    questions: list[Question] = []
    for position, (_start, gap_end, number) in enumerate(gaps):
        if first is not None and not first <= number <= last:
            continue
        if not 1 <= number <= 100:
            continue
        limit = gaps[position + 1][0] if position + 1 < len(gaps) else len(body)
        run = [o for o in options if gap_end <= o[0] < limit]
        wanted = ["A", "B", "C", "D"]
        picked: list[tuple[int, int, str]] = []
        for marker in run:
            if wanted and marker[2] == wanted[0]:
                picked.append(marker)
                wanted.pop(0)
        if len(picked) != 4:
            continue
        found: dict[str, str] = {}
        for index, (_s, text_start, letter) in enumerate(picked):
            text_end = picked[index + 1][0] if index + 1 < len(picked) else limit
            found[letter] = clean(re.split(r"[-.…]{2,}", body[text_start:text_end])[0])
        if any(not value for value in found.values()):
            continue
        questions.append(Question(
            number=number,
            page=page_of.get(number, lines[0].page if lines else 1),
            stem=f"Gap {number} in the cloze passage.",
            options=found,
            skill=CLOZE_SKILL[0],
            skill_reason=CLOZE_SKILL[1],
        ))

    seen: set[int] = set()
    unique = []
    for question in questions:
        if question.number not in seen:
            seen.add(question.number)
            unique.append(question)
    passage = re.sub(r"\s+", " ", body).strip()
    return unique, passage


def classify(question: Question) -> None:
    if question.skill:
        return
    haystack = question.instruction or ""
    for pattern, skill, reason in DIRECTION_RULES:
        if pattern.search(haystack):
            question.skill, question.skill_reason = skill, reason
            return
    for pattern, skill, reason in STEM_RULES:
        if pattern.search(question.stem):
            question.skill, question.skill_reason = skill, reason
            question.weak_mapping = True
            return
    question.skill, question.skill_reason = COMPREHENSION_DEFAULT
    question.weak_mapping = True


def rejoin_split_starts(body: list[Line], skip: set[int]) -> int:
    """Split lines where a question begins in the middle of the one before it.

    QUESTION_RE only matches a number at the start of a line, which is nearly always where a
    question number is. Nearly: seven times across nine papers the source sets the last option
    and the next question's number on one line —

        D. useless 62 The lamb is a little feeble animal

    — and a start that is never found is a question that is never extracted. The number then
    lands inside option D, which is the visible half of the damage; the invisible half is that
    question 62 is gone from the paper altogether. Six of the seven were.

    A number in the middle of a line is not evidence of anything on its own: this source has
    numbers in prose, in dates and in citations. So this does not go looking for numbers. It
    takes the ascending run that `question_starts` already trusts, finds the numbers MISSING
    from it, and looks for exactly those, only inside the span where they would have to be.
    A number that is both absent from the run and sitting where the run says it belongs is a
    question, not prose.

    The same repair covers a second way the source loses a question: printing the number at
    the start of its own line with no full stop after it — "62 The lamb is a little feeble
    animal" — which QUESTION_RE requires and therefore skips. There is nothing to split
    there; the separator is put back instead.

    Returns how many it split, so the caller can say so rather than fixing things silently.
    """
    chain = question_starts(body, skip)
    if len(chain) < 2:
        return 0

    repaired = 0
    # Walk from the end so inserting a line never shifts an index still to be examined.
    for position in range(len(chain) - 2, -1, -1):
        index, number, _ = chain[position]
        next_index, next_number, _ = chain[position + 1]
        for missing in range(next_number - 1, number, -1):
            for line_index in range(next_index - 1, index - 1, -1):
                if line_index in skip:
                    continue
                line = body[line_index]
                # A printed direction names question numbers on purpose — "gaps numbered 16
                # to 25", "In each of questions 36 to 50" — and splitting one of those turns
                # the second half of the direction into a question. 2012 gained exactly that:
                # a question 25 whose stem was "Immediately following each gap...", and an
                # eight-word passage to go with it. Directions are never split.
                if (
                    GAPS_RE.search(line.text)
                    or RANGE_RE.search(line.text)
                    or re.search(r"\bIn each of\b|\bThe passage below\b", line.text, re.I)
                ):
                    continue
                # The number, then a separator, then something that reads like the start of a
                # sentence. Not preceded by a digit or a decimal point, so "1.62" and page
                # ranges do not match.
                match = re.search(
                    rf"(?<![\d.]){missing}(?:\s*[.)])?\s+(?=[A-Z\"'(])", line.text
                )
                if not match:
                    continue
                head = line.text[: match.start()].rstrip()
                # The far end of a range — "gaps numbered 16 to 25. Immediately following..."
                # — is a direction, not a question, even when the direction has wrapped and
                # this line no longer carries the words that would say so. What identifies it
                # is the connector immediately before the number.
                if re.search(r"\b(?:to|through|and|or)$|[-–]$", head, re.I):
                    continue
                tail = f"{missing}. {line.text[match.end():].lstrip()}"
                if not tail.strip():
                    continue
                if head:
                    body[line_index] = Line(page=line.page, text=head)
                    body.insert(line_index + 1, Line(page=line.page, text=tail))
                else:
                    # The number already starts its own line; it was missed only because the
                    # source printed it with no full stop after it, which QUESTION_RE requires.
                    # Nothing needs splitting — the separator needs putting back.
                    body[line_index] = Line(page=line.page, text=tail)
                repaired += 1
                break
    return repaired


def question_starts(body: list[Line], skip: set[int]) -> list[tuple[int, int, str]]:
    """Line indexes that begin a question.

    A number printed at the start of a line is not proof of a question: the source has
    numbers in prose, in citations and in the answer key. What is reliable is that question
    numbers ascend. So every candidate is collected and the longest strictly ascending run
    is kept — one stray number cannot then derail the rest of the paper, which is exactly
    what a straight sequential scan did.
    """
    candidates: list[tuple[int, int, str]] = []
    for index, line in enumerate(body):
        if index in skip:
            continue
        match = QUESTION_RE.match(line.text)
        if match and 1 <= int(match.group(1)) <= 100:
            candidates.append((index, int(match.group(1)), match.group(2)))
    if not candidates:
        return []
    best = [1] * len(candidates)
    previous = [-1] * len(candidates)
    for i in range(len(candidates)):
        for j in range(i):
            if candidates[j][1] < candidates[i][1] and best[j] + 1 > best[i]:
                best[i], previous[i] = best[j] + 1, j
    tail = max(range(len(candidates)), key=lambda i: best[i])
    chain = []
    while tail != -1:
        chain.append(candidates[tail])
        tail = previous[tail]
    return list(reversed(chain))


def paragraphs(body: list[Line]) -> list[tuple[int, str]]:
    """Consecutive lines joined until something structural starts.

    Directions wrap over three or four short lines in this layout, so matching them line by
    line finds almost nothing — the question range and the verb usually land on different
    lines.
    """
    out: list[tuple[int, str]] = []
    start, buffer = 0, []
    for index, line in enumerate(body):
        text = line.text.strip()
        structural = (QUESTION_RE.match(text) or PASSAGE_RE.match(text)
                      or OPTION_RE.match(text) or not text)
        if structural:
            if buffer:
                out.append((start, " ".join(buffer)))
                buffer = []
            continue
        if not buffer:
            start = index
        buffer.append(text)
    if buffer:
        out.append((start, " ".join(buffer)))
    return out


def directions(body: list[Line]) -> tuple[dict[int, str], list[tuple[int, str]]]:
    """Printed directions, keyed by the question numbers they name."""
    by_number: dict[int, str] = {}
    positional: list[tuple[int, str]] = []
    for index, text in paragraphs(body):
        if len(text) < 25 or not re.search(r"choose|select|pick", text, re.I):
            continue
        # A direction can be the tail of a paragraph that began with an option, so keep
        # only from the instruction's own opening.
        trimmed = re.search(r"(In each of.*|In the following.*|From the words.*|"
                            r"Choose the (?:option|word|most appropriate|most suitable).*|"
                            r"Select the option.*|"
                            r"The passage below.*|Fill each gap.*)", text, re.I)
        if not trimmed:
            continue
        text = clean(trimmed.group(1))
        match = RANGE_RE.search(text)
        if match:
            first, last = int(match.group(1)), int(match.group(2))
            if 0 < first <= last <= 100:
                for number in range(first, last + 1):
                    by_number[number] = text
        positional.append((index, text))
    return by_number, positional


def parse_year(year: int, lines: list[Line]) -> tuple[dict, list[str]]:
    rejections: list[str] = []
    split = next((i for i, line in enumerate(lines) if ANSWER_HEADER_RE.match(line.text)),
                 len(lines))
    body, key_lines = lines[:split], lines[split:]
    key, blank = parse_answer_key(key_lines)
    instruction_for, positional = directions(body)

    # ---- the cloze passage, whose gaps are numbered inside the prose ------------------
    passages: list[dict] = []
    cloze_questions: list[Question] = []
    cloze_numbers: set[int] = set()
    skip: set[int] = set()
    paragraph_list = paragraphs(body)
    gap_match = next(((i, text) for i, text in paragraph_list
                      if CLOZE_DIRECTION_RE.search(text)), None)
    if gap_match is None and any(GAP_HINT_RE.search(item.text) for item in body):
        # 2013 prints its cloze with no direction at all — just gaps in the prose. Scanning
        # the whole year finds them; the contiguous-run filter below throws away numbers
        # that merely look like gaps.
        gap_match = (0, "")
    if gap_match:
        index, direction_text = gap_match
        printed = GAPS_RE.search(direction_text)
        # The cloze runs until the next numbered direction, whatever the year's wording.
        stop = next((i for i, text in paragraph_list
                     if i > index and RANGE_RE.search(text)
                     and re.search(r"choose|select", text, re.I)), len(body))
        if printed:
            first, last = int(printed.group(1)), int(printed.group(2))
            stop = min(stop, next(
                (i for i, item in enumerate(body[index:], index)
                 if (m := QUESTION_RE.match(item.text)) and int(m.group(1)) > last), len(body)))
        else:
            first, last = None, None
        cloze_questions, passage_text = parse_cloze(body[index:stop], first, last)
        if not printed and cloze_questions:
            # With no printed range, a number in ordinary prose can look like a gap. Real
            # gaps run consecutively, so keep the longest near-consecutive block and drop
            # strays rather than inventing questions from them.
            numbers = sorted(q.number for q in cloze_questions)
            best: list[int] = []
            run = [numbers[0]]
            for value in numbers[1:]:
                if value - run[-1] <= 2:
                    run.append(value)
                else:
                    best, run = max(best, run, key=len), [value]
            best = max(best, run, key=len)
            if len(best) < 4:
                best = []
            cloze_questions = [q for q in cloze_questions if q.number in set(best)]
            cloze_numbers = {q.number for q in cloze_questions}
            first, last = (min(best), max(best)) if best else (None, None)
        cloze_numbers = {q.number for q in cloze_questions}
        pid = f"cloze_{year}"
        if cloze_questions:
            passages.append({"id": pid, "label": "CLOZE PASSAGE", "text": passage_text})
            for item in cloze_questions:
                item.passage_ref = pid
                item.instruction = clean(direction_text)
                item.section = "Cloze passage"
        # Whatever the gap parser handled must not be read again as ordinary questions;
        # what it missed is left in place so the numbered-list style below can catch it.
        for i in range(index, stop):
            candidate = QUESTION_RE.match(body[i].text)
            if candidate and int(candidate.group(1)) in cloze_numbers:
                skip.add(i)
        # Only the years that print "gaps numbered 16 to 25" tell us what should be there;
        # where the range was inferred, a missing number is not evidence of anything.
        if printed:
            for number in range(first, last + 1):
                if number not in cloze_numbers:
                    rejections.append(
                        f"{year} Q{number}: printed as a cloze gap but no options found inline")

    # ---- ordinary questions ----------------------------------------------------------
    # Repair lines that hold the end of one question and the start of the next before the
    # starts are read, so the repaired starts are the ones everything else is built from.
    repaired = rejoin_split_starts(body, skip)
    if repaired:
        rejections.append(
            f"{year}: {repaired} question(s) began mid-line, inside the previous question's "
            "last option, and were split out"
        )
    starts = question_starts(body, skip)
    questions: list[Question] = []
    spans: list[tuple[int, int]] = []
    for position, (index, number, remainder) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(body)
        segment = body[index:end]
        question = Question(number=number, page=segment[0].page)
        option_key: str | None = None

        # Some years print a cloze as a numbered list: "11. A. insignificant".
        head = OPTION_RE.match(remainder)
        if head and head.group(1).upper() == "A":
            question.options["A"] = clean(head.group(2))
            option_key = "A"
            question.stem = f"Gap {number} in the cloze passage."
            question.skill, question.skill_reason = CLOZE_SKILL
        else:
            question.stem = clean(remainder)

        consumed = 1
        for line in segment[1:]:
            text = line.text.strip()
            if PASSAGE_RE.match(text) or GAPS_RE.search(text):
                break
            consumed += 1
            if not text:
                continue
            option = OPTION_RE.match(text)
            if option and option.group(1).upper() in OPTION_KEYS:
                letter = option.group(1).upper()
                if letter in question.options and letter == "A" and option_key == "D":
                    break
                option_key = letter
                question.options[letter] = clean(option.group(2))
                continue
            if option_key:
                question.options[option_key] = clean(
                    f"{question.options[option_key]} {text}")
            elif len(question.stem) < 400:
                question.stem = clean(f"{question.stem} {text}")

        # Options printed inline inside the sentence: "... [A. one B. two C. three D. four]".
        if len(question.options) < 4:
            inline = re.search(r"\[(.*?)\]", question.stem, re.S)
            if inline:
                parts = re.split(r"\b([A-D])[.)]?\s+", inline.group(1))
                found = {}
                for i in range(1, len(parts) - 1, 2):
                    found[parts[i]] = clean(parts[i + 1])
                if len(found) == 4:
                    question.options = found
                    question.stem = clean(question.stem.replace(inline.group(0), " ...... "))

        question.instruction = instruction_for.get(number)
        if question.instruction is None:
            earlier = [text for i, text in positional if i < index]
            question.instruction = earlier[-1] if earlier else None
        spans.append((index, index + consumed))
        questions.append(question)

    questions.extend(cloze_questions)
    questions.sort(key=lambda q: q.number)
    deduped: dict[int, Question] = {}
    for question in questions:
        existing = deduped.get(question.number)
        if existing is None or (len(existing.options) < 4 <= len(question.options)):
            deduped[question.number] = question
    questions = sorted(deduped.values(), key=lambda q: q.number)

    # ---- passages: prose that belongs to no question ---------------------------------
    owned: set[int] = set()
    for first, last in spans:
        owned.update(range(first, last))
    current: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        nonlocal current, buffer
        if current and buffer:
            passages.append({"id": current, "label": current.split("_", 2)[-1].upper(),
                             "text": clean(" ".join(buffer))})
        current, buffer = None, []

    for index, line in enumerate(body):
        text = line.text.strip()
        if PASSAGE_RE.match(text):
            flush()
            current = f"passage_{year}_" + re.sub(r"\W+", "_", text.lower()).strip("_")
            continue
        if index in owned or index in skip or not text:
            continue
        if current and not GAPS_RE.search(text) and not RANGE_RE.search(text):
            buffer.append(text)
    flush()

    # Attach each question to the passage printed above it.
    passage_at: list[tuple[int, str]] = []
    for index, line in enumerate(body):
        if PASSAGE_RE.match(line.text):
            passage_at.append(
                (index, f"passage_{year}_" + re.sub(r"\W+", "_", line.text.lower()).strip("_")))
    by_index = {index: number for index, number, _r in
                [(i, n, r) for i, n, r in starts]}
    for question in questions:
        if question.passage_ref:
            continue
        index = next((i for i, n in by_index.items() if n == question.number), None)
        if index is None:
            continue
        earlier = [pid for pos, pid in passage_at if pos < index]
        if earlier and question.number <= 25:
            question.passage_ref = earlier[-1]

    prepared: list[dict] = []
    for question in questions:
        if PAPER_TYPE_RE.search(question.stem):
            rejections.append(
                f"{year} Q{question.number}: paper-type question, not an English item")
            continue
        missing = [k for k in OPTION_KEYS if not question.options.get(k)]
        if missing:
            rejections.append(
                f"{year} Q{question.number}: option(s) {','.join(missing)} missing in the source")
            continue
        if not question.stem:
            rejections.append(f"{year} Q{question.number}: empty stem")
            continue
        if question.number in blank:
            rejections.append(f"{year} Q{question.number}: the printed key says NO ANSWER")
            continue
        answer = key.get(question.number)
        if not answer:
            rejections.append(f"{year} Q{question.number}: no entry in the printed key")
            continue
        classify(question)
        trimmed = {key: trim_option(question.options[key]) for key in OPTION_KEYS}
        overlong = [key for key, value in trimmed.items() if len(value) > 180]
        if overlong:
            rejections.append(
                f"{year} Q{question.number}: option {','.join(overlong)} runs into the "
                "following text and cannot be read cleanly")
            continue
        # A number sitting inside an option, with a sentence after it, is the page bleeding
        # in. rejoin_split_starts repairs this where the number is the next question's, which
        # is nearly every case; what is left is a stray the parser cannot attribute, and an
        # option we cannot read is a question we should not ask.
        unreadable = [
            key for key, value in trimmed.items()
            if re.search(r"\s\d{1,3}\s+[A-Z]", value)
        ]
        if unreadable:
            rejections.append(
                f"{year} Q{question.number}: option {','.join(unreadable)} has text from "
                "elsewhere on the page inside it and cannot be read cleanly")
            continue
        if any(not value for value in trimmed.values()):
            rejections.append(
                f"{year} Q{question.number}: an option is empty once the following text is "
                "trimmed off")
            continue
        prepared.append({
            "number": question.number,
            "page": question.page,
            "section": question.section,
            "instruction": question.instruction,
            "stem": question.stem,
            "options": trimmed,
            "proposed_answer": answer,
            "answer_confidence": "medium",
            "proposed_skill": question.skill,
            "skill_reason": question.skill_reason
            + (" Mapped from the stem: no direction is printed for comprehension items."
               if question.weak_mapping else ""),
            "passage_ref": question.passage_ref,
        })

    used = {q["passage_ref"] for q in prepared if q["passage_ref"]}
    seen: set[str] = set()
    unique_passages = []
    for passage in passages:
        if passage["id"] in used and passage["id"] not in seen and passage["text"]:
            seen.add(passage["id"])
            unique_passages.append(passage)
    document = {
        "format_version": 1,
        "source": {
            "file": "docs/questions/utme/english/JAMB-USE-OF-ENGLISH-PAST-QUESTIONS.pdf",
            "exam_year": year,
            "paper_label": f"UTME {year} Use of English (objective)",
            "paper_code": f"UTME-{year}-ENG",
            "question_count": max((q["number"] for q in prepared), default=0),
            # The compilation prints a key for every year. It is not JAMB's marking scheme,
            # so it loads as published_key: a real source, still not a verified answer.
            "answer_source": "published_key",
        },
        "passages": unique_passages,
        "questions": prepared,
    }
    return document, rejections


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--out", required=True, help="Directory for the per-year YAML")
    parser.add_argument("--year", type=int, action="append",
                        help="Only convert these years (repeatable)")
    args = parser.parse_args()

    pdf = Path(args.pdf).resolve()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    lines = read_lines(pdf)

    totals = Counter()
    all_rejections: list[str] = []
    for year, block in split_years(lines):
        if args.year and year not in args.year:
            continue
        document, rejections = parse_year(year, block)
        all_rejections.extend(rejections)
        skills = Counter(q["proposed_skill"] for q in document["questions"])
        weak = sum(1 for q in document["questions"]
                   if "Mapped from the stem" in q["skill_reason"])
        header = (
            f"# UTME {year}, Use of English — extracted from the text layer of\n"
            f"# {document['source']['file']}.\n#\n"
            f"# {len(document['questions'])} questions kept, {len(rejections)} rejected.\n"
            "# Answers come from the key printed with the paper, which is a compiler's, not\n"
            "# JAMB's: they load as `published_key` and still need a person to check them.\n"
            "# Skill mappings follow the paper's own printed directions where it prints one;\n"
            f"# {weak} comprehension items had none and were mapped from the stem instead.\n"
        )
        path = out / f"transcription_{year}.yaml"
        path.write_text(header + yaml.dump(
            document, sort_keys=False, allow_unicode=True, width=100))
        totals[year] = len(document["questions"])
        print(f"{year}: {len(document['questions']):3d} questions, "
              f"{len(rejections):2d} rejected, {len(document['passages'])} passages, "
              f"skills {dict(skills)}")

    print(f"\nTotal questions: {sum(totals.values())}")
    if all_rejections:
        print(f"Rejected {len(all_rejections)}:")
        for reason in all_rejections:
            print(f"  - {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
