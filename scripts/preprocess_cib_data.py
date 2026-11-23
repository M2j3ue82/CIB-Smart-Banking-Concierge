#!/usr/bin/env python3
"""
preprocess_cib_data.py
======================
Prepare the CIB knowledge base (Markdown) for vector-store ingestion.

What it does
------------
1. Reads ``cib_knowledge_base.md`` (UTF-8).
2. Cleans the text: Unicode normalisation, invisible characters, Arabic tatweel,
   line endings, stray whitespace and repeated blank lines.
3. Splits the file into sections (one section per ``## Heading``).
4. Reads and VALIDATES the YAML-style metadata block of every section
   (required keys, allowed categories, unique ids, valid source URL and date).
5. Splits long sections into chunks, repeating the section title in each chunk so
   a chunk never loses its context.
6. Writes:
   * ``cib_chunks.json``         a JSON array, one object per chunk
                                 (``chunk_id``, ``text``, ``metadata``, ``char_count``)
   * ``cib_chunks_report.json``  counts, warnings and errors of the run

Design notes
------------
* Standard library only: no ``pip install`` is needed for this script.
* The metadata block is flat ``key: value`` text, so a tiny parser is enough and
  avoids a YAML dependency.
* Exit code is 0 on success, 1 if validation errors were found (the chunks file
  is NOT written in that case, so a broken knowledge base is never ingested).

Usage
-----
    python scripts\\preprocess_cib_data.py
    python scripts\\preprocess_cib_data.py --input D:\\CIB-Project\\cib_knowledge_base.md --max-chars 900
    python scripts\\preprocess_cib_data.py --strict
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

LOG = logging.getLogger("preprocess_cib_data")

# ----------------------------------------------------------------------------
# Validation rules (edit here if the knowledge-base schema changes)
# ----------------------------------------------------------------------------
REQUIRED_KEYS = ("product_id", "product_name_en", "category", "language", "source", "last_verified")
ALLOWED_CATEGORIES = {
    "credit_cards",
    "certificates_of_deposit",
    "loans",
    "digital_banking",
    "emergency_protocols",
    "not_available",  # the "information not available" guardrail section
}
SOURCE_PREFIX = "https://www.cibeg.com/"
ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")  # kebab-case
# A section without a metadata block is accepted only if its title matches this.
GUARDRAIL_TITLE = re.compile(r"غير\s+متوفرة")

# Characters removed during cleaning: zero-width, bidi controls, BOM, tatweel.
INVISIBLE = re.compile("[\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff\u0640]")
YAML_BLOCK = re.compile(r"```ya?ml\s*\n(.*?)\n```", re.DOTALL)
BULLET = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+")


@dataclass
class Section:
    title: str
    body: str
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def error(self, msg: str) -> None:
        self.errors.append(msg)
        LOG.error(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)
        LOG.warning(msg)


# ----------------------------------------------------------------------------
# Step 1: cleaning
# ----------------------------------------------------------------------------
def clean_text(raw: str) -> str:
    """Normalise a Markdown string without changing its meaning."""
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = unicodedata.normalize("NFC", text)
    text = INVISIBLE.sub("", text)
    text = text.replace("\u00a0", " ")  # non-breaking space -> normal space
    lines = [re.sub(r"[ \t]+$", "", line) for line in text.split("\n")]  # trailing spaces
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)  # at most one blank line in a row
    return text.strip() + "\n"


# ----------------------------------------------------------------------------
# Step 2: parsing
# ----------------------------------------------------------------------------
def split_sections(text: str) -> tuple[str, list[Section]]:
    """Return (preamble, sections). A section starts at a line beginning with '## '."""
    preamble_lines: list[str] = []
    sections: list[Section] = []
    current_title: str | None = None
    current_lines: list[str] = []
    in_fence = False

    def flush() -> None:
        if current_title is not None:
            sections.append(Section(current_title, "\n".join(current_lines).strip()))

    for line in text.split("\n"):
        if line.strip().startswith("```"):
            in_fence = not in_fence
        if not in_fence and line.startswith("## "):
            flush()
            current_title = line[3:].strip()
            current_lines = []
        elif current_title is None:
            preamble_lines.append(line)
        else:
            current_lines.append(line)
    flush()
    return "\n".join(preamble_lines).strip(), sections


def parse_metadata(section: Section) -> None:
    """Extract the ``yaml`` block, store it in ``section.metadata`` and strip it from the body."""
    match = YAML_BLOCK.search(section.body)
    if not match:
        return
    for line in match.group(1).split("\n"):
        if not line.strip() or line.strip().startswith("#"):
            continue
        key, sep, value = line.partition(":")
        if not sep:
            continue  # reported later as a missing key if it was required
        section.metadata[key.strip()] = value.strip()
    section.body = (section.body[: match.start()] + section.body[match.end():]).strip()
    section.body = re.sub(r"\n{3,}", "\n\n", section.body)
    section.body = re.sub(r"^---\s*$", "", section.body, flags=re.MULTILINE).strip()


# ----------------------------------------------------------------------------
# Step 3: validation
# ----------------------------------------------------------------------------
def validate_sections(sections: list[Section], report: Report, max_age_days: int, today: date) -> None:
    seen_ids: dict[str, str] = {}
    for sec in sections:
        where = f"section '{sec.title}'"
        meta = sec.metadata

        if not meta:
            if GUARDRAIL_TITLE.search(sec.title):
                meta.update(
                    product_id="not-available-details",
                    product_name_en="Information not available",
                    category="not_available",
                    language="ar",
                    source=SOURCE_PREFIX,
                    last_verified=today.isoformat(),
                )
                report.warn(f"{where}: no metadata block, default guardrail metadata applied")
            else:
                report.error(f"{where}: missing metadata block")
            continue

        missing = [k for k in REQUIRED_KEYS if not meta.get(k)]
        if missing:
            report.error(f"{where}: missing metadata keys: {', '.join(missing)}")
            continue

        pid = meta["product_id"]
        if not ID_PATTERN.match(pid):
            report.error(f"{where}: product_id '{pid}' is not kebab-case (a-z, 0-9, hyphens)")
        if pid in seen_ids:
            report.error(f"{where}: duplicate product_id '{pid}' (also used by '{seen_ids[pid]}')")
        seen_ids[pid] = sec.title

        if meta["category"] not in ALLOWED_CATEGORIES:
            report.error(f"{where}: unknown category '{meta['category']}'")
        if meta["language"] != "ar":
            report.error(f"{where}: language must be 'ar', got '{meta['language']}'")
        if not meta["source"].startswith(SOURCE_PREFIX):
            report.error(f"{where}: source must start with {SOURCE_PREFIX}")

        try:
            verified = date.fromisoformat(meta["last_verified"])
        except ValueError:
            report.error(f"{where}: last_verified '{meta['last_verified']}' is not an ISO date (YYYY-MM-DD)")
        else:
            if verified > today:
                report.error(f"{where}: last_verified {verified} is in the future")
            elif (today - verified).days > max_age_days:
                report.warn(f"{where}: last_verified is {(today - verified).days} days old (limit {max_age_days})")

        if not sec.body:
            report.error(f"{where}: empty body")


# ----------------------------------------------------------------------------
# Step 4: chunking
# ----------------------------------------------------------------------------
def chunk_section(sec: Section, max_chars: int) -> list[str]:
    """Return the text of each chunk. The title is repeated in every chunk."""
    header = sec.title
    full = f"{header}\n{sec.body}".strip()
    if len(full) <= max_chars:
        return [full]

    # Group lines into blocks: a bullet and its continuation lines stay together.
    blocks: list[str] = []
    for line in sec.body.split("\n"):
        if not line.strip():
            continue
        if BULLET.match(line) or not blocks:
            blocks.append(line)
        else:
            blocks[-1] += "\n" + line

    chunks: list[str] = []
    current = header
    for block in blocks:
        if len(current) + 1 + len(block) > max_chars and current != header:
            chunks.append(current)
            current = header
        current += "\n" + block
    if current != header:
        chunks.append(current)
    return chunks


def build_chunks(sections: list[Section], max_chars: int, source_file: str) -> list[dict]:
    result: list[dict] = []
    for sec in sections:
        parts = chunk_section(sec, max_chars)
        for index, text in enumerate(parts, start=1):
            pid = sec.metadata["product_id"]
            result.append(
                {
                    "chunk_id": f"{pid}-{index:02d}",
                    "text": text,
                    "char_count": len(text),
                    "metadata": {
                        **sec.metadata,
                        "section_title": sec.title,
                        "part": index,
                        "parts_total": len(parts),
                        "source_file": source_file,
                    },
                }
            )
    return result


# ----------------------------------------------------------------------------
# Orchestration
# ----------------------------------------------------------------------------
def process_text(raw: str, max_chars: int, max_age_days: int, strict: bool,
                 source_file: str = "cib_knowledge_base.md", today: date | None = None):
    """Pure function used by main() and by the unit tests."""
    today = today or date.today()
    report = Report()
    text = clean_text(raw)
    preamble, sections = split_sections(text)
    if not sections:
        report.error("no '## ' sections found in the file")
    for sec in sections:
        parse_metadata(sec)
    validate_sections(sections, report, max_age_days, today)
    if strict and report.warnings:
        report.error(f"--strict: {len(report.warnings)} warning(s) treated as errors")
    chunks = [] if report.errors else build_chunks(sections, max_chars, source_file)
    return preamble, sections, chunks, report


def find_default_input(root: Path) -> Path:
    for candidate in (root / "knowledge_base" / "cib_knowledge_base.md", root / "cib_knowledge_base.md"):
        if candidate.exists():
            return candidate
    return root / "knowledge_base" / "cib_knowledge_base.md"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    p = argparse.ArgumentParser(description="Clean, validate and chunk the CIB knowledge base.")
    p.add_argument("--input", type=Path, default=find_default_input(root), help="knowledge base Markdown file")
    p.add_argument("--output", type=Path, default=root / "data" / "processed" / "cib_chunks.json",
                   help="output JSON array of chunks")
    p.add_argument("--max-chars", type=int, default=1000, help="maximum characters per chunk (default 1000)")
    p.add_argument("--max-age-days", type=int, default=90, help="warn if last_verified is older (default 90)")
    p.add_argument("--strict", action="store_true", help="treat warnings as errors")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(message)s")

    if not args.input.exists():
        LOG.error("input file not found: %s", args.input)
        return 1
    raw_bytes = args.input.read_bytes()
    raw = raw_bytes.decode("utf-8-sig")  # tolerates a BOM written by Notepad

    preamble, sections, chunks, report = process_text(
        raw, args.max_chars, args.max_age_days, args.strict, source_file=args.input.name
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    report_path = args.output.with_name(args.output.stem + "_report.json")
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "input_file": str(args.input),
        "input_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "max_chars": args.max_chars,
        "sections": len(sections),
        "chunks": len(chunks),
        "preamble_chars": len(preamble),
        "errors": report.errors,
        "warnings": report.warnings,
        "ok": not report.errors,
    }
    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    if report.errors:
        LOG.error("validation failed: %d error(s). Chunks file NOT written. See %s", len(report.errors), report_path)
        return 1

    args.output.write_text(json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")
    LOG.info("OK: %d sections -> %d chunks (%d warning(s))", len(sections), len(chunks), len(report.warnings))
    LOG.info("chunks: %s", args.output)
    LOG.info("report: %s", report_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
