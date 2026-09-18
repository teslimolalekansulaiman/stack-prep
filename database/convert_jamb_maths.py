#!/usr/bin/env python3
"""Turn the JAMB Mathematics past-questions compilation into transcription YAML + figures.

    uv run python database/convert_jamb_maths.py \
        --pdf docs/questions/utme/mathematics/MATHEMATICS-questions.pdf \
        --out docs/questions/utme/mathematics \
        --from-year 2000

The English compilation was awkward; this one is harder, in three specific ways.

FIGURES. There is not one embedded image in the file — every diagram is vector line art,
128,192 path operators of it. So a figure cannot be extracted, only rendered: the page is
drawn to a greyscale bitmap, every word's bounding box is masked out, and whatever ink
survives is a drawing. Those regions are grown to include the labels printed inside them
(a pie chart's "Biology (3x-18)°" belongs to the picture, not to the question's sentence),
then cropped straight out of the PDF at 200dpi. This needs no imaging library: poppler
renders the analysis bitmap and also does the final crop.

NOTATION. The text layer mangles mathematics. Degree signs come out as the digit zero, so
"60°, 30°, 120°" is extracted as "600 300 1200"; exponents lose their height, so x² becomes
x2. Both are recoverable from the glyph geometry — a raised, smaller glyph is not a zero —
so superscripts are reconstructed from the word boxes rather than trusted from the text.
Anything still suspicious is flagged on the question instead of being quietly loaded.

ANSWERS. The cover says "Questions And Answers". There is no answer key anywhere in the 64
pages. Nothing here invents one: questions load with no correct option and answer_source
'unverified', which the database already understands, and which stops approval dead until
someone works them out. A wrong answer in mathematics is invisible in a way a wrong English
answer is not, so guessing 250 of them would be the worst thing this script could do.
"""

# ruff: noqa: RUF001  (the quotes here are the ones the PDF prints)
from __future__ import annotations

import argparse
import hashlib
import html
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
GUTTER_X = 318.0          # letter page, 612pt wide; the columns meet in a clear gap here
LINE_BUCKET = 4.0
ANALYSIS_DPI = 100        # enough to see a pencil line, cheap to scan in pure Python
CROP_DPI = 200            # what the student will actually look at
CELL = 4                  # analysis bitmap is reduced to cells this many pixels square
INK_THRESHOLD = 160       # 0 is black, 255 white
#: Papers up to the mid-1990s print five options; from the late 1990s, four. Which it is
#: comes from the question, not from an assumption about the year.
OPTION_KEYS = ("A", "B", "C", "D", "E")
MINIMUM_OPTIONS = 4

YEAR_RE = re.compile(r"Mathematics\s+((?:19|20)\d\d)")
QUESTION_RE = re.compile(r"^(\d{1,3})\s*[.)]\s*(.*)$")
# Options often share a line: "A. (6,5) B. (5,8) C. (5,7)".
OPTION_SPLIT_RE = re.compile(r"(?:(?<=\s)|^)([A-E])[.)]\s+")
FOOTER_RE = re.compile(r"myschoolgist|Uploaded on", re.I)
FIGURE_CUE_RE = re.compile(
    r"\bdiagram\b|\bfigure\b|\bgraph\b|shown below|shown above|the sketch", re.I)

#: Margins: the compilation stamps a banner at the top of every page and a rule at the
#: bottom. Neither is a diagram.
TOP_MARGIN_PT = 58.0
BOTTOM_MARGIN_PT = 745.0
#: A diagram is at least this big in both directions. Smaller ink is a rule, a fraction bar,
#: or the leftovers of a character the mask missed.
MIN_FIGURE_PT = 26.0

