#!/usr/bin/env python3
"""Prepare and validate Auris versions without third-party dependencies."""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VERSION_FILE = ROOT / "VERSION"
DEFAULT_CHANGELOG_FILE = ROOT / "CHANGELOG.md"
VERSION_PATTERN = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$"
)
HEADING_PATTERN = re.compile(
    r"^## \[(Unreleased|(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*))\]"
    r"(?: - (\d{4}-\d{2}-\d{2}))?[ \t]*$",
    re.MULTILINE,
)
LANGUAGE_HEADING_PATTERN = re.compile(r"^### (Magyar|English)[ \t]*$", re.MULTILINE)


def parse_version(value: str) -> tuple[int, int, int]:
    """Return strict MAJOR.MINOR.PATCH components."""
    match = VERSION_PATTERN.fullmatch(value.strip())
    if not match:
        raise ValueError(f"Érvénytelen verzió: {value!r}; MAJOR.MINOR.PATCH szükséges.")
    return tuple(int(part) for part in match.groups())


def next_version(current: str, level: str) -> str:
    """Calculate the next Auris version for a patch, minor, or major change."""
    major, minor, patch = parse_version(current)
    if level == "patch":
        patch += 1
    elif level == "minor":
        minor, patch = minor + 1, 0
    elif level == "major":
        major, minor, patch = major + 1, 0, 0
    else:
        raise ValueError("A szint patch, minor vagy major lehet.")
    return f"{major}.{minor}.{patch}"


def _read_version(path: Path) -> str:
    value = path.read_text(encoding="utf-8").strip()
    parse_version(value)
    return value


def _read_changelog(path: Path) -> str:
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    if not text.endswith("\n"):
        text += "\n"
    return text


def _section(text: str, name: str) -> tuple[re.Match[str], str]:
    headings = list(HEADING_PATTERN.finditer(text))
    for index, heading in enumerate(headings):
        if heading.group(1) != name:
            continue
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        return heading, text[heading.end():end].strip()
    raise ValueError(f"A CHANGELOG.md nem tartalmazza ezt a szakaszt: {name}")


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="\n", dir=path.parent, delete=False
    ) as handle:
        handle.write(text)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _validate_bilingual(body: str, section: str) -> None:
    """Require explicit Hungarian and English release-note sections."""
    languages = set(LANGUAGE_HEADING_PATTERN.findall(body))
    if languages != {"Magyar", "English"}:
        raise ValueError(
            f"A(z) {section} szakasznak ### Magyar és ### English részt is "
            "tartalmaznia kell."
        )


def prepare_release(
    version_path: Path,
    changelog_path: Path,
    level: str,
    release_date: str | None = None,
) -> str:
    """Promote the Unreleased changelog body and update VERSION."""
    current = _read_version(version_path)
    target = next_version(current, level)
    date_value = release_date or dt.date.today().isoformat()
    try:
        dt.date.fromisoformat(date_value)
    except ValueError as exc:
        raise ValueError("A dátum YYYY-MM-DD alakú legyen.") from exc

    text = _read_changelog(changelog_path)
    heading, body = _section(text, "Unreleased")
    if not body:
        raise ValueError("Az Unreleased szakasz üres; nincs mit kiadni.")
    _validate_bilingual(body, "Unreleased")
    if any(item.group(1) == target for item in HEADING_PATTERN.finditer(text)):
        raise ValueError(f"A {target} verzió már szerepel a CHANGELOG.md fájlban.")

    headings = list(HEADING_PATTERN.finditer(text))
    next_start = next(
        (item.start() for item in headings if item.start() > heading.start()),
        len(text),
    )
    updated = (
        text[:heading.start()]
        + "## [Unreleased]\n\n"
        + f"## [{target}] - {date_value}\n\n"
        + body
        + "\n\n"
        + text[next_start:].lstrip("\n")
    )
    if not updated.endswith("\n"):
        updated += "\n"

    _write_atomic(changelog_path, updated)
    _write_atomic(version_path, target + "\n")
    return target


def release_notes(changelog_path: Path, version: str) -> str:
    """Extract one release body from CHANGELOG.md."""
    parse_version(version)
    _, body = _section(_read_changelog(changelog_path), version)
    if not body:
        raise ValueError(f"A {version} kiadási szakasz üres.")
    _validate_bilingual(body, version)
    return body


def validate_release(
    version_path: Path,
    changelog_path: Path,
    tag: str | None = None,
) -> str:
    """Validate VERSION, changelog state, and an optional Git tag."""
    version = _read_version(version_path)
    release_notes(changelog_path, version)
    _, pending = _section(_read_changelog(changelog_path), "Unreleased")
    if pending:
        raise ValueError(
            "Az Unreleased szakasz nem üres; futtasd a prepare parancsot tagelés előtt."
        )
    if tag is not None and tag != f"v{version}":
        raise ValueError(f"A tag ({tag}) nem egyezik a VERSION értékével (v{version}).")
    return version


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("current", help="Az aktuális verzió kiírása.")
    next_parser = sub.add_parser("next", help="A következő verzió kiszámítása.")
    next_parser.add_argument("level", choices=("patch", "minor", "major"))
    prepare = sub.add_parser("prepare", help="Az Unreleased szakasz lezárása.")
    prepare.add_argument("level", choices=("patch", "minor", "major"))
    prepare.add_argument("--date", dest="release_date")
    check = sub.add_parser("check", help="A kiadási állapot ellenőrzése.")
    check.add_argument("--tag")
    notes = sub.add_parser("notes", help="Egy kiadás jegyzeteinek kiírása.")
    notes.add_argument("--version")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "current":
            print(_read_version(DEFAULT_VERSION_FILE))
        elif args.command == "next":
            print(next_version(_read_version(DEFAULT_VERSION_FILE), args.level))
        elif args.command == "prepare":
            print(
                prepare_release(
                    DEFAULT_VERSION_FILE,
                    DEFAULT_CHANGELOG_FILE,
                    args.level,
                    args.release_date,
                )
            )
        elif args.command == "check":
            print(validate_release(DEFAULT_VERSION_FILE, DEFAULT_CHANGELOG_FILE, args.tag))
        elif args.command == "notes":
            version = args.version or _read_version(DEFAULT_VERSION_FILE)
            print(release_notes(DEFAULT_CHANGELOG_FILE, version))
    except (OSError, ValueError) as exc:
        print(f"Hiba: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
