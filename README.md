ABOUT

PDF-XML Tools assists in extracting unstructured PDF content for reuse in an XML-based CMS. It is a Python app written to assist in the process by using pymupdf to convert PDF elements into correctly structured pseudo-DocBook 5 XML as used by the Paligo content authoring system. 

INSTALLATION

1. Clone the git repository to a local directory.
2. Run schema_install.py to create the database.
3. Run create_user.py --admin to create an administrator account.

USING PDF-XML Tools

You can run the app using python3 run.py for testing. For longer term use, run with gunicorn or WSGI.

The interface consists of a series of cards that provide access to documentation and functions. In the default install, the Process card contains instructions on using the tool. These are editable by users with admin accounts. The next five cards (Paragraph, Ordered list, Unordered list, Table, and Extract image) are the tools for extracting contents from PDFs. The Crop card leads to a simple tool for cropping images. The Style guide card points to a user-provided Style guide document (static/style_guide.df) to instruct users on managing content. The Troubleshooting card provides a space for administrators to store troubleshooting information for users.
