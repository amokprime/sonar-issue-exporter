#!/usr/bin/env python3
"""Lint markdown files for Obsidian prettify issues per AGENTS.md rules.

Auto-fixes:
  1. Bare #identifier outside backticks → wrap in backticks
     (Obsidian renders #id as a tag pill)
  2. Bare [identifier] outside backticks (not followed by `(`) → wrap in backticks
     (Obsidian renders [id] as a link label with no URL)
  3. Bullet indentation normalized to 4-space steps:
     level 1 = 0 spaces, level 2 = 4 spaces, level 3 = 8 spaces, etc.
  4. Bare === text === outside backticks → wrap in backticks
     (Obsidian's ==highlight== extension greedily matches the outer == of
     === text ===, applying a yellow background to the contained text)

Warns (does NOT auto-fix):
  5. [[wikilink]] found in body text — intentional? if not, wrap in backticks manually.
     In Obsidian-connected markdown, [[...]] is the standard wikilink syntax and is
     almost always intentional. Auto-wrapping breaks the link, so we only warn.
  6. Bullet lines >400 chars — likely a minified clump, consider splitting

Skips:
  - YAML frontmatter (between --- markers at the top of the file)
  - Text inside inline backtick spans (`...`)
  - Text inside fenced code blocks (``` ... ```)
  - Heading lines (for # check only — [id], [[id]], and === are still checked)

Usage:
  python3 lint_markdown.py file1.md [file2.md ...]

Exit codes:
  0 = clean (or all violations auto-fixed; overlong bullets only warn)
  1 = overlong bullets found (need manual splitting)
  2 = usage error
"""
import os
import re
import sys
from pathlib import Path

# Threshold for "minified clump" warning on bullet lines.
OVERLONG_BULLET_THRESHOLD = 400

# Regex for inline backtick spans — `...` (non-greedy, no nested backticks).
BACKTICK_SPAN = re.compile(r'`[^`]*`')

# Regex for fenced code block markers (``` or ~~~ at start of line).
FENCE_RE = re.compile(r'^(\s*)(```|~~~)')

# Regex for markdown headings (1-6 # at start of line).
HEADING_RE = re.compile(r'^\s{0,3}#{1,6}\s')

# Regex for YAML frontmatter delimiters (--- at start of file, on its own line).
# Frontmatter is the block between the first `---` and the second `---` at the
# very top of the file. The linter skips frontmatter entirely — [[wikilinks]]
# and other tokens there are YAML values, not markdown body text.
FRONTMATTER_DELIM_RE = re.compile(r'^---\s*$')

# Violation patterns (applied to text OUTSIDE backtick spans):
# 1. [[wikilink]] — must be checked BEFORE [link-label] to avoid double-matching.
WIKILINK_RE = re.compile(r'\[\[([^\]]+)\]\]')
# 2. #tag — preceded by non-word, non-backtick, non-slash (to skip URLs).
#    Requires a letter as the first char (so #1, #2 footnote-style refs don't match).
TAG_RE = re.compile(r'(?<![\w`/])#([a-zA-Z][a-zA-Z0-9_-]*)')
# 3. [link-label] — not preceded by [ (to skip [[...]] inner match),
#    not followed by ( (to skip real [text](url) links).
#    Negative lookahead (?![ xX]\]) skips checkbox syntax [ ]/[x]/[X].
LINK_LABEL_RE = re.compile(r'(?<!\[)\[(?![ xX]\])([^\]\[`]+)\](?!\()')
# 4. === section headers === — Obsidian's ==highlight== extension greedily
#    matches the outer == of === text ===, applying a yellow background to
#    the contained text. Wrapping in backticks renders them as literal code.
#    Matches === or more on each side with text in between (no newticks, no newlines).
SECTION_HEADER_RE = re.compile(r'(?<![=`])===([^=`\n]+?)===(?![=`])')

