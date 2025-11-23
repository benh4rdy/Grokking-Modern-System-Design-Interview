#!/usr/bin/env python3
"""
Generate a consolidated Markdown "ebook" of the repository's documentation and a
minimal PDF rendition without external dependencies.

The script traverses the repository, collects Markdown files, and outputs two
artifacts:

* A combined Markdown file with each source file separated by a heading that
  shows its relative path.
* A PDF created from the combined Markdown text, rendered in a monospaced font
  using a tiny built-in PDF writer (no third-party packages required).
"""
from __future__ import annotations

import argparse
import os
import textwrap
from pathlib import Path
from typing import Iterable, List


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MARKDOWN = REPO_ROOT / "artifacts" / "system-design-ebook.md"
DEFAULT_PDF = REPO_ROOT / "artifacts" / "system-design-ebook.pdf"


def find_markdown_files(root: Path) -> List[Path]:
    """Return a sorted list of Markdown files beneath ``root``.

    The traversal excludes Git internals and the generated ebook files to avoid
    recursion when the script is re-run.
    """

    excluded_names = {".git", "artifacts"}
    collected: List[Path] = []

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in excluded_names and not d.startswith(".")]
        for filename in filenames:
            if not filename.lower().endswith(".md"):
                continue
            candidate = Path(dirpath) / filename
            if candidate.resolve() == DEFAULT_MARKDOWN.resolve():
                continue
            collected.append(candidate)

    collected.sort(key=lambda path: path.relative_to(root).as_posix())
    return collected


def combine_markdown(files: Iterable[Path]) -> str:
    """Combine the supplied Markdown files into a single document string."""

    parts: List[str] = []
    parts.append("# Grokking Modern System Design Interview — Collected Notes\n")
    parts.append(
        "Generated with scripts/build_ebook.py. Each section below mirrors the contents "
        "of a Markdown file from the repository, prefixed with its relative path.\n\n"
    )

    for path in files:
        relative = path.relative_to(REPO_ROOT)
        parts.append(f"## {relative.as_posix()}\n\n")
        text = path.read_text(encoding="utf-8")
        parts.append(text.rstrip() + "\n\n")

    return "".join(parts)


def write_markdown(content: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(content, encoding="utf-8")


def escape_pdf_text(text: str) -> str:
    """Escape characters that are special within PDF text objects."""

    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def chunk_lines_for_pdf(text: str, width: int = 95, max_lines: int = 60) -> List[List[str]]:
    """Wrap the text and break it into page-sized chunks."""

    wrapped_lines: List[str] = []
    for line in text.splitlines():
        if not line:
            wrapped_lines.append("")
            continue
        wrapped_lines.extend(textwrap.wrap(line, width=width))

    pages: List[List[str]] = []
    for start in range(0, len(wrapped_lines), max_lines):
        pages.append(wrapped_lines[start : start + max_lines])
    return pages


def build_pdf_objects(content: str) -> List[str]:
    """Construct PDF objects as strings (without offsets)."""

    pages = chunk_lines_for_pdf(content)
    objects: List[str] = []

    # 1. Catalog
    objects.append("<< /Type /Catalog /Pages 2 0 R >>")

    # Placeholder for pages; will fill Kids later
    # 2. Pages (will be updated after page objects are known)
    pages_obj_index = len(objects)
    objects.append("")

    # 3. Font object (Helvetica)
    objects.append("<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>")

    page_object_ids = []
    content_object_ids = []

    for i, lines in enumerate(pages, start=1):
        content_stream_lines = ["BT", "/F1 10 Tf", "12 TL", "50 780 Td"]
        for line in lines:
            content_stream_lines.append(f"({escape_pdf_text(line)}) Tj")
            content_stream_lines.append("T*")
        content_stream_lines.append("ET")
        content_stream = "\n".join(content_stream_lines)
        content = f"<< /Length {len(content_stream.encode('utf-8'))} >>\nstream\n{content_stream}\nendstream"

        content_obj_id = len(objects) + 1
        objects.append(content)
        content_object_ids.append(content_obj_id)

        page_obj = (
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            "/Resources << /Font << /F1 3 0 R >> >> "
            f"/Contents {content_obj_id} 0 R >>"
        )
        page_obj_id = len(objects) + 1
        objects.append(page_obj)
        page_object_ids.append(page_obj_id)

    kids_entries = " ".join(f"{pid} 0 R" for pid in page_object_ids)
    pages_obj = f"<< /Type /Pages /Count {len(page_object_ids)} /Kids [{kids_entries}] >>"
    objects[pages_obj_index] = pages_obj

    return objects


def write_pdf(content: str, destination: Path) -> None:
    """Write a basic PDF containing the provided text content."""

    objects = build_pdf_objects(content)
    destination.parent.mkdir(parents=True, exist_ok=True)

    with destination.open("wb") as f:
        f.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets: List[int] = []

        for obj_id, obj in enumerate(objects, start=1):
            offsets.append(f.tell())
            obj_bytes = obj.encode("utf-8")
            f.write(f"{obj_id} 0 obj\n".encode("ascii"))
            f.write(obj_bytes)
            f.write(b"\nendobj\n")

        xref_offset = f.tell()
        f.write(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
        f.write(b"0000000000 65535 f \n")
        for offset in offsets:
            f.write(f"{offset:010d} 00000 n \n".encode("ascii"))

        f.write(b"trailer\n")
        f.write(
            f"<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode(
                "ascii"
            )
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a combined Markdown + PDF ebook from repository docs without external dependencies"
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=REPO_ROOT,
        help="Path to the repository root to scan for Markdown files (default: repository root)",
    )
    parser.add_argument(
        "--markdown",
        type=Path,
        default=DEFAULT_MARKDOWN,
        help=f"Path for the combined Markdown output (default: {DEFAULT_MARKDOWN})",
    )
    parser.add_argument(
        "--pdf",
        type=Path,
        default=DEFAULT_PDF,
        help=f"Path for the generated PDF output (default: {DEFAULT_PDF})",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    markdown_files = find_markdown_files(args.root)

    if not markdown_files:
        raise SystemExit("No Markdown files found to include in the ebook.")

    combined = combine_markdown(markdown_files)
    write_markdown(combined, args.markdown)
    write_pdf(combined, args.pdf)

    print(f"Markdown saved to: {args.markdown}")
    print(f"PDF saved to: {args.pdf}")


if __name__ == "__main__":
    main()
