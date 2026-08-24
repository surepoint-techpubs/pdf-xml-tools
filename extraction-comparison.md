# Extraction approach: old_pdf_xml vs PDF-XML

Comparing `old_pdf_xml/app.py` (771 lines, one monolithic Flask app,
bundled Windows `.exe` binaries for ImageMagick/Ghostscript/Tesseract)
against this app's `app/docbook.py` + `app/blueprints/extract.py`
(PyMuPDF only, no external binaries).

## Bottom line

The new app is more correct and more secure everywhere it re-implements
something the old app did. The old app has exactly one real capability
the new app lacks outright: **OCR fallback for scanned/image-only PDFs**.
Everything else the old app does differently is a tradeoff, not a
strict win -- covered per-element below.

## Per-element comparison

### Paragraphs / text

- **Old** (`/scrape`): pulls `page.get_text("blocks")`, keeps blocks
  inside the middle 80% of the page (drops top/bottom 10% as
  header/footer), joins block text with newlines. A **separate** step
  (`/create-paras`) then turns the result into XML -- one `<para>` per
  *line*, not per logical paragraph. A prose paragraph that wraps
  across 4 lines becomes 4 separate `<para>` tags.
- **New** (`extract_paragraph`): joins every line in the selected
  region into one space-joined string, one `<para>` for the whole
  selection.
- **Verdict**: new app's one-paragraph-per-selection is correct for
  flowing prose (the common case) but can't cleanly represent content
  that's genuinely line-structured (e.g. an address block) without the
  user drawing multiple small selections. Old app's per-line splitting
  is the opposite problem -- correct for line-structured content,
  wrong for wrapped prose (explodes one paragraph into many). Neither
  is strictly better; new app's choice matches this app's stated
  purpose (converting body prose) better.

### Lists

- **Old** (`/extract-list`): marker regex is similar in spirit
  (bullet/dash/number prefix), but list *items* preserve internal
  paragraph structure -- a blank line inside one bullet's wrapped text
  starts a new `<para>` within the same `<listitem>`, rather than
  getting silently joined. New app's `_split_list_items()` only
  supports single-paragraph items; a blank line isn't treated specially.
- **Old** also has a **content-based boilerplate filter** --
  regex-blocklists `confidential|proprietary|draft|do not distribute`
  in any line and drops it. New app instead filters by *geometry*
  (rotated-text detection in `_region_lines`), matching how watermark
  stamps actually render (diagonal), regardless of wording.
- **Old has an OCR fallback here specifically**: if
  `page.get_text(..., clip=clip)` comes back empty, it rasters the
  clipped region at 2.5x, grayscale + hard-thresholds it (binarize at
  180), and runs `pytesseract.image_to_string(..., config="--psm 6")`.
  New app has no equivalent -- a scanned list region just extracts
  nothing (now correctly reported as "Nothing could be converted"
  rather than silently validating empty, but still can't actually read
  it).
- **Verdict**: multi-paragraph list items are a real, if narrow, gap.
  The OCR fallback is the bigger one. The watermark filtering is a
  wash -- old app's approach catches non-rotated stamps a geometry
  filter would miss; new app's catches rotated stamps regardless of
  wording, and won't accidentally eat a real line that happens to
  contain "draft" as a normal word.

### Tables

- **Old** (`/extract-table`): pdfplumber's `extract_table()` on a
  cropped page region. Header detection: first row's cells all contain
  a letter *and* no digit (`table_has_header_row`). Cell cleaning
  (`clean_table_cell`) drops any line that's a single letter --
  presumably a crude watermark-stray-character filter, but it'll just
  as happily eat a legitimate single-letter cell (a grade column of
  "A"/"B"/"C", for instance).
- **New** (`extract_table`): PyMuPDF's `find_tables()`, falling back to
  one single-cell row if nothing's detected rather than erroring.
  Header detection is bold-fraction based (top row >50% bold, next row
  0% bold) -- tied to how headers actually *look*, not word patterns,
  but only fires if the source PDF actually bolds its headers.
  Watermark filtering reuses the same rotation-geometry filter as
  everything else, applied per-cell.
- **No OCR fallback on either side** for tables -- if there's no text
  layer, old app just raises "No table was found."
- **Verdict**: new app's fallback (emit *something* rather than error
  out) is friendlier than old app's hard failure. Header heuristics are
  differently fragile (bold-styling vs letters-no-digits) -- neither
  dominates; a table with an unstyled header defeats the new app's
  check, a data table with an all-alpha, no-digit first row defeats the
  old app's. Old app's single-letter cell filter is a real correctness
  risk the new app doesn't share.

### Images

