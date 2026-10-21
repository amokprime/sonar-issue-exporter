#!/usr/bin/env python3
"""Split overlong bullet lines in a markdown file at natural break points.

Splits lines >400 chars that start with '- ' or '  - ' by inserting sub-bullets
at natural break points: after '; ', after '. ' (when followed by a capital),
or after ', ' before a '**bold**' marker.

Only splits if the result has at least 2 bullets each under 400 chars.
Otherwise leaves the line as-is (the linter will keep warning).
"""
import os
import re
import sys
from pathlib import Path

THRESHOLD = 400

# Base directory for path validation (the cwd when the script runs).
_BASE_DIR = os.path.realpath(os.getcwd())


def safe_path(path_str: str) -> Path:
    """Validate a file path is within the allowed base directory.

    Prevents path traversal (../) and absolute path injection — the script
    reads/writes files passed as CLI args, which in an agentic workflow
    could be LLM-supplied. Canonicalizes via realpath, then checks the
    resolved path starts with base_dir + os.sep (the trailing separator
    prevents partial-path bypass like /base/dirmalicious).
    """
    resolved = os.path.realpath(path_str)
    base_with_sep = _BASE_DIR + os.sep
    if resolved != _BASE_DIR and not resolved.startswith(base_with_sep):
        raise ValueError(
            f'path {path_str!r} resolves outside the allowed directory {_BASE_DIR!r}'
        )
    return Path(resolved)


def _parse_bullet(line: str) -> tuple[str, str, str] | None:
    """Extract (indent, bullet_marker, content) from a bullet line.

    Returns None if the line is not a bullet.
    """
    stripped = line.lstrip()
    indent = line[:len(line) - len(stripped)]
    if stripped.startswith('- '):
        return indent, '- ', stripped[2:]
    if stripped.startswith('  - '):
        indent = line[:line.index('- ')]
        return indent, '- ', stripped[2:]
    return None


def _try_split(
    content: str, pattern: str, indent: str, bullet: str, suffix: str = ''
) -> list[str] | None:
    """Try splitting content at pattern boundaries.

    Returns the split lines if successful (all under THRESHOLD), or None.
    The first part keeps the original bullet marker; subsequent parts use
    sub-bullet indentation. Suffix is appended to each non-last part
    (e.g. ';' or '.').
    """
    parts = re.split(pattern, content)
    if len(parts) <= 1:
        return None

    result = [indent + bullet + parts[0].rstrip() + suffix]
    for p in parts[1:-1]:
        result.append(indent + '  - ' + p.rstrip() + suffix)
    result.append(indent + '  - ' + parts[-1].rstrip())

    if all(len(r.rstrip()) <= THRESHOLD for r in result):
        return result
    return None


def _try_bold_split(content: str, indent: str, bullet: str) -> list[str] | None:
    """Try splitting at '**...**' bold markers (new sub-topic)."""
    parts = re.split(r'(?=\*\*)', content)
    if len(parts) <= 1:
        return None

    intro = parts[0].rstrip()
    if len(intro) <= 10:  # not a meaningful intro
        return None

    result = [indent + bullet + intro]
    for p in parts[1:]:
        p = p.rstrip()
        if p:
            result.append(indent + '  - ' + p)

    if all(len(r.rstrip()) <= THRESHOLD for r in result):
        return result
    return None


def split_bullet(line: str) -> list[str]:
    """Try to split a bullet line into multiple sub-bullets.

    Returns the split lines if successful, or [line] if no good split
    point was found.
    """
    if len(line.rstrip()) <= THRESHOLD:
        return [line]

    parsed = _parse_bullet(line)
    if parsed is None:
        return [line]
    indent, bullet, content = parsed

    # Try splitting at '; ' boundaries
    result = _try_split(content, r'; (?=[A-Z`*])', indent, bullet, ';')
    if result:
        return result

    # Try splitting at '. ' boundaries (sentence end)
    result = _try_split(content, r'\. (?=[A-Z`*])', indent, bullet, '.')
    if result:
        return result

    # Try splitting at '**...**' bold markers
    result = _try_bold_split(content, indent, bullet)
    if result:
        return result

    # Try splitting at ', ' before a backtick-quoted token
    result = _try_split(content, r', (?=`)', indent, bullet, ',')
    if result:
        return result

    # Couldn't find a good split point
    return [line]


def _process_file(path_str: str) -> tuple[int, int]:
    """Read, split overlong bullets, and write back. Returns (split_count, remaining).

    Validates the path via safe_path() internally so the validation is visible
    at the I/O site (S2083: taint analysis needs to see the check before the read/write).
    """
    # Path traversal defense (S2083): resolve to canonical path, then verify
    # it's within the allowed base directory (cwd). The resolved path is used
    # for ALL I/O — the original user input is never passed to open/read/write.
    base_dir = os.path.realpath(os.getcwd())
    resolved = os.path.realpath(path_str)
    if resolved != base_dir and not resolved.startswith(base_dir + os.sep):
        raise ValueError(f'path {path_str!r} resolves outside the allowed directory')
    # Use the validated resolved path — NOT the original user input
    with open(resolved, encoding='utf-8') as f:
        lines = f.read().splitlines(keepends=True)

    new_lines: list[str] = []
    split_count = 0
    remaining = 0

    for line in lines:
        stripped = line.rstrip('\n')
        is_bullet = stripped.lstrip().startswith('- ') or '  - ' in stripped[:10]
        if is_bullet and len(stripped) > THRESHOLD:
            split = split_bullet(stripped)
            if len(split) > 1:
                new_lines.extend(s + '\n' for s in split)
                split_count += 1
            else:
                new_lines.append(line)
                remaining += 1
        else:
            new_lines.append(line)

    # Write using the validated resolved path
    with open(resolved, 'w', encoding='utf-8') as f:
        f.write(''.join(new_lines))
    return split_count, remaining


def main() -> int:
    if len(sys.argv) < 2:
        print('Usage: split_bullets.py <file.md>', file=sys.stderr)
        return 1

    split_count, remaining = _process_file(sys.argv[1])
    print(f'Split {split_count} overlong bullets. {remaining} remain'
          ' (no natural break point found).')
    return 0 if remaining == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
