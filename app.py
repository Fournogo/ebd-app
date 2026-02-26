"""
app.py
------
Flask application entry point.

Static files (React build output) are served from the `static/` directory.
Requests to any non-API path fall through to `static/index.html` so that
React Router can handle client-side navigation.

Project layout expected:
    app.py
    routes.py
    idf_analysis.py
    rainfall_data.py
    idf_report_template.ipynb
    idf_report.css
    static/
        index.html          ← React build output (npm run build)
        assets/
            ...

Usage:
    python app.py               # development server on http://localhost:5000
    flask run --debug           # same, with auto-reload
"""

import os
from flask import Flask, send_from_directory
from routes import report_bp

# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

app = Flask(__name__, static_folder="static", static_url_path="")

# Register the /generate-report blueprint
app.register_blueprint(report_bp)


# ---------------------------------------------------------------------------
# Static / SPA catch-all
# ---------------------------------------------------------------------------

@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_spa(path: str):
    """Serve static assets, falling back to index.html for unknown paths.

    This lets React Router handle all client-side routes without Flask
    returning 404s for deep links like /results or /about.
    """
    # If a real file exists in the static folder, serve it directly
    # (JS bundles, CSS, images, favicons, etc.)
    static_file = os.path.join(app.static_folder, path)
    if path and os.path.isfile(static_file):
        return send_from_directory(app.static_folder, path)

    # Otherwise fall through to the React entry point
    return send_from_directory(app.static_folder, "index.html")


# ---------------------------------------------------------------------------
# Dev entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5001)