#: Subtopic keywords -> the skill under that subtopic. Mathematics papers print no
#: directions at all (English printed "choose the option opposite in meaning..."), so unlike
#: the English importer there is nothing authoritative to read: every mapping here is a
#: proposal from the words of the question, and each one says so in its reason.
SKILL_RULES: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"\bbase\s+(?:two|eight|ten|\d)\b|number base|\bmodulo\b|\bmod\b", re.I),
     "MATH.I.1.i", "number bases or modular arithmetic"),
    (re.compile(r"simple interest|percentage error|profit|\bratio\b|proportion|"
                r"significant figures|decimal places|\bVAT\b", re.I),
     "MATH.I.2.iii", "fractions, decimals, approximation or percentages"),
    (re.compile(r"logarithm|\blog\b|\bsurd|rationali[sz]e|\bindices\b|standard form", re.I),
     "MATH.I.3.i", "indices, logarithms or surds"),
    (re.compile(r"\bset\b|\bsets\b|venn|universal set|subset|intersection of", re.I),
     "MATH.I.4.iv", "sets"),
    (re.compile(r"\bmatri(?:x|ces)\b|determinant", re.I),
     "MATH.II.6.ii", "matrices and determinants"),
    (re.compile(r"\bvaries\b|variation|proportional to|inversely as", re.I),
     "MATH.II.2.i", "variation"),
    (re.compile(r"inequalit|\bgreater than or equal\b|\bless than or equal\b", re.I),
     "MATH.II.3.i", "inequalities"),
    (re.compile(r"arithmetic progression|geometric progression|\bA\.?P\b|\bG\.?P\b|"
                r"common difference|common ratio|nth term", re.I),
     "MATH.II.4.i", "progression"),
    (re.compile(r"binary operation|\bdefined by\s*[a-z]\s*\*|identity element|"
                r"inverse element", re.I),
     "MATH.II.5.i", "binary operations"),
    (re.compile(r"factori[sz]e|polynomial|quadratic|remainder theorem|factor theorem|"
                r"subject of the (?:formula|relation)|simultaneous", re.I),
     "MATH.II.1.i", "polynomials"),
    (re.compile(r"differentiat|derivative|\bdy/dx\b|rate of change", re.I),
     "MATH.IV.1.ii", "differentiation"),
    (re.compile(r"maximum value|minimum value|stationary point|turning point", re.I),
     "MATH.IV.2.i", "application of differentiation"),
    (re.compile(r"integrat|\barea under\b|\bindefinite integral\b", re.I),
     "MATH.IV.3.i", "integration"),
    (re.compile(r"probabilit|at random|\bdie\b|\bdice\b|tossed", re.I),
     "MATH.V.5.i", "probability"),
    (re.compile(r"permutation|combination|arrangements|\bhow many ways\b", re.I),
     "MATH.V.4.i", "permutation and combination"),
    (re.compile(r"standard deviation|variance|mean deviation|\brange of\b", re.I),
     "MATH.V.3.i", "measures of dispersion"),
    (re.compile(r"\bmedian\b|\bmode\b|\bmean\b|quartile|percentile|ogive", re.I),
     "MATH.V.2.i", "measures of location"),
    (re.compile(r"histogram|bar chart|pie chart|frequency (?:table|distribution)", re.I),
     "MATH.V.1.ii", "representation of data"),
    (re.compile(r"\bsine\b|\bcosine\b|\btangent\b|\bsin\b|\bcos\b|\btan\b|bearing|"
                r"angle of (?:elevation|depression)", re.I),
     "MATH.III.5.i", "trigonometry"),
    (re.compile(r"\blocus\b|\bloci\b|equidistant from", re.I), "MATH.III.3.i", "loci"),
    (re.compile(r"gradient|midpoint|equation of the (?:line|straight line)|"
                r"perpendicular to the line|parallel to the line|coordinates? of", re.I),
     "MATH.III.4.iv", "coordinate geometry"),
    (re.compile(r"\barea\b|\bvolume\b|perimeter|circumference|\bsector\b|\bsegment\b|"
                r"surface area|longitude|latitude|\bcone\b|\bcylinder\b|\bsphere\b", re.I),
     "MATH.III.2.i", "mensuration"),
    (re.compile(r"\btriangle\b|\bpolygon\b|quadrilateral|\bcircle\b|interior angle|"
                r"exterior angle|\bparallelogram\b|\btrapezium\b|cyclic", re.I),
     "MATH.III.1.ii", "Euclidean geometry"),
]
FALLBACK_SKILL = ("MATH.I.2.i", "no keyword matched; parked on basic operations for review")


@dataclass
class Word:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str

    @property
    def height(self) -> float:
        return self.y1 - self.y0


@dataclass
class Line:
    page: int
    y0: float
    y1: float
    column: int
    text: str


