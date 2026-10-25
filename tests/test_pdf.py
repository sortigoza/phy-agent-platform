from phy.read.flatten import pdf_text


def tiny_pdf(pages: list[list[bytes]]) -> bytes:
    """A minimal PDF: one Helvetica text line per entry, 20 pt apart, on each page."""
    page_ids = [4 + 2 * i for i in range(len(pages))]
    objects = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: b"<< /Type /Pages /Kids [%s] /Count %d >>"
        % (b" ".join(b"%d 0 R" % i for i in page_ids), len(pages)),
        3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    }
    for page_id, lines in zip(page_ids, pages, strict=True):
        ops = b"BT /F1 12 Tf 72 720 Td " + b" 0 -20 Td ".join(b"(%s) Tj" % s for s in lines)
        stream = ops + b" ET"
        objects[page_id] = (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 3 0 R >> >> /Contents %d 0 R >>" % (page_id + 1)
        )
        objects[page_id + 1] = b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream)
    out = bytearray(b"%PDF-1.4\n")
    offsets = {}
    for number in sorted(objects):
        offsets[number] = len(out)
        out += b"%d 0 obj\n%s\nendobj\n" % (number, objects[number])
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for number in sorted(objects):
        out += b"%010d 00000 n \n" % offsets[number]
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return bytes(out)


def test_pdf_pages_are_separated_by_form_feeds(tmp_path):
    path = tmp_path / "paper.pdf"
    path.write_bytes(tiny_pdf([[b"First page."], [b"Second page."]]))

    text = pdf_text(path)

    assert text.split("\f") == ["First page.", "Second page."]


def test_hyphenated_line_breaks_are_joined(tmp_path):
    path = tmp_path / "paper.pdf"
    path.write_bytes(tiny_pdf([[b"The configu-", b"ration space."]]))

    assert pdf_text(path) == "The configuration space."


def test_soft_hyphens_at_line_ends_are_stripped(tmp_path):
    path = tmp_path / "paper.pdf"
    path.write_bytes(tiny_pdf([[b"auto\xad", b"correlation time"]]))

    assert pdf_text(path) == "autocorrelation time"


def test_nfkc_is_applied(tmp_path):
    path = tmp_path / "paper.pdf"
    # WinAnsi 0x85 is the ellipsis character, which NFKC turns into three dots.
    path.write_bytes(tiny_pdf([[b"and so on\x85"]]))

    assert pdf_text(path) == "and so on..."
