"""Text splitting utilities for knowledge chunking."""

from __future__ import annotations

from typing import List, Tuple


MAX_CHUNK_CHARS_DEFAULT = 2000
CHUNK_OVERLAP_DEFAULT = 300


def split_logical_sections(text: str) -> List[str]:
    """Split text into logical sections based on headings and blank lines."""
    lines = text.splitlines()
    sections: list[list[str]] = []
    current: list[str] = []

    def _is_heading(line: str) -> bool:
        stripped = line.lstrip()
        return stripped.startswith("#") or (
            stripped.startswith("**") and stripped.endswith("**")
        )

    for line in lines:
        if _is_heading(line) and current:
            sections.append(current)
            current = [line]
        else:
            current.append(line)
    if current:
        sections.append(current)

    # Join lines back into paragraphs
    return ["\n".join(section).strip() for section in sections if "".join(section).strip()]


def recursive_char_split(
    text: str,
    max_len: int = MAX_CHUNK_CHARS_DEFAULT,
    overlap: int = CHUNK_OVERLAP_DEFAULT,
) -> List[str]:
    """Split text by characters with fixed size and overlap."""
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    start = 0
    length = len(text)

    while start < length:
        end = min(start + max_len, length)
        chunk = text[start:end]
        chunks.append(chunk)
        if end == length:
            break
        start = max(0, end - overlap)

    return chunks


def chunk_knowledge(
    title: str,
    content: str,
    max_chunk_chars: int = MAX_CHUNK_CHARS_DEFAULT,
    overlap: int = CHUNK_OVERLAP_DEFAULT,
) -> List[Tuple[str, str]]:
    """Chunk knowledge content into (title, content) pairs."""
    # First try logical sections
    logical_sections = split_logical_sections(content)
    if not logical_sections:
        logical_sections = [content]

    chunks: list[tuple[str, str]] = []

    for section in logical_sections:
        if len(section) <= max_chunk_chars:
            chunks.append((title, section))
            continue

        # Fallback to recursive char split for large sections
        for part in recursive_char_split(section, max_len=max_chunk_chars, overlap=overlap):
            chunks.append((title, part))

    # Add "Part X" suffix for subsequent chunks
    titled_chunks: list[tuple[str, str]] = []
    for idx, (t, c) in enumerate(chunks, start=1):
        if idx == 1:
            titled_chunks.append((t, c))
        else:
            titled_chunks.append((f"{t} – Part {idx}", c))

    return titled_chunks