@dataclass
class Figure:
    page: int
    column: int
    box: tuple[float, float, float, float]      # x0, y0, x1, y1 in points
    #: 'drawing' — a histogram, pie chart or sketch, whose labels are part of the picture.
    #: 'ruled'   — a table or a stacked arithmetic layout: rules around text that must stay
    #:             in the question, because the question is the table.
    kind: str = "drawing"
    labels: list[str] = field(default_factory=list)
    path: Path | None = None
    sha256: str = ""
    width: int = 0
    height: int = 0
    byte_size: int = 0


def repo_relative(path: Path) -> str:
    """Path relative to the repository when it lives inside it, absolute otherwise.

    Matches database/load_questions.py, so a converted file can be written anywhere (a
    scratch directory while testing) without the stored URI pretending it is in the repo.
    """
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path.resolve())


def run(command: list[str]) -> bytes:
    return subprocess.run(command, check=True, capture_output=True).stdout


def page_words(pdf: Path) -> list[list[Word]]:
    xml = subprocess.run(["pdftotext", "-bbox", str(pdf), "-"],
                         check=True, capture_output=True, text=True, errors="replace").stdout
    pages = re.findall(r'<page width="[\d.]+" height="[\d.]+">(.*?)</page>', xml, re.S)
    word_re = re.compile(
        r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>',
        re.S)
    out = []
    for body in pages:
        out.append([Word(float(a), float(b), float(c), float(d), html.unescape(t))
                    for a, b, c, d, t in word_re.findall(body)])
    return out


def year_starts(words_by_page: list[list[Word]]) -> list[tuple[int, int, float]]:
    """(year, page, y) for each year banner.

    The banner is not at the top of a page. Page 61 carries the last eleven questions of
    2003, then the "Mathematics 2004" bar, then the first questions of 2004 — so a year that
    begins where its page begins would file eleven of 2003's questions under 2004 and lose
    them when the numbering failed to ascend. The banner runs the full width of the sheet,
    so its height is the boundary in both columns.
    """
    found: list[tuple[int, int, float]] = []
    for page_number, words in enumerate(words_by_page, 1):
        rows: dict[int, list[Word]] = {}
        for word in words:
            rows.setdefault(round(word.y0 / LINE_BUCKET), []).append(word)
        for key in sorted(rows):
            row = sorted(rows[key], key=lambda w: w.x0)
            text = " ".join(w.text for w in row)
            match = YEAR_RE.search(text)
            if match:
                found.append((int(match.group(1)), page_number, min(w.y0 for w in row)))
    # The cover lists every year; keep the first banner for each.
    seen: set[int] = set()
    ordered: list[tuple[int, int, float]] = []
    for year, page, y in found:
        if year not in seen and page > 1:
            seen.add(year)
            ordered.append((year, page, y))
    return ordered


