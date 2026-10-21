#!/usr/bin/env python3
"""Deterministic linter for the structural STE rules in SKILL.md.

Checks only rules verifiable without ASD's dictionary. Never flags hedges
or modality (may/might/could): confidence is content, not style.

Usage:
  ste-lint.py FILE [FILE ...]
  echo "text" | ste-lint.py [--json]
  ste-lint.py --baseline 5 FILE      # pass unless hard violations exceed 5
  ste-lint.py --disable passive-voice,present-perfect FILE
  ste-lint.py --selftest

Exit 1 when hard violations exceed the baseline (default 0).
Advisory findings never fail the run. Exit 2 on a usage error.
"""
import argparse
import bisect
import json
import re
import sys

# Irregular past participles used by the present-perfect heuristic.
IRREGULAR_PARTICIPLES = (
    "given|taken|made|done|found|seen|known|shown|written|built|sent|set"
    "|run|read|kept|held|left|put|cut|hit|let|shut|split|spread|begun"
    "|become|come|gone|got|gotten|lost|met|paid|said|sold|told|thought"
    "|brought|bought|caught|taught|won|worn|torn|born|drawn|grown|thrown"
    "|flown|driven|risen|chosen|broken|spoken|frozen|hidden|ridden"
    "|forgotten|fallen|eaten|beaten|understood|stood|struck|stuck|swung"
    "|hung|led|fed|bled|fled|sped|bound|wound|dug|spun|slid|bit|lit|quit"
)
PASSIVE_PARTICIPLES = (
    "given|taken|made|done|found|seen|known|shown|written|built|sent"
    "|set|run|read|kept|held|left|put"
)
MODAL_PERFECT_PREFIX = re.compile(
    r"\b(?:may|might|could|should|would|must|can|will|shall)"
    r"(?:\s+not|n['\u2019]t)?\s+",
    re.I,
)

MAX_WORDS = 25  # STE-flavored cap for descriptions/prose

RULES = [
    ("semicolon", "advisory-free", re.compile(r";"),
     "STE bans the semicolon (Rule 8.1). Split into separate sentences."),
    ("phrasal-verb", "advisory-free",
     re.compile(
         r"\b(spin(?:ning|s)? up|spun up|reach(?:ing|es|ed)? out|"
         r"div(?:e|es|ing|ed) into|dove into|kick(?:ing|s|ed)? off|"
         r"circl(?:e|es|ing|ed) back|touch(?:ing|es|ed)? base)\b",
         re.I,
     ),
     "Soft phrasal verb. Use the single plain verb (start, contact, read, begin)."),
    ("marketing-adjective", "advisory-free",
     re.compile(
         r"\b(seamless(?:ly)?|robust(?:ly)?|cutting-edge|effortless(?:ly)?|"
         r"blazing[- ]fast|world-class|state-of-the-art|game-chang(?:ing|er))\b",
         re.I,
     ),
     "Marketing adjective. Delete, or replace with the measurement that earns the claim."),
    ("nominalization", "advisory-free",
     re.compile(
         r"\b(perform|performs|performed|conduct|conducts|conducted|"
         r"carry out|carries out|carried out)\s+(?:a|an|the)\s+"
         r"\w+(?:tion|sion|ment|ance|ence|ysis)\b",
         re.I,
     ),
     "Action frozen into a noun. Use the verb (analyze, not perform an analysis of)."),
    ("passive-voice", "advisory",
     re.compile(
         r"\b(is|are|was|were|been|being)\s+(\w+ed|"
         + PASSIVE_PARTICIPLES + r")\b(?!\s+(?:to|for|by)\s+\w+ing)",
         re.I,
     ),
     "Possible passive voice. Name the actor and use an active verb, "
     "unless the actor is unknown or irrelevant."),
    ("present-perfect", "advisory",
     re.compile(
         r"\b(?:has|have|had)\s+\w+(?:ed|"
         + IRREGULAR_PARTICIPLES + r")\b",
         re.I,
     ),
     "Present perfect tense. Use the simple past ('we received' not 'we have received'). "
     "Keep the compound form if it carries current relevance or a hedge."),
]

# Synonym groups for the one-word-one-meaning check (advisory).
SYNONYM_GROUPS = [
    ("check", "verify", "confirm", "validate"),
    ("use", "utilize", "employ"),
    ("start", "begin", "commence", "initiate"),
    ("end", "finish", "complete", "conclude"),
    ("show", "display", "present", "exhibit"),
    ("make", "create", "produce", "generate"),
]