- **Old** has two entirely different image paths:
  1. **"Image Extractor"** (`/extract`, Workflow 1): shells out to
     bundled ImageMagick+Ghostscript to raster the *entire page* at 600
     DPI -- no region selection up front. Cropping happens afterward in
     the separate Image Crop tool.
  2. **"PDF Scraper"** (`/scrape`, Workflow 2): auto-detects every
     embedded image on the page via `get_image_info()`, merges
     adjacent/overlapping boxes, and renders each one as its own
     cropped PNG at 300 DPI -- alongside the page's body text -- in one
     combined result. No manual region-drawing at all for this path.
- **New** (`extract_image`): draw one region on the page, get exactly
  that clip rendered at 600/72 zoom directly via PyMuPDF, no
  intermediate whole-page raster and no external binaries.
- **Verdict**: new app's direct clip-to-PNG is strictly more efficient
  for "I want this one region" (the common case) and drops the
  ImageMagick/Ghostscript dependency entirely. The real gap is old
  app's **auto-detect-all-images-on-a-page** mode -- new app has no way
  to pull every embedded image off a page in one action; it's always
  one manually-drawn region at a time. Worth having if a page routinely
  has many small figures to pull at once; not worth it just to match
  feature-for-feature.

## Cross-cutting differences (not per-element)

- **XML validity**: new app builds XML via `lxml` and validates every
  fragment against the real DocBook 5 RelaxNG schema (`xmllint`)
  before showing Valid/Invalid. Old app builds XML via raw string
  concatenation + `html.escape()` on cell/text content, with **no
  validation step at all** -- a malformed fragment would just ship.
  Clear improvement.
- **Authentication**: old app has **none** -- no login, no session, no
  admin concept, every route open to anyone who can reach it. New
  app's whole account/bcrypt/lockout/admin-role system is a from-
  scratch addition, not a port of anything. Given this app is headed
  for a building-wide LAN, this alone would have been disqualifying to
  carry forward as-is.
- **External binaries / portability**: old app bundles Windows `.exe`
  builds of ImageMagick, Ghostscript, and Tesseract and was packaged
  via PyInstaller (`make_exe.py`) as a Windows desktop-style app. None
  of that runs on the target Raspberry Pi without swapping in Linux
  binaries for all three. New app's "PyMuPDF only, no external
  binaries" choice (already called out in `requirements.txt`) was the
  right call for this deployment target independent of any quality
  comparison.
- **Temp-file lifecycle -- directly relevant to the open TODO item**:
  old app's pattern is more sophisticated than what's currently
  planned. It tracks an `ACTIVE_TEMP_FILES` dict of per-file
  last-seen timestamps, updated by `mark_temp_files_active()` whenever
  a file is actually served (`/temp/<filename>`) or pinged by a
  JS heartbeat (`/temp-activity`, called periodically while a page is
  open). `cleanup_temp_files()` only deletes a file once *both* its
  tracked last-active time *and* its on-disk mtime are past a 10-minute
  grace window, and it's called at the top of nearly every route
  (`prepare_temp_route()`) -- so it re-sweeps on almost every request
  instead of only at process start. Net effect: an abandoned upload
  gets cleaned up within ~10 minutes regardless of overall traffic, but
  a file someone's actively working with (sitting on the crop tool,
  say) survives past the grace window because the frontend keeps
  refreshing its "last seen" time. This is a better shape than "sweep
  on upload" for the TODO item -- worth adapting the mark-active/
  release/heartbeat pattern rather than reinventing it, especially
  since it also directly solves that TODO's other concern (don't
  invalidate a file the user is still actively using).

## Worth adopting

- **The active-file-tracking + heartbeat temp-sweep pattern**, adapted
  into the upload-sweep TODO item already filed.
- **OCR fallback** (tesseract) for regions with no text layer -- real
  capability gap, but a real dependency addition (tesseract binary +
  `pytesseract` + `Pillow` image thresholding) and slower per-request;
  worth a deliberate yes/no rather than folding into the sweep fix.
- **Multi-paragraph list items** (blank-line-separated `<para>`s within
  one `<listitem>`) -- small, contained change to
  `_split_list_items()` if it turns out real source documents need it.

## Not worth reverting to

- Bundled Windows binaries / no Linux path for ImageMagick+Ghostscript.
- No authentication.
- No XML schema validation.
- Content-blocklist watermark filtering and the single-letter-cell
  filter (both have real false-positive/false-negative modes the
  geometry-based approach avoids).
- Whole-page-raster-then-crop as the primary image-extraction path.

## Open question

Auto-detect-all-images-on-a-page (old app's `/scrape` behavior) is the
one old-app feature that's a genuine, no-tradeoff capability gap for a
document with many embedded figures. Not filing it as a TODO on my own
judgment -- flagging it here for you to decide whether it's worth the
added complexity given how this app is actually being used.