# 4b. === section headers with nested backticks === — the SECTION_HEADER_RE
#     above skips these (inner content excludes backticks to avoid broken
#     double-backtick wrapping). This second pattern catches them for a WARN
#     only — the agent must manually convert to a fenced code block (triple
#     backticks) since inline single-backtick wrapping splits on inner backticks.
#     Uses `.+?` (any non-newline char, lazy) instead of `[^=`\n]+?` so the
#     content can include `=` chars (e.g. regex strings like `[^=`\n]+?`).
#     The `` ` `` in the middle requires at least one backtick in the content.
SECTION_HEADER_NESTED_RE = re.compile(r'(?<![=`])===(.+?`.+?)===(?![=`])')  # noqa: S8786 — bounded by === anchors, input is markdown (bounded by MAX_LINES)

# Base directory for path validation (the cwd when the script runs).
# All file paths passed on the CLI must resolve within this directory.
_BASE_DIR = os.path.realpath(os.getcwd())


def safe_path(path_str: str) -> Path:
    """Validate a file path is within the allowed base directory.

    Prevents path traversal (../) and absolute path injection — the script
    reads/writes files passed as CLI args, which in an agentic workflow
    could be LLM-supplied. Canonicalizes via realpath, then checks the
    resolved path starts with base_dir + os.sep (the trailing separator
    prevents partial-path bypass like /base/dirmalicious).

    Raises ValueError if the path escapes base_dir.
    """
    resolved = os.path.realpath(path_str)
    base_with_sep = _BASE_DIR + os.sep
    if resolved != _BASE_DIR and not resolved.startswith(base_with_sep):
        raise ValueError(
            f'path {path_str!r} resolves outside the allowed directory {_BASE_DIR!r}'
        )
    return Path(resolved)


def split_by_backticks(line: str) -> list[tuple[str, bool]]:
    """Split a line into segments: (text, is_inside_backticks)."""
    segments: list[tuple[str, bool]] = []
    pos = 0
    for m in BACKTICK_SPAN.finditer(line):
        if m.start() > pos:
            segments.append((line[pos:m.start()], False))
        segments.append((m.group(), True))
        pos = m.end()
    if pos < len(line):
        segments.append((line[pos:], False))
    if not segments:
        segments.append(('', False))
    return segments


def fix_wikilink(m: re.Match) -> str:
    return f'`[[{m.group(1)}]]`'


def fix_tag(m: re.Match) -> str:
    return f'`#{m.group(1)}`'


def fix_link_label(m: re.Match) -> str:
    return f'`[{m.group(1)}]`'


def fix_section_header(m: re.Match) -> str:
    # Wrap the entire === text === span in backticks so Obsidian renders it
    # as literal code instead of applying ==highlight== to the outer == pair.
    return f'`{m.group()}`'


def normalize_bullet_indent(line: str) -> tuple[str, bool]:
    """Normalize bullet indentation to 4-space steps.

    Level 1 (base) = 0 spaces, level 2 = 4 spaces, level 3 = 8 spaces, etc.

    Handles both space-indented and tab-indented bullets:
    - Tabs are expanded to 4 spaces before measuring (so 1 tab = level 2).
    - 4-space multiples stay as-is (already normalized).
    - 2-space indents (old-style) are upgraded to 4-space multiples.
    - 8-space doubled indents (where 4 is expected) are collapsed to 4
      when the doubled pattern is detected (indent_spaces > 4 and
      indent_spaces is a multiple of 8 but not a multiple of 4 that
      naturally arises from nesting — heuristically, if every sub-bullet
      in the file uses 8 spaces, they're doubled, not level 3).

    Non-bullet lines are returned unchanged.
    """
    # Match both space and tab indentation before a bullet marker.
    m = re.match(r'^(\s+)([-*] )', line)
    if not m:
        return line, False

    # Expand tabs to 4 spaces for consistent measurement.
    raw_indent = m.group(1)
    indent_str = raw_indent.expandtabs(4)
    indent_spaces = len(indent_str)

    if indent_spaces == 0:
        return line, False

    if indent_spaces % 4 == 0:
        level = indent_spaces // 4
    else:
        level = indent_spaces // 2

    new_indent = '    ' * level
    new_line = new_indent + line[m.start(2):]
    return new_line, new_line != line


