#!/usr/bin/env python3
"""Re-map UTME Mathematics questions onto the skill each one actually tests.

    uv run python database/reclassify_maths.py \
        --transcriptions docs/questions/utme/mathematics --apply

WHY. The import classified questions by reading the direction printed above them, which
works for English and not at all for mathematics, because a mathematics paper prints no
directions. 431 of 906 questions matched nothing and fell to a fallback skill, and because
that fallback lives under "Fractions, Decimals, Approximations and Percentages", 476
questions — 52.5% of the bank — ended up filed under a subtopic most of them have nothing to
do with. Integration held 2 questions; binary operations held 4.

A subtopic count that wrong is not a cosmetic problem. It is what a study plan is built from:
"revise integration" is actionable and "revise fractions" is noise when the question was
about a determinant.

HOW. Mathematics announces its topic in its own vocabulary — "determinant", "integrate",
"bearing", "cumulative frequency" — so the rules below read the stem and the options rather
than waiting for a direction that was never printed. They are ordered most specific first,
because the specific term is the true one: a question mentioning both "area" and "integrate"
is integration, and one mentioning both "angle" and "bearing" is bearings.

Each mapping is recorded as proposed_by 'model' with the matched term in its reason, so a
reviewer sees why a question was filed where it was. Classifications already approved by a
person are never touched. Anything that still matches nothing keeps the fallback and is
counted in the report rather than hidden.
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

#: (skill code, what it recognises, pattern). Order matters: the first match wins, so the
#: most specific mathematics is listed first.
RULES: list[tuple[str, str, re.Pattern[str]]] = [
    # ---- Calculus: unmistakable vocabulary, and it outranks the geometry it borrows -----
    ("MATH.IV.3.ii", "area under a curve", re.compile(
        r"area under the curve|area bounded by the curve|volume of (?:the )?solid "
        r"generated|rotated about the [xy][-\s]?axis", re.I)),
    ("MATH.IV.3.i", "integration", re.compile(r"\bintegrat|\bintegral\b", re.I)),
    ("MATH.IV.2.i", "rate of change, maxima and minima", re.compile(
        r"rate of change|at the rate of|maximum value|minimum value|stationary point|"
        r"turning point|"
        r"\bmaxima\b|\bminima\b|greatest area|least value", re.I)),
    ("MATH.IV.1.i", "limit of a function", re.compile(r"\blimit\b|\blim\b", re.I)),
    ("MATH.IV.1.ii", "differentiation", re.compile(
        r"differentiat|\bderivative\b|\bdy\s*/\s*dx\b|d2y|gradient of the curve|"
        r"slope of the (?:tangent|curve)", re.I)),
    # ---- Trigonometry --------------------------------------------------------------------
    ("MATH.III.5.iv", "bearings", re.compile(r"\bbearing\b", re.I)),
    ("MATH.III.5.iii", "angles of elevation and depression", re.compile(
        r"angle of (?:elevation|depression)|angles of (?:elevation|depression)", re.I)),
    ("MATH.III.5.vi", "sine and cosine graphs", re.compile(
        r"graph of (?:the )?(?:sine|cosine)|\bsine curve\b", re.I)),
    ("MATH.III.5.v", "area of a triangle by trigonometry", re.compile(
        r"area of (?:the )?triangle.*\b(?:sin|cos)\b|\b(?:sine|cosine) (?:rule|formula)\b",
        re.I)),
    ("MATH.III.5.i", "trigonometric ratios", re.compile(
        r"\bsin\b|\bcos\b|\btan\b|\bcot\b|\bsec\b|\bcosec\b|\bsine\b|\bcosine\b|\btangent of\b",
        re.I)),
    # ---- Statistics and probability ------------------------------------------------------
    ("MATH.V.4.i", "permutations and combinations", re.compile(
        r"permutation|combination|how many ways|\barrangements?\b|arranged in a row|"
        r"\bcommittee\b|be selected from|be chosen from", re.I)),
    ("MATH.V.5.i", "probability", re.compile(
        r"probabilit|at random|\bdice\b|\bdie is\b|\bdie\b|tossed|\bcoin\b", re.I)),
    ("MATH.V.3.i", "range, deviation and variance", re.compile(
        r"standard deviation|\bvariance\b|mean deviation|\brange of\b|\bthe range\b", re.I)),
    ("MATH.V.2.ii", "ogives, quartiles and percentiles", re.compile(
        r"\bogive\b|cumulative frequency|\bquartile|\bpercentile", re.I)),
    ("MATH.V.2.i", "mean, mode and median", re.compile(
        r"\bmean\b|\bmedian\b|\bmode\b|\baverage\b", re.I)),
    ("MATH.V.1.ii", "histograms, bar charts and pie charts", re.compile(
        r"pie chart|bar chart|histogram|\bsector\b.*\bchart\b", re.I)),
    ("MATH.V.1.i", "frequency distribution tables", re.compile(
        r"frequency (?:table|distribution)|\bfrequency\b", re.I)),
    # ---- Geometry ------------------------------------------------------------------------
    ("MATH.III.2.iv", "the earth as a sphere", re.compile(r"longitude|latitude|\bequator\b", re.I)),
    ("MATH.III.2.iii", "surface areas and volumes of solids", re.compile(
        r"\bvolume\b|surface area|\bcuboid\b|\bcylinder\b|\bcone\b|\bpyramid\b|\bsphere\b|"
        r"\bhemisphere\b|\bprism\b|\bfrustum\b", re.I)),
    ("MATH.III.2.ii", "arcs, chords, sectors and segments", re.compile(
        r"\barc\b|\bchord\b|\bsector\b|\bsegment\b", re.I)),
    ("MATH.III.3.i", "loci", re.compile(r"\blocus\b|\bloci\b|equidistant from", re.I)),
    ("MATH.III.4.iv", "the equation of a line", re.compile(
        r"equation of the (?:line|straight line)|equation of a (?:line|straight line)", re.I)),
    ("MATH.III.4.iii", "parallel and perpendicular lines", re.compile(
        r"perpendicular to the line|parallel to the line|perpendicularity|\bparallelism\b",
        re.I)),
    ("MATH.III.4.i", "midpoint and gradient", re.compile(
        r"\bmidpoint\b|mid-point|\bgradient\b|\bslope\b", re.I)),
    ("MATH.III.4.ii", "distance between two points", re.compile(
        r"distance between the points|distance between two points", re.I)),
    ("MATH.III.1.iii", "circle theorems", re.compile(
        r"\bcyclic\b|circle theorem|\btangent to the circle\b|angle at the cent|"
        r"circumference of the circle.*angle", re.I)),
    ("MATH.III.1.ii", "polygons", re.compile(
        r"\bpolygon\b|\bhexagon\b|\bpentagon\b|\boctagon\b|\bquadrilateral\b|"
        r"interior angle|exterior angle|\btriangle\b|\bparallelogram\b|\btrapezium\b|"
        r"\brhombus\b|\bsquare\b of side", re.I)),
    ("MATH.III.1.i", "lines and angles", re.compile(
        r"\bangle\b|\bangles\b|\bparallel\b|\bperpendicular\b|\bbisector\b", re.I)),
    ("MATH.III.2.i", "perimeters and areas of plane figures", re.compile(
        r"\barea\b|\bperimeter\b|\bcircumference\b|\bcircle\b", re.I)),
    # ---- Algebra -------------------------------------------------------------------------
    ("MATH.II.6.ii", "determinants", re.compile(r"determinant", re.I)),
    ("MATH.II.6.iii", "inverse of a matrix", re.compile(
        r"inverse of the matrix|inverse of a matrix", re.I)),
    ("MATH.II.6.i", "matrices", re.compile(r"\bmatri(?:x|ces)\b", re.I)),
    ("MATH.II.5.ii", "identity and inverse elements", re.compile(
        r"identity element|inverse (?:element|of the element)|inverse of \d+ under", re.I)),
    ("MATH.II.5.i", "binary operations", re.compile(
        r"binary operation|\bclosure\b|commutativ|associativ|distributiv|defined by\s*[a-z]\s*\*",
        re.I)),
    ("MATH.II.4.iii", "sum to infinity", re.compile(r"sum to infinity", re.I)),
    ("MATH.II.4.i", "nth term of a progression", re.compile(r"nth term|\bn-?th term\b", re.I)),
    ("MATH.II.4.ii", "arithmetic and geometric progressions", re.compile(
        r"arithmetic progression|geometric progression|\bA\.?\s?P\b|\bG\.?\s?P\b|"
        r"common (?:difference|ratio)|\bprogression\b|\bsequence\b|\bseries\b", re.I)),
    ("MATH.II.2.i", "variation", re.compile(
        r"\bvaries\b|variation|proportional to|inversely as|directly as|\bjointly\b", re.I)),
    ("MATH.II.3.i", "inequalities", re.compile(
        r"inequalit|\bsatisfy(?:ing)? the\b.*[<>]|\brange of values\b", re.I)),
    ("MATH.II.1.i", "changing the subject of a formula", re.compile(
        r"subject of the (?:formula|relation)|make [a-z] the subject", re.I)),
    ("MATH.II.1.ii", "factor and remainder theorems", re.compile(
        r"remainder theorem|factor theorem|\bremainder when\b|is a factor of", re.I)),
    ("MATH.II.1.v", "simultaneous equations", re.compile(
        r"simultaneous|solve the (?:following )?equations?", re.I)),
    ("MATH.II.1.iv", "factorising", re.compile(r"factori[sz]e|\bfactors? of\b", re.I)),
    ("MATH.II.1.vi", "graphs of polynomials", re.compile(
        r"graph of (?:the )?(?:function|curve|y\s*=)|\bcurve\b.*\bcross", re.I)),
    ("MATH.II.1.iii", "polynomials and quadratics", re.compile(
        r"\bpolynomial\b|\bquadratic\b|\broots? of\b|\bx\^?2\b|\bx2\b", re.I)),
    # ---- Number and numeration -----------------------------------------------------------
    ("MATH.I.1.iii", "modular arithmetic", re.compile(r"\bmodulo\b|\bmod\b", re.I)),
    ("MATH.I.1.ii", "converting between bases", re.compile(
        r"convert.*base|\bin base\b|base (?:two|three|five|six|seven|eight|nine|ten)|"
        r"\bbase\s*\d|\(\d+\)\s*base|_\s*\d\b", re.I)),
    ("MATH.I.3.v", "surds", re.compile(r"\bsurd|rationali[sz]e", re.I)),
    ("MATH.I.3.iv", "logarithms", re.compile(r"logarithm|\blog\b|\blog\d", re.I)),
    ("MATH.I.3.i", "indices", re.compile(
        r"\bindices\b|\bindex\b|standard form|\d\s*\^\s*[a-z]", re.I)),
    ("MATH.I.4.iv", "Venn diagrams and sets", re.compile(
        r"\bvenn\b|universal set|\bsubset\b|\bset of\b|\bsets\b|\bintersection\b|\bunion\b|"
        r"\bcomplement\b|\bempty set\b", re.I)),
    ("MATH.I.2.iii", "interest, ratio, profit and percentage", re.compile(
        r"simple interest|compound interest|\bprofit\b|\bloss\b|\bdiscount\b|\bratio\b|"
        r"\bproportion\b|percentage error|\bper cent\b|\bpercentage\b|\bdividend\b|"
        r"\bcommission\b|\bVAT\b|\bshares\b", re.I)),
    ("MATH.I.2.ii", "significant figures and decimal places", re.compile(
        r"significant figures?|decimal places?|correct to", re.I)),
    ("MATH.I.2.i", "operations on fractions and decimals", re.compile(
        r"\bsimplify\b|\bevaluate\b|\bfraction\b|\bdecimal\b", re.I)),
]

FALLBACK = "MATH.I.2.i"

def _letter_bounded(source: str) -> str:
    r"""Rewrite \b so it separates letters from letters, not words from digits.

    In ordinary prose \b is the right boundary. In this text it is the wrong one, because
    digits sit flush against words all the time: "in the ratio2:3:5", "2x2+5x+3", "log2".
    \b sees no boundary between "ratio" and "2" — both are word characters — so the pattern
    misses. A boundary that only cares about letters matches all three while still refusing
    "along" for "log", which is the case \b was there to prevent.
    """
    source = re.sub(r"\\b(?=[A-Za-z])", "(?<![A-Za-z])", source)
    return re.sub(r"(?<=[A-Za-z])\\b", "(?![A-Za-z])", source)


#: The same rules, with boundaries that tolerate an adjacent digit.
TOLERANT_RULES: list[tuple[str, str, re.Pattern[str]]] = [
    (skill, label, re.compile(_letter_bounded(pattern.pattern), re.I))
    for skill, label, pattern in RULES
]

#: Words common to every kind of mathematics question. They are fine inside a phrase —
#: "equation of the line" is specific — but useless on their own, and the loose pass strips
#: phrases down to single words. Without this, "Solve the following equation 2/(2r-1) = ..."
#: matched "equation" and was filed under the equation of a straight line.
TOO_GENERIC = {
    "equation", "equations", "expression", "expressions", "following", "numbers", "number",
    "values", "value", "figure", "diagram", "problem", "problems", "points", "point",
    "distance", "length", "lengths", "result", "results", "answer", "answers", "correct",
    "straight", "standard", "simplify", "evaluate", "calculate", "determine", "solution",
}

#: The extraction drops spaces in the middle of sentences — "isparallel", "findthebearing",
#: "binaryoperation" — and a missing space defeats every pattern anchored on a word boundary.
#: So each rule gets a second chance against text with all spaces removed, using only the
#: distinctive words from its own pattern. Six letters is the threshold: "parallel" and
#: "bearing" cannot appear inside another word by accident, while "log", "mod" and "sin" can
#: ("along", "model", "using"), so short terms are never used in the loose pass.
LOOSE_TERMS: list[tuple[str, str, set[str]]] = [
    (
        skill,
        label,
        {
            term.lower()
            for term in re.findall(r"[a-zA-Z]{6,}", pattern.pattern)
            if term.lower() not in TOO_GENERIC
        },
    )
    for skill, label, pattern in RULES
]


def classify(question: dict[str, object]) -> tuple[str, str] | None:
    """The skill this question tests, and the term that gave it away."""
    stem = str(question.get("stem") or "")
    options = " ".join(str(value) for value in (question.get("options") or {}).values())
    # The stem says what a question is about; the options are only its answers. Reading both
    # at once let a geometry question whose answer was "2V3 cm" be filed under surds, so the
    # stem is tried alone first and the options only serve as a tie-breaker afterwards.
    for haystack in (stem, f"{stem} {options}"):
        decision = _first_match(haystack, label_suffix="")
        if decision:
            return decision

    squashed = re.sub(r"[^a-z]", "", f"{stem} {options}".lower())
    for skill, label, terms in LOOSE_TERMS:
        for term in sorted(terms, key=len, reverse=True):
            if term in squashed:
                return skill, (
                    f"Matched '{term}' once the missing spaces were ignored, which is "
                    f"{label}. The source prints many of these words run together."
                )
    return None


def _first_match(haystack: str, label_suffix: str = "") -> tuple[str, str] | None:
    for skill, label, pattern in TOLERANT_RULES:
        match = pattern.search(haystack)
        if match:
            return skill, (
                f"Matched '{match.group(0).strip()}' in the question, which is {label}. "
                "Read from the mathematics itself: this paper prints no directions."
            )
    return None


async def apply_to_database(
    updates: dict[str, tuple[str, str]], dsn: str | None
) -> tuple[int, int]:
    """Re-point draft classifications. Anything a person approved is left alone."""
    conn = await asyncpg.connect(
        dsn=dsn,
        host=None if dsn else str(ROOT / ".local/run"),
        port=None if dsn else 55439,
        database=None if dsn else "scorepilot",
    )
    try:
        await conn.execute("SET search_path = stackprep, public")
        skills = {
            row["code"]: row["id"]
            for row in await conn.fetch(
                """
                SELECT ci.code, ci.id FROM curriculum_items ci
                JOIN syllabus_versions v ON v.id = ci.syllabus_version_id
                JOIN subjects s ON s.id = v.subject_id AND s.code = 'MATH'
                JOIN examinations e ON e.id = s.examination_id AND e.short_name = 'UTME'
                WHERE ci.item_type = 'skill'
                """
            )
        }
        changed = untouched = 0
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
                   AND q.exam_year = $3 AND q.question_number = $4
                   AND c.curriculum_item_id <> $1
                """,
                target, reason, int(year), number,
            )
            if result.endswith(" 0"):
                untouched += 1
            else:
                changed += 1
        return changed, untouched
    finally:
        await conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transcriptions", required=True)
    parser.add_argument("--apply", action="store_true", help="Write the change to the database")
    parser.add_argument("--database-url", default=None)
    args = parser.parse_args()

    folder = Path(args.transcriptions).resolve()
    spread: Counter[str] = Counter()
    unmatched = 0
    total = 0
    updates: dict[str, tuple[str, str]] = {}

    for path in sorted(folder.glob("transcription_*.yaml")):
        document = yaml.safe_load(path.read_text())
        year = document["source"]["exam_year"]
        for question in document["questions"]:
            total += 1
            decision = classify(question)
            if decision is None:
                unmatched += 1
                spread[FALLBACK] += 1
                continue
            skill, reason = decision
            spread[skill] += 1
            question["proposed_skill"] = skill
            question["skill_reason"] = reason
            updates[f"{year}:{question['number']}"] = (skill, reason)
        # Keep the files and the database saying the same thing — but only when actually
        # applying. A dry run that rewrites the files it is previewing is not a dry run.
        if args.apply:
            header = "".join(
                line + "\n" for line in path.read_text().splitlines() if line.startswith("#")
            )
            path.write_text(
                header + yaml.dump(document, sort_keys=False, allow_unicode=True, width=100)
            )

    subtopics: Counter[str] = Counter()
    for skill, count in spread.items():
        subtopics[skill.rsplit(".", 1)[0]] += count
    print(f"{total} questions, {unmatched} matched nothing and kept the fallback\n")
    print("questions per subtopic:")
    for subtopic, count in sorted(subtopics.items()):
        print(f"  {subtopic:<12} {count:4d}")

    if args.apply:
        changed, untouched = asyncio.run(apply_to_database(updates, args.database_url))
        print(f"\nDatabase: {changed} classifications re-pointed, {untouched} already correct "
              "or approved and left alone.")
    else:
        print("\nDry run; pass --apply to write the change.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
