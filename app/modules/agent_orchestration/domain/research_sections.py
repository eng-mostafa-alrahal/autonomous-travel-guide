"""Split concatenated DeepSearch reports into labeled sections."""

from __future__ import annotations

import re

_H2 = re.compile(r"^##\s+(.+)$", re.MULTILINE)
_SLUG = re.compile(r"[^a-z0-9]+")


def topic_slug(label: str) -> str:
    slug = _SLUG.sub("_", label.strip().lower()).strip("_")
    return slug or "destination"


def split_research_sections(raw: str) -> list[tuple[str, str]]:
    """Split concatenated DeepSearch reports on markdown H2 headings.

    The knowledge builder prefixes each cluster with ``## {label}``. Reports
    without headings are returned as a single section so nothing is dropped.
    """
    text = (raw or "").strip()
    if not text:
        return []
    matches = list(_H2.finditer(text))
    if not matches:
        return [("full_destination_research", text)]

    sections: list[tuple[str, str]] = []
    lead = text[: matches[0].start()].strip()
    if lead:
        sections.append(("preamble", lead))
    for i, match in enumerate(matches):
        label = match.group(1).strip() or f"section_{i + 1}"
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if body:
            sections.append((label, body))
    return sections or [("full_destination_research", text)]