def reconstruct_superscripts(words: list[Word]) -> list[Word]:
    """Put back what the flattening lost.

    A degree sign is extracted as the digit 0 and an exponent as an ordinary digit, so
    "60°" arrives as "600" and x² as "x2". The geometry still knows: the glyph is smaller
    than its neighbours and sits higher. Anything raised and small is marked, and a raised
    lone o/O/0 after a number is what it always was — a degree sign.
    """
    if not words:
        return words
    heights = sorted(w.height for w in words if w.height > 0)
    body_height = heights[len(heights) // 2] if heights else 0
    out: list[Word] = []
    for index, word in enumerate(words):
        raised = False
        if body_height and word.height < body_height * 0.85:
            previous = words[index - 1] if index else None
            if previous and word.y0 < previous.y0 - body_height * 0.12:
                raised = True
        if raised and re.fullmatch(r"[oO0]", word.text):
            out.append(Word(word.x0, word.y0, word.x1, word.y1, "°"))
        elif raised and re.fullmatch(r"[-+]?\d+|[a-z]", word.text):
            out.append(Word(word.x0, word.y0, word.x1, word.y1, f"^{word.text}"))
        else:
            out.append(word)
    return out


def column_numbers(words: list[Word], gutter: float) -> list[int]:
    """The question numbers this page yields when split at `gutter`, in reading order."""
    numbers: list[int] = []
    for low, high in ((0.0, gutter), (gutter, 1e9)):
        column = [w for w in words if low <= (w.x0 + w.x1) / 2 < high]
        for row in group_rows(column):
            match = QUESTION_RE.match(assemble_row(row))
            if match and 1 <= int(match.group(1)) <= 60:
                numbers.append(int(match.group(1)))
    return numbers


def ascending_length(numbers: list[int]) -> int:
    best = 0
    run = 0
    previous = 0
    for value in numbers:
        run = run + 1 if value > previous else 1
        previous = value
        best = max(best, run)
    return best


def find_gutter(words: list[Word], default: float = GUTTER_X) -> float:
    """Where the two columns actually meet on THIS page.

    A fixed gutter looked fine until page 63, whose right column starts at x=307 while page
    64's starts at x=324: one fixed line put five of page 63's questions into the left
    column, interleaved by height with the left column's own, and the ascending-number scan
    then dropped whichever set was shorter. Looking for a blank vertical band instead was no
    better, because a column has blank bands of its own — between a question number and its
    text, for one.

    So the page is split at each candidate and scored on the thing that actually matters:
    a correct split makes the question numbers come out ascending. Ties go to the middle of
    the sheet, which is where the gutter is on a page with too little text to tell.
    """
    best_gutter, best_score = default, -1
    for candidate in range(280, 350, 2):
        score = ascending_length(column_numbers(words, float(candidate)))
        if score > best_score or (score == best_score
                                  and abs(candidate - default) < abs(best_gutter - default)):
            best_gutter, best_score = float(candidate), score
    return best_gutter


def read_pgm(path: Path) -> tuple[int, int, bytes]:
    data = path.read_bytes()
    parts = data.split(b"\n", 3)
    width, height = (int(v) for v in parts[1].split())
    return width, height, parts[3]


def find_figures(pdf: Path, page: int, words: list[Word], work: Path,
                 gutter: float) -> tuple[list[Figure], list[tuple[float, float, float, float]]]:
    """Regions of the page that carry ink but no text.

    The page is rendered small and grey, every word is painted out of it, and what is left
    is drawing. Strokes arrive as separate blobs, so the grid is dilated before components
    are collected — otherwise a triangle comes back as three figures.
    """
    prefix = work / f"page{page}"
    run(["pdftoppm", "-gray", "-r", str(ANALYSIS_DPI), "-f", str(page), "-l", str(page),
         "-q", str(pdf), str(prefix)])
    rendered = next(iter(sorted(work.glob(f"page{page}*.pgm"))), None)
    if rendered is None:
        return [], []
    width, height, pixels = read_pgm(rendered)
    scale = ANALYSIS_DPI / 72

    mask = bytearray(width * height)
    for word in words:
        for y in range(max(0, int(word.y0 * scale) - 2), min(height, int(word.y1 * scale) + 2)):
            row = y * width
            for x in range(max(0, int(word.x0 * scale) - 2),
                           min(width, int(word.x1 * scale) + 2)):
                mask[row + x] = 1

    cols = (width + CELL - 1) // CELL
    rows = (height + CELL - 1) // CELL
    grid = bytearray(cols * rows)
    for y in range(height):
        row = y * width
        cell_row = (y // CELL) * cols
        for x in range(width):
            if pixels[row + x] < INK_THRESHOLD and not mask[row + x]:
                grid[cell_row + x // CELL] = 1

    # Dilate so the separate strokes of one drawing become one blob.
    grown = bytearray(grid)
    reach = 3
    for cy in range(rows):
        for cx in range(cols):
            if not grid[cy * cols + cx]:
                continue
            for dy in range(-reach, reach + 1):
                ny = cy + dy
                if not 0 <= ny < rows:
                    continue
                for dx in range(-reach, reach + 1):
                    nx = cx + dx
                    if 0 <= nx < cols:
                        grown[ny * cols + nx] = 1

    seen = bytearray(len(grown))
    figures: list[Figure] = []
    #: Ink too small to be a figure. In a mathematics paper this is not noise: it is the bar
    #: of a stacked fraction, the hook of a radical, the rule under a column of digits —
    #: precisely the notation the text layer cannot express.
    minor: list[tuple[float, float, float, float]] = []
    for start in range(len(grown)):
        if not grown[start] or seen[start]:
            continue
        stack = [start]
        seen[start] = 1
        cells = []
        while stack:
            cell = stack.pop()
            cells.append(cell)
            cy, cx = divmod(cell, cols)
            for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
                if 0 <= ny < rows and 0 <= nx < cols:
                    neighbour = ny * cols + nx
                    if grown[neighbour] and not seen[neighbour]:
                        seen[neighbour] = 1
                        stack.append(neighbour)

        # Measure the REAL ink inside the blob, not the dilated blob: dilation is only there
        # to join the strokes of one drawing, and it would otherwise inflate a hairline into
        # something that looks like a figure.
        raw = [c for c in cells if grid[c]]
        if not raw:
            continue
        ys = sorted({c // cols for c in raw})
        xs = sorted({c % cols for c in raw})
        x0 = (xs[0] * CELL) / scale
        x1 = ((xs[-1] + 1) * CELL) / scale
        y0 = (ys[0] * CELL) / scale
        y1 = ((ys[-1] + 1) * CELL) / scale
        if y1 < TOP_MARGIN_PT or y0 > BOTTOM_MARGIN_PT:
            continue
        # A fraction bar is one row of cells; a rule is one row; a drawing is two-dimensional.
        if (len(raw) < 25 or len(ys) < 6 or len(xs) < 6
                or (x1 - x0) < MIN_FIGURE_PT or (y1 - y0) < MIN_FIGURE_PT):
            minor.append((x0, y0, x1, y1))
            continue
        # Page furniture: the compilation stamps a filled black banner with the year across
        # the full width of the page. Nothing that wide is a question's diagram.
        if (x1 - x0) > 300 or (x0 < gutter < x1):
            continue

        # Straight long runs mean rules — a table, or the line under a stacked subtraction.
        inked = set(raw)
        runs = 0
        for cell in raw:
            cy, cx = divmod(cell, cols)
            if all(cy * cols + cx + step in inked for step in range(1, 9)):
                runs += 1
        kind = "ruled" if runs * 3 > len(raw) else "drawing"

        column = 0 if (x0 + x1) / 2 < gutter else 1
        figures.append(Figure(page=page, column=column, box=(x0, y0, x1, y1), kind=kind))

    # Grow each figure to swallow the labels printed inside it, and remember their text:
    # those words are part of the picture and must leave the question's sentence.
    for figure in figures:
        x0, y0, x1, y1 = figure.box
        for word in words:
            if (word.x0 > x0 - 14 and word.x1 < x1 + 14
                    and word.y0 > y0 - 10 and word.y1 < y1 + 10):
                figure.labels.append(word.text)
                x0, y0 = min(x0, word.x0), min(y0, word.y0)
                x1, y1 = max(x1, word.x1), max(y1, word.y1)
        figure.box = (x0, y0, x1, y1)
    return figures, minor


def crop_figure(pdf: Path, figure: Figure, figures_dir: Path, work: Path) -> None:
    """Render just the figure's rectangle, and name the file after its own bytes."""
    pad = 6
    x0, y0, x1, y1 = figure.box
    scale = CROP_DPI / 72
    args = ["-x", str(int((x0 - pad) * scale)), "-y", str(int((y0 - pad) * scale)),
            "-W", str(int((x1 - x0 + 2 * pad) * scale)),
            "-H", str(int((y1 - y0 + 2 * pad) * scale))]
    prefix = work / f"crop{figure.page}_{int(y0)}"
    run(["pdftoppm", "-png", "-r", str(CROP_DPI), "-f", str(figure.page),
         "-l", str(figure.page), *args, "-q", str(pdf), str(prefix)])
    rendered = next(iter(sorted(work.glob(f"{prefix.name}*.png"))), None)
    if rendered is None:
        return
    data = rendered.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    target = figures_dir / f"{digest}.png"
    if not target.exists():
        figures_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(rendered, target)
    rendered.unlink(missing_ok=True)
    figure.path = target
    figure.sha256 = digest
    figure.byte_size = len(data)
    # PNG header: width and height are big-endian at byte 16.
    figure.width = int.from_bytes(data[16:20], "big")
    figure.height = int.from_bytes(data[20:24], "big")


def crop_region(pdf: Path, page: int, box: tuple[float, float, float, float],
                figures_dir: Path, work: Path) -> Figure:
    """Crop an arbitrary rectangle of a page — used to keep a question as it was printed."""
    figure = Figure(page=page, column=0, box=box, kind="printed")
    crop_figure(pdf, figure, figures_dir, work)
    return figure


def describe(figure: Figure) -> str:
    if figure.kind == "printed":
        return ("The question exactly as printed, kept because its notation — a stacked "
                "fraction, a radical or a column of figures — does not survive text "
                "extraction. Not yet checked by a person.")
    labels = [label for label in figure.labels if label.strip()]
    if labels:
        return ("Diagram from the paper, carrying the labels: " + " ".join(labels)
                + ". Not yet checked by a person.")
    return "Diagram from the paper, with no text labels. Not yet checked by a person."


def assemble_row(row: list[Word]) -> str:
    """Join one line's words, putting back the spacing the PDF threw away.

    This compilation sets text with per-character kerning, so pdftotext hands back
    "Tr ia n gl e OPQ a bove" — fragments, not words. A gap much narrower than the glyphs
    around it was never a space, so fragments are joined and only real gaps become spaces.
    """
    row = sorted(row, key=lambda w: w.x0)
    heights = [w.height for w in row if w.height > 0]
    typical = sorted(heights)[len(heights) // 2] if heights else 8.0
    out = row[0].text
    for previous, word in pairwise(row):
        gap = word.x0 - previous.x1
        out += word.text if gap < typical * 0.22 else f" {word.text}"
    return out.strip()


def group_rows(words: list[Word], tolerance: float = 3.0) -> list[list[Word]]:
    """Cluster words into printed lines by their vertical centre.

    Fixed-width buckets split a line whenever a glyph sits on its own baseline — which is
    exactly what mathematical operators do. The inequality signs of a question were landing
    in a bucket of their own and being appended to the end of the stem, so "x - 1 =< 0"
    arrived as "x - 1 0 ... =<". Clustering by centre with a tolerance keeps the line whole.
    """
    if not words:
        return []
    ordered = sorted(words, key=lambda w: (w.y0 + w.y1) / 2)
    rows: list[list[Word]] = [[ordered[0]]]
    centre = (ordered[0].y0 + ordered[0].y1) / 2
    for word in ordered[1:]:
        middle = (word.y0 + word.y1) / 2
        if abs(middle - centre) <= tolerance:
            rows[-1].append(word)
        else:
            rows.append([word])
        centre = sum((w.y0 + w.y1) / 2 for w in rows[-1]) / len(rows[-1])
    return rows


#: What a mangled stacked fraction looks like once it has been flattened into a line:
#: a slash with nothing after it, or a tail of loose digits that were once denominators —
#: "Simplify 1 - (21/ x 11/ ) + 3/ 3 4 5".
DAMAGED_TEXT_RE = re.compile(r"/\s|\s\d(?:\s+\d){2,}\s*$|\(\s*\)")


def looks_damaged(stem: str, options: dict[str, str]) -> bool:
    if DAMAGED_TEXT_RE.search(stem):
        return True
    return any(DAMAGED_TEXT_RE.search(value) for value in options.values())


def clean(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text.replace("’", "'").replace("‘", "'").strip()


def split_options(text: str) -> dict[str, str]:
    parts = OPTION_SPLIT_RE.split(text)
    found: dict[str, str] = {}
    for index in range(1, len(parts) - 1, 2):
        letter = parts[index]
        value = clean(parts[index + 1])
        if value:
            found[letter] = value
    return found


def classify(stem: str, options: dict[str, str]) -> tuple[str, str]:
    haystack = f"{stem} {' '.join(options.values())}"
    for pattern, skill, topic in SKILL_RULES:
        if pattern.search(haystack):
            return skill, (f"Proposed from the wording of the question, which is about "
                           f"{topic}. The paper prints no direction to read instead.")
    return FALLBACK_SKILL[0], ("Proposed as a fallback: " + FALLBACK_SKILL[1] + ". The paper "
                               "prints no direction, so this needs a person.")


def longest_run(candidates: list[tuple[int, int]]) -> list[tuple[int, int]]:
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


def parse_year(pdf: Path, year: int, begin: tuple[int, float], finish: tuple[int, float],
               words_by_page: list[list[Word]], figures_dir: Path,
               work: Path) -> tuple[dict, list[str]]:
    rejections: list[str] = []
    lines: list[Line] = []
    figures: list[Figure] = []
    leftover_ink: list[tuple[int, tuple[float, float, float, float]]] = []
    gutter_of: dict[int, float] = {}

    first, first_y = begin
    last, last_y = finish
    for page in range(first, last + 1):

        all_words = reconstruct_superscripts(words_by_page[page - 1])
        words = [w for w in all_words
                 if not (page == first and w.y0 < first_y)
                 and not (page == last and w.y0 >= last_y)]
        gutter = find_gutter(words)
        gutter_of[page] = gutter
        page_figures, minor_ink = find_figures(pdf, page, words, work, gutter)
        leftover_ink.extend((page, box) for box in minor_ink)
        label_boxes = [f.box for f in page_figures if f.kind == "drawing"]
        figures.extend(page_figures)

        for column, (low, high) in enumerate(((0.0, gutter), (gutter, 1e9))):
            in_column = [w for w in words if low <= (w.x0 + w.x1) / 2 < high]
            keep = [
                word for word in in_column
                if not FOOTER_RE.search(word.text)
                # A label inside a diagram belongs to the picture, not to the sentence.
                and not any(box[0] - 14 < word.x0 and word.x1 < box[2] + 14
                            and box[1] - 10 < word.y0 and word.y1 < box[3] + 10
                            for box in label_boxes)
            ]
            for row in group_rows(keep):
                text = assemble_row(row)
                if text and not FOOTER_RE.search(text):
                    lines.append(Line(page, min(w.y0 for w in row), max(w.y1 for w in row),
                                      column, text))

    candidates = [(index, int(match.group(1)))
                  for index, line in enumerate(lines)
                  if (match := QUESTION_RE.match(line.text)) and 1 <= int(match.group(1)) <= 60]
    starts = longest_run(candidates)

    def position_of(page: int, column: int, y: float) -> tuple[int, int, float]:
        return (page, column, y)

    start_positions = [
        (position_of(lines[index].page, lines[index].column, lines[index].y0), number)
        for index, number in starts
    ]
    owners: dict[int, list[Figure]] = {}
    for figure in figures:
        here = position_of(figure.page, figure.column, figure.box[1])
        candidates = [(key, number) for key, number in start_positions if key <= here]
        if not candidates:
            continue
        _key, number = max(candidates, key=lambda item: item[0])
        crop_figure(pdf, figure, figures_dir, work)
        owners.setdefault(number, []).append(figure)

    questions: list[dict] = []
    for position, (index, number) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
        segment = lines[index:end]
        head = QUESTION_RE.match(segment[0].text)
        body = [head.group(2)] + [line.text for line in segment[1:]]
        joined = clean(" ".join(body))

        options = split_options(joined)
        stem = clean(OPTION_SPLIT_RE.split(joined)[0])
        present = [key for key in OPTION_KEYS if options.get(key)]
        missing = [key for key in OPTION_KEYS[:len(present)] if not options.get(key)]
        if len(present) < MINIMUM_OPTIONS or missing:
            rejections.append(
                f"{year} Q{number}: "
                + (f"option(s) {','.join(missing)} not found in the source" if missing
                   else f"only {len(present)} options found"))
            continue
        if not stem:
            rejections.append(f"{year} Q{number}: no stem left once the options were split off")
            continue

        owned = owners.get(number, [])
        if FIGURE_CUE_RE.search(stem) and not owned:
            rejections.append(
                f"{year} Q{number}: the question refers to a diagram but none was found on "
                "the page; it cannot be answered as text alone")
            continue

        # Ink inside this question that was too small to be a figure means the printed
        # notation is richer than the text: a fraction bar, a radical, a division rule. The
        # extracted text is then an unreliable rendering of the question, so the question is
        # kept as an image as well, and marked.
        region_top = segment[0].y0 - 2
        region_bottom = max(line.y1 for line in segment) + 2
        suspect = any(
            page == segment[0].page and box[3] > region_top and box[1] < region_bottom
            for page, box in leftover_ink
        )
        suspect = suspect or looks_damaged(stem, options)
        printed_copy: list[Figure] = []
        if suspect:
            column_x = (30.0, gutter_of.get(segment[0].page, GUTTER_X) - 4) \
                if segment[0].column == 0 \
                else (gutter_of.get(segment[0].page, GUTTER_X) + 4, 585.0)
            printed_copy = [crop_region(
                pdf, segment[0].page,
                (column_x[0], region_top, column_x[1], min(region_bottom, BOTTOM_MARGIN_PT)),
                figures_dir, work)]

        skill, reason = classify(stem, options)
        questions.append({
            "number": number,
            "page": segment[0].page,
            "stem": stem,
            "options": {key: options[key] for key in present},
            # No answer: this compilation prints no key. See the module docstring.
            "proposed_skill": skill,
            "skill_reason": reason,
            "notation_suspect": bool(printed_copy),
            "figures": [
                {
                    "file": repo_relative(f.path) if f.path else None,
                    "sha256": f.sha256,
                    "width": f.width,
                    "height": f.height,
                    "byte_size": f.byte_size,
                    "alt_text": describe(f),
                    "alt_text_source": "model_proposed",
                    "source_location": (
                        f"PDF page {f.page}, crop "
                        f"({f.box[0]:.0f},{f.box[1]:.0f})-({f.box[2]:.0f},{f.box[3]:.0f})pt"),
                }
                for f in owned + printed_copy
            ],
        })

    for question in questions:
        for figure in question["figures"]:
            if figure["file"] is None:
                rejections.append(
                    f"{year} Q{question['number']}: a diagram was detected but could not be "
                    "rendered")

    document = {
        "format_version": 1,
        "source": {
            "file": "docs/questions/utme/mathematics/MATHEMATICS-questions.pdf",
            "exam_year": year,
            "paper_label": f"UTME {year} Mathematics (objective)",
            "paper_code": f"UTME-{year}-MATH",
            "question_count": max((q["number"] for q in questions), default=0),
            # There is no key in this compilation. Nothing here proposes one.
            "answer_source": "unverified",
        },
        "passages": [],
        "questions": questions,
    }
    return document, rejections


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--from-year", type=int, default=2000,
                        help="Earliest year to convert (default 2000)")
    parser.add_argument("--year", type=int, action="append")
    args = parser.parse_args()

    pdf = Path(args.pdf).resolve()
    out = Path(args.out).resolve()
    figures_dir = out / "figures"
    out.mkdir(parents=True, exist_ok=True)

    words = page_words(pdf)
    starts = year_starts(words)

    totals = Counter()
    all_rejections: list[str] = []
    with tempfile.TemporaryDirectory() as temporary:
        work = Path(temporary)
        for index, (year, page, y) in enumerate(starts):
            if args.year and year not in args.year:
                continue
            if not args.year and year < args.from_year:
                continue
            if index + 1 < len(starts):
                finish = (starts[index + 1][1], starts[index + 1][2])
            else:
                finish = (len(words), 1e9)
            document, rejections = parse_year(pdf, year, (page, y), finish, words,
                                              figures_dir, work)
            all_rejections.extend(rejections)
            with_figures = sum(1 for q in document["questions"] if q["figures"])
            header = (
                f"# UTME {year}, Mathematics — extracted from the text layer and the rendered\n"
                f"# figures of {document['source']['file']}.\n#\n"
                f"# {len(document['questions'])} questions kept, {len(rejections)} rejected,\n"
                f"# {with_figures} carrying a diagram cropped from the page.\n#\n"
                "# THERE ARE NO ANSWERS. The compilation prints no key, and this importer does\n"
                "# not invent one: every question loads with no correct option and\n"
                "# answer_source 'unverified'. Approval is impossible until someone works them\n"
                "# out. Skill mappings are proposed from the wording, since the paper prints no\n"
                "# directions of its own.\n")
            (out / f"transcription_{year}.yaml").write_text(
                header + yaml.dump(document, sort_keys=False, allow_unicode=True, width=100))
            totals[year] = len(document["questions"])
            print(f"{year}: {len(document['questions']):3d} questions, "
                  f"{len(rejections):2d} rejected, {with_figures} with a diagram")

    print(f"\nTotal questions: {sum(totals.values())}")
    if all_rejections:
        print(f"Rejected {len(all_rejections)}:")
        for reason in all_rejections[:40]:
            print(f"  - {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