INLINE_CODE = re.compile(r"`[^`]*`")
LIST_ITEM_START = re.compile(
    r"^\s*(?:[-*+]|[0-9]+[.)])(?:\s|$)"
)
CONJUNCTION_END = re.compile(r"\b(?:and|or)\s*$", re.I)
STANDALONE_LINE = re.compile(r"^ {0,3}(?:#|<|(?:[-*_=] *){3,}$)")
BLOCKQUOTE_PREFIX = re.compile(r"^ {0,3}(?:> ?)+")
ANY_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|[0-9]+[.)])(?:\s|$)")
SENTENCE_END = re.compile(r"[.!?][\"'\u201d\u2019)\]*_]*$")
OPENERS = "\"'\u201c\u2018([*_"
ABBREVIATIONS = {"vs.", "cf.", "approx.", "mr.", "mrs.", "ms.", "dr.", "fig.", "no."}
DOTTED_ABBREVIATION = re.compile(r"(?:[a-z]\.){2,}", re.I)
CODE_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


def _word_re(base):
    return re.compile(r"\b" + base + r"(?:s|es|ed|d|ing)?\b", re.I)


def _mask_inline_code(text):
    """Blank code spans with equal-length spaces so columns stay true."""
    return INLINE_CODE.sub(lambda m: " " * len(m.group(0)), text)


def _sentence_starts(text):
    """Return the offset of each sentence start in text."""
    words = list(re.finditer(r"\S+", text))
    if not words:
        return [0]
    starts = [words[0].start()]
    for word, next_word in zip(words, words[1:], strict=False):
        end = SENTENCE_END.search(word.group())
        if not end:
            continue
        core = word.group()[:end.start() + 1].lstrip(OPENERS)
        if core.lower() in ABBREVIATIONS:
            continue
        if (DOTTED_ABBREVIATION.fullmatch(core)
                and not next_word.group().lstrip(OPENERS)[:1].isupper()):
            continue
        starts.append(next_word.start())
    return starts


def _long_sentence_findings(pieces, filename):
    """Flag long sentences in one prose block."""
    offsets, position = [], 0
    for _, _, text in pieces:
        offsets.append(position)
        position += len(text) + 1
    joined = " ".join(text for _, _, text in pieces)
    findings = []
    starts = _sentence_starts(joined)
    for start, end in zip(starts, starts[1:] + [len(joined)], strict=False):
        n = len(joined[start:end].split())
        if n <= MAX_WORDS:
            continue
        index = bisect.bisect_right(offsets, start) - 1
        offset = offsets[index]
        lineno, source_column, _ = pieces[index]
        findings.append({
            "file": filename, "line": lineno,
            "col": source_column + start - offset + 1,
            "rule": "long-sentence", "level": "advisory-free",
            "match": f"{n} words",
            "message": f"Sentence has {n} words (cap {MAX_WORDS}). Split it.",
        })
    return findings


def _leading_spaces(line):
    return len(line) - len(line.lstrip(" "))


def _is_list_continuation(line, content_indent):
    if not line.strip():
        return True
    if LIST_ITEM_START.match(line):
        return False
    return _leading_spaces(line) >= content_indent


def _markdown_table_cells(lines):
    """Return a dict: line_index -> list of (cell_text, source_col) tuples."""
    cells = {}
    for i, line in enumerate(lines):
        stripped = line.strip()
        if "|" not in stripped or not stripped.startswith("|"):
            continue
        if set(stripped.replace("|", "").strip()) <= {"-", ":"}:
            continue
        left = len(line) - len(line.lstrip())
        content = line[left:].rstrip()
        if content.startswith("|"):
            content = content[1:]
            left += 1
        if content.endswith("|"):
            content = content[:-1]
        raw_cells = re.split(r"(?<!\\)\|", content)
        cells[i] = [(c.strip(), left) for c in raw_cells]
    return cells


