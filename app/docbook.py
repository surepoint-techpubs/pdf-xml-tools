########################################################################
### DOCBOOK -- REGION-SCOPED EXTRACTION + FRAGMENT GENERATION
###
### Every builder except extract_image() returns (preview, xml) --
### preview is plain structured data (a string, or a list of
### strings/rows) for the result template to render as real HTML via
### Jinja (auto-escaped there, not here); xml is the serialized
### DocBook fragment text, deliberately without its own xmlns -- it's
### meant to be pasted into an existing namespaced document, not stand
### alone. extract_image() returns just the PNG bytes -- extracted
### images go straight into a CMS that assigns xml:id and metadata
### itself, so there's no fragment to build.
########################################################################
import os
import re

import fitz
from lxml import etree

SCHEMA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "schema", "docbook.rng")
DOCBOOK_NS = "http://docbook.org/ns/docbook"

### a bullet/number marker, either alone on its own line (PyMuPDF often
### extracts a bullet glyph as a separate line from the item text that
### follows it) or prefixing text on the same line -- e.g. "•" alone,
### or "1. First item" together. Marker text is capped at 4 chars so a
### real word ending in a period ("bracket.") on its own wrapped line
### doesn't get mistaken for a marker and dropped -- covers digits,
### single letters, and roman numerals up to "viii.". Best-effort: the
### result is always in an editable textarea for exactly this reason.
_MARKER_ONLY_RE = re.compile(r"^\s*(?:[•\-\*◦▪‣]|\(?[a-zA-Z0-9]{1,4}[\.\)])\s*$")
_MARKER_PREFIX_RE = re.compile(r"^\s*(?:[•\-\*◦▪‣]|\(?[a-zA-Z0-9]{1,4}[\.\)])\s+")


def _serialize(elem):
    return etree.tostring(elem, pretty_print=True, encoding="unicode").strip()


### page-spanning watermarks are rotated text; real content in these
### documents is always axis-aligned. Drop non-axis-aligned lines here
### rather than cleaning them up after the fact -- even a watermark
### line clipped down to a stray fragment by rect still carries its
### original (rotated) direction vector.
_ROTATED_DIR_THRESHOLD = 0.01