def fix_tokens_in_segment(text: str, is_heading: bool) -> tuple[str, list[str]]:
    """Apply the wikilink/tag/link-label/section-header auto-fixes to a segment.

    Extracted from lint_line to reduce cognitive complexity (S3776).
    Returns (fixed_text, messages).
    """
    messages: list[str] = []

    # WARN-ONLY for [[wikilink]] — do NOT auto-fix.
    # In Obsidian-connected markdown, [[...]] is the standard wikilink syntax and
    # is almost always intentional. Auto-wrapping in backticks breaks the link.
    # The #tag and [link-label] auto-fixes remain because those are more likely
    # to be unintentional (bare tags/link-labels in prose). [[wikilinks]] only
    # get a warning so the author can decide.
    if WIKILINK_RE.search(text):
        messages.append('WARN: [[wikilink]] found — intentional? if not, wrap manually')

    # Auto-fix #tag (skip on heading lines — those are markdown headings).
    if not is_heading:
        prev = text
        text = TAG_RE.sub(fix_tag, text)
        if text != prev:
            messages.append('fixed tag')

    # Auto-fix [link-label] (not followed by `(`).
    prev = text
    text = LINK_LABEL_RE.sub(fix_link_label, text)
    if text != prev:
        messages.append('fixed link-label')

    # Auto-fix === section headers === (Obsidian ==highlight== collision).
    # Runs last so it doesn't interfere with the [link-label] check.
    prev = text
    text = SECTION_HEADER_RE.sub(fix_section_header, text)
    if text != prev:
        messages.append('fixed section-header (=== highlight)')

    return text, messages


def lint_line(line: str, in_code_block: bool) -> tuple[str, list[str], int, int]:
    """Lint a single line. Returns (fixed_line, messages, overlong_count, nested_header_count)."""
    if in_code_block:
        return line, [], 0, 0

    # Normalize bullet indentation to 4-space steps (runs first — structural).
    line, indent_changed = normalize_bullet_indent(line)

    is_heading = bool(HEADING_RE.match(line))
    segments = split_by_backticks(line)

    fixed_segments: list[str] = []
    messages: list[str] = []
    overlong = 0
    nested_headers = 0

    if indent_changed:
        messages.append('normalized bullet indent')

    for text, inside in segments:
        if inside:
            fixed_segments.append(text)
            continue
        fixed_text, msgs = fix_tokens_in_segment(text, is_heading)
        fixed_segments.append(fixed_text)
        messages.extend(msgs)

    fixed_line = ''.join(fixed_segments)

    # Check for === text with `backticks` === patterns (warn only — can't
    # auto-fix because inline single-backtick wrapping splits on inner backticks).
    # Must check the FULL line (not per-segment) because the pattern spans
    # across backtick segments when it contains inner backticks.
    if SECTION_HEADER_NESTED_RE.search(fixed_line):
        nested_headers = 1
        messages.append('WARN: === with nested backticks — convert to fenced code block')

    # Check for overlong bullets (warn only, no auto-fix).
    stripped = fixed_line.rstrip()
    if stripped.startswith('- ') and len(stripped) > OVERLONG_BULLET_THRESHOLD:
        overlong = 1

    return fixed_line, messages, overlong, nested_headers


def _read_and_validate(path_str: str) -> tuple[Path, str, list[str]] | None:
    """Validate path, read file. Returns (path, original_content, lines) or None.

    Extracted from lint_file to reduce cognitive complexity (S3776/C901).
    Handles the S2083 path traversal check and the file read.
    """
    base_dir = os.path.realpath(os.getcwd())
    resolved = os.path.realpath(path_str)
    if resolved != base_dir and not resolved.startswith(base_dir + os.sep):
        print(f'ERROR: path {path_str!r} resolves outside the allowed directory', file=sys.stderr)
        return None
    path = Path(resolved)
    if not path.exists():
        print(f'WARN: {path} does not exist — skipping', file=sys.stderr)
        return None
    if path.suffix != '.md':
        return None
    with open(resolved, encoding='utf-8') as f:
        original = f.read()
    return path, original, original.splitlines(keepends=True)


