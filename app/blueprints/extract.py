########################################################################
### EXTRACT -- UPLOAD, TYPE/PAGE SELECTION, REGION-SELECT WIZARD
########################################################################
import fitz
from flask import Blueprint, render_template, request, redirect, url_for, session, Response, abort

from app.extensions import login_required, pdf_processing_limit, save_upload, upload_path, delete_upload, save_result, load_result
from app import docbook

bp = Blueprint("extract", __name__)

### page preview is rendered at this zoom for on-screen display/region-
### select; region coordinates submitted from the browser are in THIS
### image's pixel space and get divided by this same factor to convert
### back to PDF points. Image extraction uses IMAGE_ZOOM instead, both
### for the on-screen preview and the final saved PNG -- deliberately
### high-res since the whole point is a clean crop to save, and using
### the same zoom for preview and final crop means what's drawn is
### what's saved, pixel-for-pixel scale.
PREVIEW_ZOOM = 1.5
IMAGE_ZOOM = 600 / 72  # 600 dpi; PyMuPDF's 1.0 zoom == 72 dpi
THUMBNAIL_ZOOM = 0.3  # first-page sanity check on choose_page.html, not a real preview

TYPE_LABELS = {
    "paragraph": "Paragraph",
    "orderedlist": "Ordered list",
    "itemizedlist": "Unordered list",
    "table": "Table",
    "image": "Image",
}

### cards on the landing page -- order here is the order they're shown
### in. icon_image files and description copy are borrowed from
### old_pdf_xml's tools.html -- no dedicated paragraph icon existed
### there, so that one reuses its process.png (document-with-lines).
TYPE_CARDS = [
    {
        "value": "paragraph",
        "label": "Paragraph",
        "icon_image": "process.png",
        "description": "Convert a paragraph to XML.",
    },
    {
        "value": "orderedlist",
        "label": "Ordered list",
        "icon_image": "list_ordered.png",
        "description": "Convert a numbered list to XML.",
    },
    {
        "value": "itemizedlist",
        "label": "Unordered list",
        "icon_image": "list_unordered.png",
        "description": "Convert a bulleted list to XML.",
    },
    {
        "value": "table",
        "label": "Table",
        "icon_image": "table.png",
        "description": "Convert a table to XML.",
    },
    {
        "value": "image",
        "label": "Extract image",
        "icon_image": "image_extractor.png",
        "description": "PDF region to PNG.",
    },
]


def _open_current_pdf():
    token = session.get("pdf_token")
    path = upload_path(token)
    if path is None:
        return None
    return fitz.open(path)


def _region_zoom():
    return IMAGE_ZOOM if session.get("element_type") == "image" else PREVIEW_ZOOM


### Home -> element type -> current step, current step omitted on
### choose_pdf itself since that IS the element type's landing page
def _breadcrumbs(step_label=None):
    element_label = TYPE_LABELS.get(session.get("element_type"), "")
    items = [("Home", url_for("extract.index"))]
    if not element_label:
        return items
    if step_label is None:
        items.append((element_label, ""))
    else:
        items.append((element_label, url_for("extract.choose_pdf")))
        items.append((step_label, ""))
    return items


@bp.route("/", methods=["GET", "POST"])
@login_required
def index():
    if request.method == "POST":
        element_type = request.form.get("element_type")
        if element_type not in TYPE_LABELS:
            abort(400)
        session["element_type"] = element_type
        session.pop("page_number", None)
        return redirect(url_for("extract.choose_pdf"))

    return render_template("index.html", cards=TYPE_CARDS)


### clears the loaded PDF without touching element_type -- "upload a
### different PDF" from mid-wizard should keep what you're extracting,
### not send you back to pick a type again. new_upload() below is the
### full reset (also clears element_type), for "start over" instead.
def _clear_pdf():
    delete_upload(session.get("pdf_token"))
    session.pop("pdf_token", None)
    session.pop("pdf_filename", None)
    session.pop("page_count", None)
    session.pop("page_number", None)