def _dangling_conjunction_findings(text, filename):
    """Flag list items ending with a dangling 'and' or 'or'."""
    lines = text.splitlines()
    findings = []
    for i, line in enumerate(lines, 1):
        m = LIST_ITEM_START.match(line)
        if not m:
            continue
        marker_end = m.end()
        item_text = line[marker_end:].rstrip()
        if CONJUNCTION_END.search(item_text):
            col = marker_end + len(item_text.rstrip()) - 2
            findings.append({
                "file": filename, "line": i, "col": max(1, col + 1),
                "rule": "dangling-conjunction", "level": "advisory-free",
                "match": item_text.rstrip()[-10:],
                "message": "List item ends with a conjunction. "
                           "Complete the item or remove the conjunction.",
            })
    return findings


def _scan_line_rules(findings, line, filename, lineno, source_column):
    """Scan one line for rule violations. Extracted from lint() for C901."""
    for rule_id, level, pattern, msg in RULES:
        for m in pattern.finditer(line):
            if rule_id == "present-perfect" and MODAL_PERFECT_PREFIX.search(
                line[:m.start()]
            ):
                continue
            findings.append({
                "file": filename, "line": lineno,
                "col": source_column + m.start() + 1,
                "rule": rule_id, "level": level,
                "match": m.group(0), "message": msg,
            })


def _scan_synonyms(seen_synonyms, line, lineno, source_column):
    """Track first occurrence of each synonym group member. Extracted from lint()."""
    for gi, group in enumerate(SYNONYM_GROUPS):
        for base in group:
            if (gi, base) in seen_synonyms:
                continue
            m = _word_re(base).search(line)
            if m:
                seen_synonyms[(gi, base)] = (
                    lineno, source_column + m.start() + 1, m.group(0)
                )


def _add_to_block(block, line, quote, is_table, lineno, source_column):
    """Add a line to the current prose block. Extracted from lint() for C901."""
    skip = quote.end() if quote and not is_table else 0
    if line[skip:].strip():
        block.append((lineno, source_column + skip, line[skip:]))


def _is_block_boundary(is_table, content, standalone, is_quote, in_quote):
    """Check if this line ends the current prose block. Extracted from lint()."""
    return (is_table or not content.strip() or standalone
            or ANY_LIST_ITEM.match(content) or is_quote != in_quote)


def _process_segment(findings, seen_synonyms, block, segment,
                     filename, lineno, source_column, quote, is_table):
    """Process one segment of a line. Extracted from lint() for C901.
    Returns the word count for this segment."""
    line = _mask_inline_code(segment)
    words = len(line.split())
    _scan_line_rules(findings, line, filename, lineno, source_column)
    _scan_synonyms(seen_synonyms, line, lineno, source_column)
    _add_to_block(block, line, quote, is_table, lineno, source_column)
    return words


def _parse_line(raw_line, lineno, table_cells):
    """Parse a line into its components. Extracted from lint() for C901.
    Returns (segments, is_table, quote, is_quote, content, standalone)."""
    segments = table_cells.get(lineno - 1, [(raw_line, 0)])
    is_table = (lineno - 1) in table_cells
    quote = BLOCKQUOTE_PREFIX.match(raw_line)
    is_quote = bool(quote)
    content = raw_line[quote.end():] if quote else raw_line
    standalone = STANDALONE_LINE.match(content)
    return segments, is_table, quote, is_quote, content, standalone


def _find_synonym_rotation(findings, seen_synonyms, filename):
    """Flag synonym rotation: same action named with different words. Extracted from lint()."""
    for gi, group in enumerate(SYNONYM_GROUPS):
        present = [
            (seen_synonyms[(gi, b)], b) for b in group if (gi, b) in seen_synonyms
        ]
        if len(present) > 1:
            present.sort()
            first_base = present[0][1]
            for (lineno, col, match), base in present[1:]:
                findings.append({
                    "file": filename, "line": lineno, "col": col,
                    "rule": "synonym-rotation", "level": "advisory-free",
                    "match": match,
                    "message": f"'{base}' and '{first_base}' name the same action. "
                               f"Pick one and use it every time.",
                })