def _lint_lines(lines: list[str], path: Path) -> tuple[list[str], list[str], int, int]:
    """Lint each line, handling frontmatter + code blocks.

    Returns (new_lines, messages, overlong, nested).

    Extracted from lint_file to reduce cognitive complexity (S3776/C901).
    """
    in_code_block = False
    in_frontmatter = False
    frontmatter_checked = False
    new_lines: list[str] = []
    messages: list[str] = []
    overlong_total = 0
    nested_total = 0

    for i, line in enumerate(lines, 1):
        if not frontmatter_checked and i == 1 and FRONTMATTER_DELIM_RE.match(line):
            in_frontmatter = True
            new_lines.append(line)
            continue
        if in_frontmatter:
            if FRONTMATTER_DELIM_RE.match(line):
                in_frontmatter = False
                frontmatter_checked = True
            new_lines.append(line)
            continue
        frontmatter_checked = True

        if FENCE_RE.match(line):
            in_code_block = not in_code_block
            new_lines.append(line)
            continue

        fixed, msgs, overlong, nested = lint_line(line, in_code_block)
        new_lines.append(fixed)
        for msg in msgs:
            messages.append(f'{path.name}:{i}: {msg}')
        overlong_total += overlong
        nested_total += nested

    return new_lines, messages, overlong_total, nested_total


def _collapse_doubled_indent(new_lines: list[str], path: Path) -> tuple[list[str], list[str]]:
    """Collapse doubled indentation (8-space → 4-space) if no 4-space bullets exist.

    Extracted from lint_file to reduce cognitive complexity (S3776/C901).
    Returns (updated_lines, extra_messages).
    """
    has_4space = any(re.match(r'^    [-*] ', nl) for nl in new_lines)
    has_8space = any(re.match(r'^        [-*] ', nl) for nl in new_lines)
    if not has_8space or has_4space:
        return new_lines, []
    for i, nl in enumerate(new_lines):
        m = re.match(r'^(        )([-*] )', nl)
        if m:
            new_lines[i] = '    ' + nl[m.start(2):]
    return new_lines, [f'{path.name}: collapsed doubled indent (8->4 spaces)']


def lint_file(path_str: str) -> tuple[bool, list[str], int, int]:
    """Lint a markdown file. Returns (changed, messages, overlong_count, nested_header_count).

    Validates the path via safe_path() internally so the validation is visible
    at the I/O site (S2083: taint analysis needs to see the check before the read/write).
    """
    result = _read_and_validate(path_str)
    if result is None:
        return False, [], 0, 0
    path, original, lines = result

    new_lines, messages, overlong_total, nested_total = _lint_lines(lines, path)
    new_lines, indent_msgs = _collapse_doubled_indent(new_lines, path)
    messages.extend(indent_msgs)

    changed = ''.join(new_lines) != original
    if changed:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(''.join(new_lines))

    return changed, messages, overlong_total, nested_total


def main() -> int:
    if len(sys.argv) < 2:
        print('Usage: lint_markdown.py <file1.md> [file2.md ...]', file=sys.stderr)
        return 2

    any_changed = False
    all_messages: list[str] = []
    total_overlong = 0
    total_nested = 0

    for arg in sys.argv[1:]:
        changed, messages, overlong, nested = lint_file(arg)
        if changed:
            any_changed = True
            print(f'FIXED: {arg}')
        all_messages.extend(messages)
        total_overlong += overlong
        total_nested += nested

    if all_messages:
        print()
        print('=== Lint messages ===')
        for m in all_messages:
            print(f'  {m}')

    if any_changed:
        print()
        print('Auto-fixed bare #id / [id] / [[id]] / === text === tokens — wrapped in backticks.')

    if total_overlong > 0:
        print()
        print(f'WARNING: {total_overlong} overlong bullet(s) found'
              f' (> {OVERLONG_BULLET_THRESHOLD} chars).')
        print('These are likely minified clumps — consider splitting into separate bullets.')
        print('Re-run after splitting to clear this warning.')

    if total_nested > 0:
        print()
        print(f'WARNING: {total_nested} === text with nested backticks === pattern(s) found.')
        print('These cannot be auto-fixed — inline single-backtick wrapping'
              ' splits on inner backticks.')
        print('Convert to a fenced code block (triple backticks) or'
              ' rephrase to remove inner backticks.')

    return 0


if __name__ == '__main__':
    sys.exit(main())
