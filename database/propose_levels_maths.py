#!/usr/bin/env python3
"""Propose a difficulty level for every UTME Mathematics question.

    uv run python database/propose_levels_maths.py \
        --transcriptions docs/questions/utme/mathematics

WHY THIS IS NOT THE ENGLISH SCRIPT WITH DIFFERENT WORDS. Two things make mathematics a
different problem.

The first is that word rarity, which carries most of the English rule, means nothing here.
"Evaluate" is an everyday word in a question that may or may not be hard; the difficulty is
in the mathematics, not the vocabulary.

The second is worse: 431 of the 906 maths questions — 47% — fell through to the fallback
skill during import, because the classifier reads printed directions and a mathematics paper
prints none. Basing a level on the assigned skill would therefore be basing half the bank on
a shrug. So this reads the mathematics in the stem directly, and the assigned skill is not
consulted at all.

THE RULE, in two parts.

First, a base level from the most advanced mathematics the question mentions. Topics are
tried hardest-first, so a question about the mean of a set of integrals is calculus:

    calculus, bearings, permutations, solids on a sphere    4
    algebra, trigonometric ratios, matrices, probability,
      progressions, logarithms, surds, number bases         3
    plain arithmetic, percentages, sets, averages, charts,
      the definition of a locus                             2

Second, adjustments worth one step each:

  * A word problem is harder than the same mathematics stated symbolically, because the
    candidate must first translate it. Detected by the everyday nouns and the currency that
    only appear in framed questions.
  * A long or multi-clause stem usually means more than one step.
  * A short, direct instruction — "Simplify", "Evaluate" and little else — usually means one.
  * A diagram must be read as well as the mathematics.
  * Notation the text layer could not carry is, in the source, a stacked fraction, a radical
    or a matrix: structurally richer than anything expressible on one line.

Levels are clamped to 1..5, and every one is low confidence, loading as model_proposed. None
of this is a judgement about a question; it is an estimate from what a program can see, and
the database will not let any of it reach a student unchecked.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

import yaml

#: Tried in order, hardest first: the most advanced mathematics named in the stem decides
#: the base. Each entry is (level, what it recognises, a pattern).
TOPIC_RULES: list[tuple[int, str, re.Pattern[str]]] = [
    (4, "calculus", re.compile(
        r"\bdifferentiat|\bderivative|\bintegrat|\bdy\s*/\s*dx\b|\bd2y\b|rate of change|"
        r"maximum value|minimum value|stationary point|turning point|area under the curve|"
        r"gradient of the curve|\blimit of\b", re.I)),
    (4, "bearings and elevation", re.compile(
        r"\bbearing\b|angle of (?:elevation|depression)|due (?:north|south|east|west)", re.I)),
    (4, "permutations and combinations", re.compile(
        r"permutation|combination|how many ways|arrangements|\bcommittee\b|\bselect(?:ed|ing)?"
        r" \d+ .*from\b", re.I)),
    (4, "solids and the earth as a sphere", re.compile(
        r"longitude|latitude|\bfrustum\b|\bhemisphere\b|\bpyramid\b|\bcone\b|\bsphere\b|"
        r"surface area of|\bprism\b", re.I)),
    (3, "trigonometry", re.compile(
        r"\bsine\b|\bcosine\b|\btangent\b|\bsin\b|\bcos\b|\btan\b|\bcot\b|\bsec\b|\bcosec\b",
        re.I)),
    (3, "matrices and determinants", re.compile(r"\bmatri(?:x|ces)\b|determinant", re.I)),
    (3, "progressions", re.compile(
        r"arithmetic progression|geometric progression|\bA\.?\s?P\b|\bG\.?\s?P\b|nth term|"
        r"common (?:difference|ratio)|sum to infinity", re.I)),
    (3, "indices, logarithms and surds", re.compile(
        r"logarithm|\blog\b|\bsurd|rationali[sz]e|\bindices\b|standard form|\bV\d|√", re.I)),
    (3, "number bases and modular arithmetic", re.compile(
        r"base (?:two|three|five|eight|ten|\d)|\bbase\s*\d|\bmodulo\b|\bmod\b", re.I)),
    (3, "probability", re.compile(
        r"probabilit|at random|\bdice\b|\bdie\b|tossed|\bcoin\b", re.I)),
    (3, "algebra", re.compile(
        r"factori[sz]e|polynomial|quadratic|simultaneous|inequalit|\bvaries\b|variation|"
        r"proportional|subject of the|remainder theorem|factor theorem|binary operation|"
        r"solve for|find the value of [a-z]\b|roots of", re.I)),
    (3, "measures of dispersion", re.compile(
        r"standard deviation|\bvariance\b|mean deviation", re.I)),
    (3, "circle and polygon geometry", re.compile(
        r"\bcircle\b|\bpolygon\b|\btriangle\b|quadrilateral|\bparallelogram\b|\btrapezium\b|"
        r"\brhombus\b|\btangent to\b|\bchord\b|\bsector\b|\barc\b|interior angle|"
        r"exterior angle|\bcyclic\b", re.I)),
    (3, "coordinate geometry", re.compile(
        r"\bgradient\b|\bmidpoint\b|equation of the line|perpendicular to|parallel to the line|"
        r"\bcoordinates?\b|\blocus\b.*\bequidistant\b", re.I)),
    (2, "statistics and charts", re.compile(
        r"\bmean\b|\bmedian\b|\bmode\b|\brange of\b|pie chart|bar chart|histogram|"
        r"frequency (?:table|distribution)|\bogive\b|cumulative frequency", re.I)),
    (2, "sets", re.compile(r"\bsets?\b|\bvenn\b|universal set|\bsubset\b", re.I)),
    (2, "loci", re.compile(r"\blocus\b|\bloci\b", re.I)),
    (2, "arithmetic and percentages", re.compile(
        r"simplify|evaluate|percentage|\bratio\b|simple interest|compound interest|profit|"
        r"\bloss\b|\bdiscount\b|significant figures|decimal places|\bfraction\b", re.I)),
]
FALLBACK = (3, "no topic recognised, so the middle level")

#: The extraction glues a leading instruction word to whatever follows it — "Simplifylog",
#: "Evaluatelim", "Findthe" — which defeats every pattern anchored on a word boundary. One
#: space put back is enough to let the topic rules see what the question is about.
GLUED_INSTRUCTION = re.compile(
    r"\b(simplify|evaluate|find|solve|calculate|express|determine|factori[sz]e)(?=[a-z])",
    re.I,
)

#: Algebra announces itself in notation rather than words: x^2, 3b - a, (2x+5)(x-4). A
#: question can be pure algebra without using any of algebra's vocabulary, and "Simplify
#: (x-7)/(x^2-9)" is exactly that — arithmetic's verb over algebra's content.
ALGEBRAIC_NOTATION = re.compile(r"[a-z]\s*\^?\s*[2-9]\b|[a-z]\s*[+\-]\s*[a-z0-9]|\([a-z]\s*[+\-]")


def _looks_algebraic(stem: str, options: list[str]) -> bool:
    """Whether the symbols, rather than the words, say this is algebra."""
    hits = sum(1 for text in [stem, *options] if ALGEBRAIC_NOTATION.search(text))
    return hits >= 2


#: Everyday nouns and money that only turn up when a question has been framed as a story.
WORD_PROBLEM = re.compile(
    r"\b(?:man|woman|boy|girl|student|pupil|teacher|trader|farmer|hunter|driver|worker|"
    r"brother|sister|father|mother|family|class|school|company|shop|market|team|bag|basket|"
    r"box|tank|container|bottle|car|bus|train|ship|aeroplane|boat|ladder|pole|tower|tree|"
    r"room|floor|garden|field|road|wall|pipe|rod|wire|book|shirt|orange|mango|goat|cow|"
    r"medal|ball|coin|note|salary|income|wage|price|cost)\b|#\s?\d|naira|kobo", re.I)

#: Two things joined, or a second instruction: more than one step.
MULTI_STEP = re.compile(
    r"\bhence\b|\bthen find\b|\band then\b|,\s*find .* and\b|\bfirst\b.*\bthen\b|"
    r"\bafter\b.*\bfind\b", re.I)

#: A bare instruction with nothing else in it.
DIRECT = re.compile(r"^\s*(?:simplify|evaluate|find|solve|calculate|what is)\b", re.I)


def propose(question: dict[str, object]) -> tuple[int, str]:
    """A level, and the sentence saying which part of the rule produced it."""
    stem = str(question.get("stem") or "")
    options = [str(value) for value in (question.get("options") or {}).values()]
    haystack = GLUED_INSTRUCTION.sub(r"\1 ", stem + " " + " ".join(options))

    level = FALLBACK[0]
    notes = [f"base {FALLBACK[0]}: {FALLBACK[1]}"]
    for base, label, pattern in TOPIC_RULES:
        if pattern.search(haystack):
            level = base
            notes = [f"base {base} for {label}"]
            break

    # Arithmetic's verbs over algebra's symbols: "Simplify" put the question in the wrong
    # bracket until the notation was allowed to overrule the wording.
    if level < 3 and _looks_algebraic(stem, options):
        level = 3
        notes = ["base 3: algebraic notation, whatever the instruction word says"]

    figures = question.get("figures") or []
    has_diagram = any(
        str(figure.get("alt_text", "")).startswith("Diagram") for figure in figures  # type: ignore[union-attr]
    )

    if WORD_PROBLEM.search(stem):
        level += 1
        notes.append("+1: stated as a word problem, so it must be translated before it is solved")
    if len(stem) > 150 or MULTI_STEP.search(stem):
        level += 1
        notes.append("+1: a long or two-part stem, which usually means more than one step")
    elif len(stem) < 45 and DIRECT.match(stem):
        level -= 1
        notes.append("-1: a short, direct instruction")
    if has_diagram:
        level += 1
        notes.append("+1: a diagram to read as well as the mathematics")
    if question.get("notation_suspect"):
        level += 1
        notes.append(
            "+1: notation the text layer could not carry, so a stacked or nested expression"
        )

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
                    "level_confidence": "low",
                    "reason": basis,
                }
            )

        header = (
            f"# UTME {year}, Mathematics — proposed difficulty levels.\n"
            "#\n"
            "# Produced by database/propose_levels_maths.py, whose docstring states the rule in\n"
            "# full. Levels are read from the mathematics in the stem, not from the question's\n"
            "# assigned skill: 47% of these questions fell through to a fallback skill during\n"
            "# import, because a mathematics paper prints no directions to classify from.\n"
            "#\n"
            "# Every level is low confidence and loads as model_proposed. A reviewer who\n"
            "# disagrees should disagree with the rule and re-run it, not argue one at a time.\n"
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
