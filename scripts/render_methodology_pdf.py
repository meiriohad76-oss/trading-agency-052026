from __future__ import annotations

import re
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path


PAGE_WIDTH = 612
PAGE_HEIGHT = 792
MARGIN_X = 54
MARGIN_TOP = 54
MARGIN_BOTTOM = 54


@dataclass(frozen=True)
class StyledLine:
    text: str
    font: str
    size: int
    leading: int
    before: int = 0


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("Usage: render_methodology_pdf.py INPUT.md OUTPUT.pdf", file=sys.stderr)
        return 2
    input_path = Path(argv[1])
    output_path = Path(argv[2])
    lines = markdown_to_lines(input_path.read_text(encoding="utf-8"))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(build_pdf(lines))
    return 0


def markdown_to_lines(markdown: str) -> list[StyledLine]:
    output: list[StyledLine] = []
    in_code = False
    for raw in markdown.splitlines():
        line = raw.rstrip()
        if line.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            output.extend(_wrap(line, width=98, font="F3", size=7, leading=9))
            continue
        if not line:
            output.append(StyledLine("", "F1", 9, 8))
            continue
        if line.startswith("# "):
            output.extend(_wrap(_clean(line[2:]), width=50, font="F2", size=18, leading=22, before=6))
            continue
        if line.startswith("## "):
            output.extend(_wrap(_clean(line[3:]), width=62, font="F2", size=14, leading=18, before=8))
            continue
        if line.startswith("### "):
            output.extend(_wrap(_clean(line[4:]), width=72, font="F2", size=11, leading=14, before=6))
            continue
        if _is_table_separator(line):
            continue
        if line.startswith("|"):
            output.extend(_wrap(_clean_table(line), width=112, font="F3", size=6, leading=8))
            continue
        if line.startswith("- "):
            output.extend(_wrap("- " + _clean(line[2:]), width=88, font="F1", size=9, leading=12))
            continue
        if re.match(r"^\d+\. ", line):
            output.extend(_wrap(_clean(line), width=88, font="F1", size=9, leading=12))
            continue
        output.extend(_wrap(_clean(line), width=90, font="F1", size=9, leading=12))
    return output


def _wrap(
    text: str,
    *,
    width: int,
    font: str,
    size: int,
    leading: int,
    before: int = 0,
) -> list[StyledLine]:
    if not text:
        return [StyledLine("", font, size, leading, before)]
    wrapped = textwrap.wrap(
        text,
        width=width,
        break_long_words=False,
        break_on_hyphens=False,
        replace_whitespace=False,
    ) or [text]
    return [
        StyledLine(part, font, size, leading, before if index == 0 else 0)
        for index, part in enumerate(wrapped)
    ]


def _clean(text: str) -> str:
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\*\*([^*]*)\*\*", r"\1", text)
    return text.replace("|", "/").strip()


def _clean_table(line: str) -> str:
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    return " | ".join(_clean(cell) for cell in cells)


def _is_table_separator(line: str) -> bool:
    return bool(re.match(r"^\|\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?$", line))


def build_pdf(lines: list[StyledLine]) -> bytes:
    pages: list[list[tuple[StyledLine, int]]] = [[]]
    y = PAGE_HEIGHT - MARGIN_TOP
    for line in lines:
        y -= line.before
        if y - line.leading < MARGIN_BOTTOM:
            pages.append([])
            y = PAGE_HEIGHT - MARGIN_TOP - line.before
        pages[-1].append((line, y))
        y -= line.leading

    objects: list[bytes] = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    page_object_ids: list[int] = []
    content_object_ids: list[int] = []
    first_page_obj_id = 6
    for index, page in enumerate(pages):
        page_object_ids.append(first_page_obj_id + index * 2)
        content_object_ids.append(first_page_obj_id + index * 2 + 1)
    kids = " ".join(f"{page_id} 0 R" for page_id in page_object_ids)
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode("ascii"))
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>")

    for page_id, content_id, page in zip(page_object_ids, content_object_ids, pages, strict=True):
        page_obj = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_WIDTH} {PAGE_HEIGHT}] "
            f"/Resources << /Font << /F1 3 0 R /F2 4 0 R /F3 5 0 R >> >> "
            f"/Contents {content_id} 0 R >>"
        )
        objects.append(page_obj.encode("ascii"))
        stream = _content_stream(page)
        objects.append(
            b"<< /Length "
            + str(len(stream)).encode("ascii")
            + b" >>\nstream\n"
            + stream
            + b"\nendstream"
        )

    return _assemble(objects)


def _content_stream(page: list[tuple[StyledLine, int]]) -> bytes:
    chunks: list[str] = []
    for line, y in page:
        if not line.text:
            continue
        chunks.append(
            f"BT /{line.font} {line.size} Tf 1 0 0 1 {MARGIN_X} {y} Tm "
            f"({_escape_pdf_text(line.text)}) Tj ET"
        )
    return "\n".join(chunks).encode("latin-1", errors="replace")


def _escape_pdf_text(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
        .replace("\t", "    ")
    )


def _assemble(objects: list[bytes]) -> bytes:
    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode("ascii"))
        output.extend(obj)
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f\n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n\n".encode("ascii"))
    output.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(output)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