def lint(text, filename="<stdin>"):
    """Lint text, return (findings, words_total)."""
    findings = []
    words_total = 0
    in_fence = False
    lines = text.splitlines()
    table_cells = _markdown_table_cells(lines)
    seen_synonyms = {}
    block = []
    in_quote = False

    def flush():
        findings.extend(_long_sentence_findings(block, filename))
        block.clear()

    for lineno, raw_line in enumerate(lines, 1):
        if CODE_FENCE.match(raw_line.strip()):
            flush()
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        segments, is_table, quote, is_quote, content, standalone = _parse_line(
            raw_line, lineno, table_cells
        )
        if _is_block_boundary(is_table, content, standalone, is_quote, in_quote):
            flush()
            in_quote = is_quote
        for segment, source_column in segments:
            words_total += _process_segment(
                findings, seen_synonyms, block, segment, filename,
                lineno, source_column, quote, is_table,
            )
            if is_table:
                flush()
            if standalone:
                flush()
    flush()
    _find_synonym_rotation(findings, seen_synonyms, filename)
    findings.extend(_dangling_conjunction_findings(text, filename))
    findings.sort(key=lambda f: (f["line"], f["col"]))
    return findings, words_total


def report(findings, words_total, as_json, hard_count, baseline):
    rate = round(len(findings) * 100 / words_total, 1) if words_total else 0.0
    if as_json:
        print(json.dumps({
            "violations": findings, "count": len(findings),
            "hard_count": hard_count, "baseline": baseline,
            "words": words_total, "per_100_words": rate,
        }, indent=2))
        return
    for f in findings:
        print(f"{f['file']}:{f['line']}:{f['col']} {f['rule']}: {f['message']} [{f['match']}]")
    print(f"\n{len(findings)} violations ({hard_count} hard, baseline {baseline}), "
          f"{words_total} words, {rate} per 100 words")
    print("Hedges/modality (may, might, could) are never flagged: confidence is content.")


def selftest():
    bad = (
        "The panel is removed; spin up the job. "
        "Perform an analysis of the seamless log. "
        "We have received the report."
    )
    findings, _ = lint(bad)
    rules = {f["rule"] for f in findings}
    for expected in ("semicolon", "phrasal-verb", "nominalization",
                     "marketing-adjective", "passive-voice", "present-perfect"):
        assert expected in rules, expected
    # Hedges must never be flagged
    findings, _ = lint(
        "The request may have failed. It could be a timeout. "
        "The disk might have filled."
    )
    assert findings == [], findings
    print("selftest OK")


RULE_IDS = {rule_id for rule_id, *_ in RULES} | {
    "long-sentence", "synonym-rotation", "dangling-conjunction"
}


def _rule_list(value):
    rules = {r for r in value.split(",") if r}
    unknown = rules - RULE_IDS
    if unknown:
        raise argparse.ArgumentTypeError(
            f"unknown rule(s): {', '.join(sorted(unknown))}. "
            f"Known rules: {', '.join(sorted(RULE_IDS))}"
        )
    return rules


def _non_negative_int(value):
    try:
        n = int(value)
    except ValueError:
        n = -1
    if n < 0:
        raise argparse.ArgumentTypeError(
            f"expected a non-negative integer, got {value!r}"
        )
    return n


def main(argv):
    parser = argparse.ArgumentParser(
        prog="ste-lint.py", allow_abbrev=False,
        description="Deterministic linter for the structural STE rules. "
                    "Reads stdin when no FILE is given.",
    )
    parser.add_argument("paths", nargs="*", metavar="FILE")
    parser.add_argument("--json", action="store_true", help="print findings as JSON")
    parser.add_argument("--baseline", type=_non_negative_int, default=0,
                        metavar="N",
                        help="pass unless hard violations exceed N (default 0)")
    parser.add_argument("--disable", type=_rule_list, default=set(),
                        metavar="RULES",
                        help="comma-separated rule IDs to silence")
    parser.add_argument("--selftest", action="store_true",
                        help="run the built-in tests")
    args = parser.parse_intermixed_args(argv)
    if args.selftest:
        selftest()
        return 0
    as_json, baseline, disabled, paths = (
        args.json, args.baseline, args.disable, args.paths
    )
    findings, words_total = [], 0
    if paths:
        for p in paths:
            try:
                with open(p, encoding="utf-8") as fh:
                    text = fh.read()
            except OSError as e:
                parser.error(f"cannot read {p}: {e.strerror}")
            f, w = lint(text, filename=p)
            findings.extend(f)
            words_total += w
    else:
        findings, words_total = lint(sys.stdin.read())
    findings = [f for f in findings if f["rule"] not in disabled]
    hard_count = sum(1 for f in findings if f["level"] == "advisory-free")
    report(findings, words_total, as_json, hard_count, baseline)
    return 1 if hard_count > baseline else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
