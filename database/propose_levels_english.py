#!/usr/bin/env python3
"""Propose a difficulty level for every UTME Use of English question.

    uv run python database/propose_levels_english.py \
        --transcriptions docs/questions/utme/english

WHY A RULE AND NOT 754 JUDGEMENTS. The WAEC papers were levelled one question at a time,
each with its own reason, because there were 200 of them and each reason was worth writing.
At 754 the same approach would produce 754 sentences nobody reads. A stated rule is more
useful and more honest: a reviewer who disagrees can disagree with the rule and re-level a
whole class of questions at once, instead of arguing with individual guesses.

Everything here is `level_confidence: low` and loads as `level_source: model_proposed`. That
is not modesty — it is accurate. None of this is a judgement about a question; it is an
estimate from features a program can measure, and the database will not let any of it be
approved without a person.

THE RULE, in two parts.

First, a base level per skill, taken from what the task actually demands:

    locate a stated point               2   the answer is in the passage, in words
    cloze gap                           3   context plus a lexical choice
    synonyms, antonyms, grammar         3   one discrimination, no reading
    interpret a sentence                3
    vowel, consonant, rhyme, stress     3   learned knowledge, not reasoning
    meaning in context                  4   the passage changes the word's sense
    inference, writer's attitude        4   nothing in the text says it outright
    emphatic stress                     4   requires hearing focus, not just sound

Second, adjustments from measurable features, each worth one step:

  * Lexical rarity, for items whose answer is a single word. A long, uncommon answer is
    harder than a short, everyday one. Rarity is approximated by "not in a list of common
    English words, and at least eight letters" — a crude proxy for a frequency corpus we do
    not have offline, and the reason every level here is low confidence.
  * Reading load, for comprehension, cloze and sentence items. Long options mean the work is
    reading and holding four alternatives, not knowing a word.
  * Syllable count, for the oral items. A monosyllable is an easier stress or sound
    judgement than a five-syllable word.

Levels are clamped to 1..5. The file it writes is the same shape the question loader already
reads with --levels.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

import yaml

#: Enough of the everyday vocabulary to tell "weakened" from "invigorated". A real frequency
#: list would be better; this is deliberately small and its limits are why confidence is low.
# A block of prose split on whitespace, not a list literal: a thousand quoted, comma'd
# strings would be unreadable and unmaintainable for what is plainly a word list.
COMMON_WORDS = set(
    """
    a able about above accept across act add afraid after again against age ago agree air all
    allow almost alone along already also although always among amount and anger angry animal
    another answer any appear apple are area arm army around arrive art as ask at away baby
    back bad bag ball bank bar base be bear beat beautiful because become bed been before begin
    behind believe below beside best better between big bird birth bit black blood blow blue
    board boat body book born both bottle bottom box boy break bring brother brown build burn
    business but buy by call can car care carry case cat catch cause cell centre century
    certain chair chance change check child choose church city class clean clear close cloth
    cold collect colour come common company complete condition consider continue control cook
    cool copy corner cost could count country course cover create cross crowd cry cup cut dark
    date day dead deal dear death decide deep degree describe design desire develop die
    difference different difficult dinner direct discover discuss do doctor dog door doubt down
    draw dream dress drink drive drop dry during each ear early earth east easy eat edge effect
    effort egg eight either else empty end enemy english enjoy enough enter equal escape even
    evening event ever every example except exist expect experience explain eye face fact fall
    family far farm fast father fear feed feel few field fight fill film find fine finger
    finish fire first fish fit five fix floor flower fly follow food foot for force forget form
    forward four free fresh friend from front full fun further future game garden gas gather
    general get gift girl give glass go god gold good govern great green ground group grow
    guard guess guide gun hair half hall hand hang happen happy hard hat hate have he head
    health hear heart heat heavy help her here hide high hill him his history hit hold hole
    holiday home hope horse hospital hot hour house how however human hundred hunger hurry hurt
    husband i ice idea if ill imagine important in include increase indeed inside instead
    interest into introduce iron is island it its job join joy judge jump just keep key kill
    kind king kitchen knee knife knock know lack lady lake land language large last late laugh
    law lay lead learn leave left leg lend length less let letter level lie life lift light
    like line lip list listen little live local lock long look lose lot love low luck machine
    main make man many mark market marry mass master match matter may me mean measure meat
    medicine meet member memory mention message metal method middle might mile milk mind
    minute miss mistake mix modern moment money month moon more morning most mother mountain
    mouth move much music must my name narrow nation nature near necessary neck need neighbour
    neither never new news next nice night nine no noise none nor north nose not note nothing
    notice now number obey object observe occur ocean of off offer office often oil old on once
    one only open opinion or order other our out over own page pain paint pair paper parent
    part pass past pay peace pen people perfect perhaps period person pick picture piece place
    plain plan plant play please point poor position possible post pour power prepare present
    press pretty prevent price print prison private problem produce promise proper protect
    prove provide public pull push put quality quarter queen question quick quiet quite race
    radio rain raise rate reach read ready real reason receive record red reduce refuse
    regard remain remember remove repeat reply report represent require rest result return rich
    ride right ring rise risk river road rock roll room round row rule run sad safe sail salt
    same sand save say school science sea search season seat second secret see seem sell send
    sense separate serious serve set settle seven several sex shade shake shall shape share
    sharp she sheet shine ship shoe shoot shop short should shoulder shout show shut sick side
    sign silence silver simple since sing single sister sit six size skin sky sleep slip slow
    small smell smile smoke snow so social soft soil soldier some son song soon sorry sort
    sound south space speak special speed spend spirit spot spread spring square stand star
    start state station stay steal step stick still stone stop store storm story straight
    strange street strength strike strong student study stupid subject success such sudden
    suffer sugar suggest summer sun supply support suppose sure surprise sweet swim system
    table take talk tall taste teach team tear tell ten term test than thank that the their
    them then there these they thick thin thing think third this those though thought thousand
    three through throw thus tie time tire to today together tomorrow tonight too tooth top
    total touch toward town trade train travel tree trip trouble true trust try turn twelve
    twenty two type under understand union unit until up upon use usual value various very
    village visit voice vote wait wake walk wall want war warm wash waste watch water wave way
    we wear weather week weight welcome well west wet what wheel when where whether which while
    white who whole why wide wife wild will win wind window wine wing winter wire wise wish
    with within without woman wonder wood word work world worry worth would write wrong year
    yellow yes yesterday yet you young

    account actual annual appoint arrange attend available average avoid benefit capital casual
    central certain choice citizen civil claim comment commit communicate community compare
    compete complain concern conclude confident confirm connect consist constant contain
    contract contribute convince crisis critical culture current damage danger decision
    declare defend define deliver demand depend detail determine difference
    direct disappoint discipline distance distribute economy educate effective elect
    electric emotion employ encourage energy engine environment equipment establish estimate
    eventual evidence exact examine exercise expand expense experiment expert
    express extend external factor familiar famous favour feature federal final finance
    formal fortune function fundamental generate global gradual graduate
    guarantee identify immediate impact importance impress improve incident independent
    indicate individual industry influence inform initial injure insist inspect institute
    instruct instrument intend internal international interpret invest investigate
    involve issue judgement justice knowledge labour legal limit literature maintain
    major manage manual material maximum medical mental minimum minor moral national
    natural negative normal objective obvious occasion offend official operate opportunity
    oppose option organise original participate particular partner patient pattern
    percentage permanent permit personal persuade physical political popular population
    positive possess potential practical predict prefer previous primary principle
    priority process product profession profit progress project promote propose
    publish purchase purpose qualify quantity rapid reaction realise recent
    recognise recommend refer reflect reform regular regulate relate relative
    relevant reliable religion remark remote replace republic reputation research
    resource respect respond responsible restrict reveal revenue reverse review revise
    rural satisfy schedule scheme secure security select senior sensitive
    sequence series service severe significant similar situation society solution
    specific stable standard statement statistic strategy structure substance
    succeed sufficient suitable superior surface survey survive suspect
    sustain symbol technical technique technology temporary tendency terminal territory
    theory therefore threaten tradition transfer transform transport treasure treatment
    typical ultimate unique universal urban usual vacant valid variety vehicle version
    victim violent virtual visible vision visual vital volume voluntary welfare
    """.split()  # noqa: SIM905
)

#: What the task itself demands, before any feature of the particular question.
BASE_BY_SKILL = {
    "ENG.A.1.i": 2,
    "ENG.A.2.i": 4,
    "ENG.A.3.i": 4,
    "ENG.A.4.i": 3,
    "ENG.A.5.i": 4,
    "ENG.A.6.i": 3,
    "ENG.B.1.i": 3,
    "ENG.B.2.i": 3,
    "ENG.B.3.i": 3,
    "ENG.B.3.ii": 3,
    "ENG.B.4.i": 3,
    "ENG.B.5.i": 3,
    "ENG.B.6.i": 2,
    "ENG.B.7.i": 4,
    "ENG.C.1.i": 3,
    "ENG.C.2.i": 3,
    "ENG.C.3.i": 3,
    "ENG.C.4.i": 3,
    "ENG.C.5.i": 4,
}

LEXICAL_SKILLS = {"ENG.B.1.i", "ENG.B.2.i", "ENG.B.3.i", "ENG.B.7.i"}
READING_SKILLS = {"ENG.A.1.i", "ENG.A.2.i", "ENG.A.3.i", "ENG.A.5.i", "ENG.A.6.i", "ENG.B.3.ii"}
ORAL_SKILLS = {"ENG.C.1.i", "ENG.C.2.i", "ENG.C.3.i", "ENG.C.4.i", "ENG.C.5.i"}

VOWEL_GROUP = re.compile(r"[aeiouy]+")


def syllables(word: str) -> int:
    """A rough syllable count: groups of vowels, with a silent final -e ignored."""
    cleaned = re.sub(r"[^a-z]", "", word.lower())
    if not cleaned:
        return 0
    groups = VOWEL_GROUP.findall(cleaned)
    count = len(groups)
    if cleaned.endswith("e") and count > 1 and not cleaned.endswith(("le", "ee", "ye")):
        count -= 1
    return max(1, count)


#: Endings that leave an everyday word behind. Without this, "initially" counts as rare
#: because the list holds "initial" at best and often only the bare stem — and a nine-letter
#: adverb built from a word every candidate knows is not a hard word.
SUFFIXES = (
    "ally", "ically", "fully", "ness", "ment", "ation", "ition", "ible", "able", "ology",
    "ing", "ed", "ly", "es", "s", "er", "est", "ive", "ion", "ity", "ous", "ful", "less",
    "al", "ial", "ic", "y", "ancy", "ency", "ist", "ism",
)


def _strip_once(word: str) -> set[str]:
    forms: set[str] = set()
    for suffix in SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            stem = word[: -len(suffix)]
            forms.add(stem)
            forms.add(stem + "e")          # believe -> believ(ing)
            if len(stem) > 2 and stem[-1] == stem[-2]:
                forms.add(stem[:-1])       # stopped -> stopp -> stop
            if stem.endswith("i"):
                forms.add(stem[:-1] + "y")  # happier -> happi -> happy
    return forms


def _stems(word: str) -> set[str]:
    """The word, and what it looks like with endings taken off, twice over.

    Once is not enough: "eventually" only reaches the everyday "event" after losing both
    -ly and -al, and words of that shape are exactly the ones a length test misjudges.
    """
    forms = {word}
    first = _strip_once(word)
    forms |= first
    for stem in first:
        forms |= _strip_once(stem)
    return forms


def is_uncommon(word: str) -> bool:
    """Whether a word is likely to be unfamiliar, by length and by common-word membership.

    A proxy for a frequency corpus, which is why every level this script writes is low
    confidence. It errs towards "common": a word built from an everyday stem is treated as
    everyday, because the candidate who knows "initial" can read "initially".
    """
    cleaned = re.sub(r"[^A-Za-z-]", "", word).lower()
    if len(cleaned) < 8:
        return False
    return not (_stems(cleaned) & COMMON_WORDS)


def propose(question: dict[str, object]) -> tuple[int, str]:
    """A level, and the sentence that explains which part of the rule produced it."""
    skill = str(question.get("proposed_skill") or "")
    base = BASE_BY_SKILL.get(skill, 3)
    level = base
    notes: list[str] = [f"base {base} for {skill}"]

    options = {str(k): str(v) for k, v in (question.get("options") or {}).items()}
    answer_key = str(question.get("proposed_answer") or "")
    answer = options.get(answer_key, "")
    stem = str(question.get("stem") or "")
    mean_option_length = (
        sum(len(value) for value in options.values()) / len(options) if options else 0.0
    )

    if skill in LEXICAL_SKILLS and answer:
        single_word = len(answer.split()) == 1
        if single_word and is_uncommon(answer):
            level += 1
            notes.append(f"+1: the answer '{answer}' is long and outside common vocabulary")
        elif single_word and len(answer) <= 5 and answer.lower() in COMMON_WORDS:
            level -= 1
            notes.append(f"-1: the answer '{answer}' is an everyday word")

    if skill in READING_SKILLS:
        if mean_option_length > 40:
            level += 1
            notes.append("+1: long options, so the work is reading and holding four alternatives")
        elif mean_option_length < 12 and len(stem) < 60:
            level -= 1
            notes.append("-1: short stem and short options, so little to hold at once")

    if skill in ORAL_SKILLS:
        target = stem.strip().split()[0] if stem.strip() else ""
        count = syllables(target)
        if count >= 4:
            level += 1
            notes.append(f"+1: '{target}' has about {count} syllables")
        elif count <= 1:
            level -= 1
            notes.append(f"-1: '{target}' is a monosyllable")

    level = max(1, min(5, level))
    return level, "; ".join(notes)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transcriptions", required=True)
    parser.add_argument("--year", type=int, action="append")
    args = parser.parse_args()

    folder = Path(args.transcriptions).resolve()
    spread: Counter[int] = Counter()
    total = 0

    for path in sorted(folder.glob("transcription_*.yaml")):
        document = yaml.safe_load(path.read_text())
        year = int(document["source"]["exam_year"])
        if args.year and year not in args.year:
            continue

        entries = []
        for question in document["questions"]:
            level, basis = propose(question)
            spread[level] += 1
            total += 1
            entries.append(
                {
                    "number": question["number"],
                    "proposed_level": level,
                    # Low, always: this is an estimate from features, not a judgement about
                    # the question. A person's decision replaces it and raises the source.
                    "level_confidence": "low",
                    "reason": basis,
                }
            )

        header = (
            f"# UTME {year}, Use of English — proposed difficulty levels.\n"
            "#\n"
            "# Produced by database/propose_levels_english.py, whose docstring states the rule\n"
            "# in full. Every level is low confidence and loads as model_proposed: none of it\n"
            "# is a judgement about a question, and none of it can be approved without a\n"
            "# person. A reviewer who disagrees should disagree with the rule and re-run, not\n"
            "# argue with the levels one at a time.\n"
        )
        out = folder / f"levels_{year}.yaml"
        out.write_text(
            header
            + yaml.dump(
                {"format_version": 1, "paper": {"exam_year": year}, "levels": entries},
                sort_keys=False,
                allow_unicode=True,
                width=100,
            )
        )
        print(f"{year}: {len(entries)} levels -> {out.name}")

    print(f"\n{total} questions levelled")
    for level in sorted(spread):
        share = 100 * spread[level] / total if total else 0
        print(f"  level {level}: {spread[level]:4d}  ({share:.0f}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
