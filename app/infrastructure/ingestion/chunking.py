"""Lightweight recursive-ish text chunker (no extra dependency).

Splits on paragraph boundaries first, then packs paragraphs into character
windows with a small overlap. Good enough to mirror the external service's
``recursive`` macro splitter for the local pgvector fallback.
"""

from __future__ import annotations

import re

_PARAGRAPH_RE = re.compile(r"\n\s*\n")


def chunk_text(text: str, *, chunk_size: int = 1200, overlap: int = 150) -> list[str]:
    text = text.strip()
    if not text:
        return []

    paragraphs = [p.strip() for p in _PARAGRAPH_RE.split(text) if p.strip()]
    chunks: list[str] = []
    current = ""

    for para in paragraphs:
        if len(para) > chunk_size:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_split_long(para, chunk_size=chunk_size, overlap=overlap))
            continue
        if not current:
            current = para
        elif len(current) + 2 + len(para) <= chunk_size:
            current = f"{current}\n\n{para}"
        else:
            chunks.append(current)
            current = _carry_overlap(current, overlap) + para

    if current:
        chunks.append(current)
    return chunks


def _carry_overlap(text: str, overlap: int) -> str:
    if overlap <= 0 or not text:
        return ""
    tail = text[-overlap:]
    return f"{tail}\n\n"


def _split_long(text: str, *, chunk_size: int, overlap: int) -> list[str]:
    step = max(1, chunk_size - overlap)
    return [text[i : i + chunk_size] for i in range(0, len(text), step)]
