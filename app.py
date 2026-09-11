"""
Interfaccia web locale per il fixer di Google Takeout Photos.

Avvio:
    python app.py

Poi apri http://127.0.0.1:5050 nel browser.
"""

import sys
import uuid
from pathlib import Path

from flask import Flask, jsonify, render_template, request

from core import Job, check_exiftool


def _template_folder():
    """Quando l'app è congelata con py2app, i template finiscono in
    Contents/Resources/templates invece che accanto a questo file."""
    if getattr(sys, "frozen", False):
        return str(Path(sys.executable).resolve().parent.parent / "Resources" / "templates")
    return str(Path(__file__).resolve().parent / "templates")


app = Flask(__name__, template_folder=_template_folder())

JOBS = {}


@app.route("/")
def index():
    return render_template("index.html", exiftool_ok=check_exiftool())


@app.route("/api/exiftool-status")
def exiftool_status():
    return jsonify({"installed": check_exiftool()})


@app.route("/api/start", methods=["POST"])
def start_job():
    if not check_exiftool():
        return jsonify({"error": "exiftool non è installato o non è nel PATH."}), 400

    data = request.get_json(force=True)
    input_dir = (data.get("input_dir") or "").strip()
    output_dir = (data.get("output_dir") or "").strip()
    dry_run = bool(data.get("dry_run"))
    try:
        jobs_count = int(data.get("jobs") or 4)
    except (TypeError, ValueError):
        jobs_count = 4

    if not input_dir or not output_dir:
        return jsonify({"error": "Specifica sia la cartella di input che quella di output."}), 400

    job = Job(input_dir, output_dir, dry_run=dry_run, jobs=jobs_count)
    job_id = str(uuid.uuid4())
    JOBS[job_id] = job
    job.start()

    return jsonify({"job_id": job_id})


@app.route("/api/status/<job_id>")
def job_status(job_id):
    job = JOBS.get(job_id)
    if job is None:
        return jsonify({"error": "Job non trovato."}), 404
    return jsonify(job.to_dict())


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5050, debug=False)
