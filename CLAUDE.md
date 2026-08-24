# PDF-XML

## Code style

Python: terse comments, `###`-style section headers (see `app/blueprints/*.py`,
`app/docbook.py`). No multi-line prose explaining rationale, no editorializing.

CSS and JS do NOT support `###` -- it is not a comment in either language.
Use `/* ... */` in `.css` files (and `<style>` blocks) and `//` in `.js` files
(and `<script>` blocks). This isn't a style preference: a `###` line in CSS
gets parsed as part of an invalid selector, silently swallowing the *next*
rule along with it -- no error, no warning, the rule just never applies. This
already happened once (static/style.css) and cost a long debugging session
to track down, since the file's text looked correct the whole time.