@bp.route("/extract/pdf")
@login_required
def choose_pdf():
    if "element_type" not in session:
        return redirect(url_for("extract.index"))
    return render_template(
        "upload.html",
        breadcrumbs=_breadcrumbs(),
        element_label=TYPE_LABELS.get(session.get("element_type"), ""),
        pdf_filename=session.get("pdf_filename"),
        page_count=session.get("page_count"),
        replace_pdf=request.args.get("replace") == "1",
        error=None,
    )


@bp.route("/extract/pdf/clear", methods=["POST"])
@login_required
def clear_pdf():
    _clear_pdf()
    return redirect(url_for("extract.choose_pdf"))


@bp.route("/upload", methods=["POST"])
@login_required
@pdf_processing_limit
def upload():
    if "element_type" not in session:
        return redirect(url_for("extract.index"))

    file = request.files.get("pdf")
    if file is None or file.filename == "":
        return render_template(
            "upload.html",
            breadcrumbs=_breadcrumbs(),
            element_label=TYPE_LABELS.get(session.get("element_type"), ""),
            pdf_filename=None,
            page_count=None,
            error="Choose a PDF file first.",
        )

    delete_upload(session.get("pdf_token"))
    token = save_upload(file)

    ### confirm it actually opens as a real PDF -- not just trusting
    ### the extension/content-type
    try:
        doc = fitz.open(upload_path(token))
        page_count = doc.page_count
        doc.close()
    except Exception:
        delete_upload(token)
        return render_template(
            "upload.html",
            breadcrumbs=_breadcrumbs(),
            element_label=TYPE_LABELS.get(session.get("element_type"), ""),
            pdf_filename=None,
            page_count=None,
            error="That doesn't look like a valid PDF.",
        )

    session["pdf_token"] = token
    session["pdf_filename"] = file.filename
    session["page_count"] = page_count
    session.pop("page_number", None)
    return redirect(url_for("extract.choose_page"))


@bp.route("/extract/page", methods=["GET", "POST"])
@login_required
@pdf_processing_limit
def choose_page():
    doc = _open_current_pdf()
    if doc is None or "element_type" not in session:
        return redirect(url_for("extract.index"))
    page_count = doc.page_count
    doc.close()

    error = None
    if request.method == "POST":
        try:
            page_number = int(request.form.get("page_number", ""))
        except ValueError:
            page_number = None
        if page_number is None or not (1 <= page_number <= page_count):
            error = f"Enter a page number between 1 and {page_count}."
        else:
            session["page_number"] = page_number
            return redirect(url_for("extract.select_region"))

    return render_template(
        "choose_page.html",
        breadcrumbs=_breadcrumbs("Choose page"),
        page_count=page_count,
        element_label=TYPE_LABELS.get(session.get("element_type"), ""),
        error=error,
    )


@bp.route("/extract/select", methods=["GET", "POST"])
@login_required
@pdf_processing_limit
def select_region():
    doc = _open_current_pdf()
    if doc is None or "element_type" not in session or "page_number" not in session:
        return redirect(url_for("extract.index"))

    if request.method == "POST":
        zoom = _region_zoom()
        try:
            x0 = float(request.form["x0"]) / zoom
            y0 = float(request.form["y0"]) / zoom
            x1 = float(request.form["x1"]) / zoom
            y1 = float(request.form["y1"]) / zoom
        except (KeyError, ValueError):
            abort(400)
        if x1 <= x0 or y1 <= y0:
            doc.close()
            return render_template(
                "select_region.html",
                breadcrumbs=_breadcrumbs("Select region"),
                page_number=session["page_number"],
                element_type=session.get("element_type"),
                element_label=TYPE_LABELS.get(session.get("element_type"), ""),
                error="Draw a region on the page first.",
            )

        page = doc[session["page_number"] - 1]
        rect = fitz.Rect(x0, y0, x1, y1)
        result = _run_extraction(page, rect, session["element_type"])
        doc.close()
        save_result(session["pdf_token"], result)
        return redirect(url_for("extract.result"))

    doc.close()
    return render_template(
        "select_region.html",
        breadcrumbs=_breadcrumbs("Select region"),
        page_number=session["page_number"],
        element_type=session.get("element_type"),
        element_label=TYPE_LABELS.get(session.get("element_type"), ""),
        error=None,
    )