### clip= itself can corrupt line reconstruction when the clip boundary
### partially cuts through a rotated watermark -- confirmed empirically:
### a marker+text line split apart and lost its punctuation, only for
### certain clip sizes over this page's watermark, not for a tight
### clip, a full-height clip, or no clip at all. Extracting the whole
### page once and filtering by line center in Python sidesteps it.
###
### Split into a fetch (page.get_text, the expensive part) and a filter
### (_filter_lines, pure Python) so callers that need many regions off
### the same page -- table cells, one call per cell -- fetch once and
### filter many times instead of re-parsing the whole page per region.
def _filter_lines(text_dict, rect):
    lines = []
    for block in text_dict["blocks"]:
        for line in block.get("lines", []):
            bbox = line["bbox"]
            center = ((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)
            if center not in rect:
                continue
            dir_x, dir_y = line["dir"]
            if abs(dir_x * dir_y) > _ROTATED_DIR_THRESHOLD:
                continue
            text = "".join(span["text"] for span in line["spans"]).strip()
            if text:
                lines.append(text)
    return lines


def _region_lines(page, rect):
    return _filter_lines(page.get_text("dict"), rect)


########################################################################
### PARAGRAPH -- wrapped lines joined into one continuous block, not
### one <para> per visual line.
def extract_paragraph(page, rect):
    text = " ".join(_region_lines(page, rect))
    elem = etree.Element("para")
    elem.text = text
    return text, _serialize(elem)


########################################################################
### LISTS -- a line starting with a bullet/number marker begins a new
### item; anything after that (wrapped continuation lines) joins the
### current item, until the next marker. Lines before the first marker
### are discarded, not folded into a bogus leading item -- a selection
### box that overshoots the top and catches a bit of the heading above
### the list is normal, not a sign that heading is part of the list.
def _split_list_items(lines):
    items = []
    current = []
    in_list = False
    for line in lines:
        if _MARKER_ONLY_RE.match(line):
            if current:
                items.append(" ".join(current))
            current = []
            in_list = True
        elif _MARKER_PREFIX_RE.match(line):
            if current:
                items.append(" ".join(current))
            current = [_MARKER_PREFIX_RE.sub("", line, count=1)]
            in_list = True
        elif in_list:
            current.append(line)
    if current:
        items.append(" ".join(current))
    return items


def extract_list(page, rect, ordered):
    items = _split_list_items(_region_lines(page, rect))
    tag = "orderedlist" if ordered else "itemizedlist"
    root = etree.Element(tag)
    for item_text in items:
        listitem = etree.SubElement(root, "listitem")
        para = etree.SubElement(listitem, "para")
        para.text = item_text
    return items, _serialize(root)


########################################################################
### TABLE -- page.find_tables() scoped to the selected region. Falls
### back to one single-cell row if nothing's detected, rather than
### erroring out -- something to start editing beats nothing.
###
### Cell text is rebuilt per-cell via _region_lines() rather than
### table.extract()'s own text, so the watermark filter applies here
### too -- extract() reads straight from the page and picks up the
### same stray watermark fragments paragraphs/lists had.
def extract_table(page, rect):
    finder = page.find_tables(clip=rect)
    if finder.tables:
        table = finder.tables[0]
        text_dict = page.get_text("dict")  # fetched once, reused for every cell below
        rows = [_table_row_text(text_dict, row) for row in table.rows]
        has_header = _has_reliable_header(page, table)
    else:
        whole_text = " ".join(_region_lines(page, rect))
        rows = [[whole_text]] if whole_text else [[""]]
        has_header = False

    root = etree.Element("informaltable", frame="box", rules="all")

    header_row = None
    body_rows = rows
    if has_header:
        header_row = rows[0]
        body_rows = rows[1:]
        thead = etree.SubElement(root, "thead")
        _append_row(thead, header_row, "th")

    tbody = etree.SubElement(root, "tbody")
    for row in body_rows:
        _append_row(tbody, row, "td")

    preview = {"header": header_row, "body": body_rows}
    return preview, _serialize(root)


def _table_row_text(text_dict, row):
    return [" ".join(_filter_lines(text_dict, fitz.Rect(cell))) if cell else "" for cell in row.cells]


def _append_row(parent, row, cell_tag):
    row_elem = etree.SubElement(parent, "tr")
    for cell in row:
        cell_elem = etree.SubElement(row_elem, cell_tag)
        para = etree.SubElement(cell_elem, "para")
        para.text = cell


### PyMuPDF's table.header always assumes a header exists -- absent
### contrary evidence it falls back to "the top row is the header",
### which fires just as readily on a plain data grid as a real one.
### Only trust it when the top row is actually bold and the row below
### isn't -- the same signal real headers in these documents use.
_BOLD_HEADER_THRESHOLD = 0.5


def _row_bold_fraction(page, bbox):
    text_dict = page.get_text("dict", clip=fitz.Rect(bbox), flags=fitz.TEXTFLAGS_TEXT)
    spans = [s for b in text_dict["blocks"] for l in b.get("lines", []) for s in l["spans"] if s["text"].strip()]
    if not spans:
        return None
    return sum(1 for s in spans if s["flags"] & fitz.TEXT_FONT_BOLD) / len(spans)


def _has_reliable_header(page, table):
    if table.row_count < 2:
        return False
    top_bold = _row_bold_fraction(page, table.rows[0].bbox)
    next_bold = _row_bold_fraction(page, table.rows[1].bbox)
    return top_bold is not None and top_bold > _BOLD_HEADER_THRESHOLD and next_bold == 0.0


########################################################################
### IMAGE -- renders the selected region directly (WYSIWYG with what
### was drawn), not a lookup of the original embedded image object.
### zoom is the caller's call, not a default here -- extract.py renders
### the on-screen crop preview and this final PNG at the same zoom, so
### what's drawn is what's saved, pixel-for-pixel. Must be a fitz.Matrix,
### not a plain (zoom, zoom) tuple -- combined with clip=, a bare tuple
### silently renders at 1:1 instead of applying the zoom.
def extract_image(page, rect, zoom):
    pix = page.get_pixmap(clip=rect, matrix=fitz.Matrix(zoom, zoom))
    return pix.tobytes("png")


########################################################################
### VALIDATION -- wrap the fragment in the minimal valid DocBook 5
### container for its type and validate against the vendored schema.
### Returns (is_valid, message).
_WRAP = '<article xmlns="{ns}" version="5.2"><title>x</title>{fragment}</article>'


def validate_fragment(xml_fragment):
    wrapped = _WRAP.format(ns=DOCBOOK_NS, fragment=xml_fragment)
    schema = etree.RelaxNG(etree.parse(SCHEMA_PATH))
    document = etree.fromstring(wrapped.encode("utf-8"))
    if schema.validate(document):
        return True, "Valid DocBook 5."
    return False, str(schema.error_log.last_error)
