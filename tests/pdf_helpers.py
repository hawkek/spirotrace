"""Build tiny text-layer PDFs by hand for the ingest tests (no report layout, no data).

Only the standard Helvetica font is used, so no font program is embedded
and pdfplumber can read the text back.
"""

from __future__ import annotations

PAGE_W, PAGE_H = 595.0, 842.0


def _pdf_string(text: str) -> str:
    return (
        "(" + text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ")"
    )


def _box(b: tuple[float, float, float, float]) -> str:
    return " ".join(f"{v:g}" for v in b)


def make_pdf(
    pages: list[list[tuple[str, float, float]]],
    rotate: list[int] | None = None,
    *,
    mediabox: tuple[float, float, float, float] | None = None,
    cropbox: tuple[float, float, float, float] | None = None,
) -> bytes:
    """A PDF whose pages carry the given ``(text, x, y)`` items in PDF points.

    ``rotate`` gives a ``/Rotate`` value per page (the content is stored
    sideways and the viewer turns it upright). ``mediabox`` replaces the A4
    MediaBox at the origin and ``cropbox`` adds a CropBox, both as raw PDF
    ``[x0 y0 x1 y1]`` values, on every page.
    """
    rotate = rotate or [0] * len(pages)
    objects: list[bytes] = []

    def add(body: str) -> int:
        objects.append(body.encode("latin-1"))
        return len(objects)

    font = add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    page_ids = []
    kids_placeholder = add("")  # pages tree, filled in below
    for items, rot in zip(pages, rotate, strict=True):
        ops = ["BT", "/F1 10 Tf"]
        for text, x, y in items:
            ops.append(f"1 0 0 1 {x:.2f} {y:.2f} Tm {_pdf_string(text)} Tj")
        ops.append("ET")
        stream = "\n".join(ops)
        content = add(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
        w, h = (PAGE_H, PAGE_W) if rot in (90, 270) else (PAGE_W, PAGE_H)
        boxes = f"/MediaBox [{_box(mediabox) if mediabox else f'0 0 {w} {h}'}]"
        if cropbox:
            boxes += f" /CropBox [{_box(cropbox)}]"
        page = add(
            f"<< /Type /Page /Parent {kids_placeholder} 0 R {boxes} "
            f"/Rotate {rot} /Resources << /Font << /F1 {font} 0 R >> >> /Contents {content} 0 R >>"
        )
        page_ids.append(page)
    kids = " ".join(f"{p} 0 R" for p in page_ids)
    objects[kids_placeholder - 1] = (
        f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode("latin-1")
    )
    catalog = add(f"<< /Type /Catalog /Pages {kids_placeholder} 0 R >>")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode("latin-1") + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("latin-1")
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode("latin-1")
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root {catalog} 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    ).encode("latin-1")
    return bytes(out)