### an empty selection (or one with no readable text) still produces
### well-formed XML -- e.g. an <informaltable> with no rows -- which
### validates fine but has nothing worth converting. Caught here so
### result.html can show "nothing could be converted" instead of a
### passing validation on empty tags.
def _extraction_is_empty(element_type, preview):
    if element_type == "paragraph":
        return not preview.strip()
    if element_type in ("orderedlist", "itemizedlist"):
        return not preview
    if element_type == "table":
        rows = ([preview["header"]] if preview["header"] else []) + preview["body"]
        return not any(cell.strip() for row in rows for cell in row)
    return False


### image extraction skips the DocBook fragment entirely -- the PNG
### goes straight into a CMS that assigns xml:id and metadata itself,
### so there's nothing here to build or validate. It's rendered
### on-demand by extracted_image() from result["rect"], not stored.
def _run_extraction(page, rect, element_type):
    result = {"element_type": element_type, "rect": list(rect), "page_number": session["page_number"]}

    if element_type == "paragraph":
        text, xml = docbook.extract_paragraph(page, rect)
        result["preview"] = text
        result["xml"] = xml
    elif element_type in ("orderedlist", "itemizedlist"):
        items, xml = docbook.extract_list(page, rect, ordered=(element_type == "orderedlist"))
        result["preview"] = items
        result["xml"] = xml
    elif element_type == "table":
        rows, xml = docbook.extract_table(page, rect)
        result["preview"] = rows
        result["xml"] = xml
    elif element_type == "image":
        return result
    else:
        abort(400)

    result["empty"] = _extraction_is_empty(element_type, result["preview"])
    if result["empty"]:
        result["valid"], result["validation_message"] = None, None
    else:
        result["valid"], result["validation_message"] = docbook.validate_fragment(result["xml"])

    return result


@bp.route("/extract/result")
@login_required
def result():
    result_data = load_result(session.get("pdf_token"))
    if result_data is None:
        return redirect(url_for("extract.index"))
    return render_template(
        "result.html",
        breadcrumbs=_breadcrumbs("Result"),
        result=result_data,
        element_label=TYPE_LABELS.get(result_data["element_type"], ""),
    )


@bp.route("/extract/thumbnail")
@login_required
@pdf_processing_limit
def thumbnail():
    doc = _open_current_pdf()
    if doc is None:
        abort(404)
    page = doc[0]
    pix = page.get_pixmap(matrix=fitz.Matrix(THUMBNAIL_ZOOM, THUMBNAIL_ZOOM))
    png_bytes = pix.tobytes("png")
    doc.close()
    return Response(png_bytes, mimetype="image/png")


@bp.route("/extract/page-image")
@login_required
@pdf_processing_limit
def page_image():
    doc = _open_current_pdf()
    if doc is None or "page_number" not in session:
        abort(404)
    page = doc[session["page_number"] - 1]
    zoom = _region_zoom()
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    png_bytes = pix.tobytes("png")
    doc.close()
    return Response(png_bytes, mimetype="image/png")


@bp.route("/extract/image")
@login_required
@pdf_processing_limit
def extracted_image():
    result_data = load_result(session.get("pdf_token"))
    if result_data is None or result_data["element_type"] != "image":
        abort(404)
    doc = _open_current_pdf()
    if doc is None:
        abort(404)
    page = doc[result_data["page_number"] - 1]
    rect = fitz.Rect(*result_data["rect"])
    png_bytes = docbook.extract_image(page, rect, zoom=IMAGE_ZOOM)
    doc.close()
    return Response(png_bytes, mimetype="image/png")


### back to drawing a new region on the same PDF/page/type -- select_region
### itself falls back to index if any of those are no longer in session
@bp.route("/extract/another", methods=["POST"])
@login_required
def extract_another():
    return redirect(url_for("extract.select_region"))


@bp.route("/new-upload", methods=["POST"])
@login_required
def new_upload():
    _clear_pdf()
    session.pop("element_type", None)
    return redirect(url_for("extract.index"))
