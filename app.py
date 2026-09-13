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

API_ERRORS = {
    "it": {
        "no_exiftool": "exiftool non è installato o non è nel PATH.",
        "missing_dirs": "Specifica sia la cartella di input che quella di output.",
        "job_not_found": "Job non trovato.",
    },
    "en": {
        "no_exiftool": "exiftool is not installed or not in PATH.",
        "missing_dirs": "Please specify both the input and output folders.",
        "job_not_found": "Job not found.",
    },
}


def _lang(data=None):
    lang = (data or {}).get("lang") if data else request.args.get("lang")
    return lang if lang in API_ERRORS else "it"


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/exiftool-status")
def exiftool_status():
    return jsonify({"installed": check_exiftool()})


@app.route("/api/start", methods=["POST"])
def start_job():
    data = request.get_json(force=True)
    lang = _lang(data)
    errors = API_ERRORS[lang]

    if not check_exiftool():
        return jsonify({"error": errors["no_exiftool"]}), 400

    input_dir = (data.get("input_dir") or "").strip()
    output_dir = (data.get("output_dir") or "").strip()
    dry_run = bool(data.get("dry_run"))
    fallback_tz = (data.get("fallback_tz") or "UTC").strip() or "UTC"
    try:
        jobs_count = int(data.get("jobs") or 4)
    except (TypeError, ValueError):
        jobs_count = 4

    if not input_dir or not output_dir:
        return jsonify({"error": errors["missing_dirs"]}), 400

    job = Job(input_dir, output_dir, dry_run=dry_run, jobs=jobs_count, lang=lang, fallback_tz=fallback_tz)
    job_id = str(uuid.uuid4())
    JOBS[job_id] = job
    job.start()

    return jsonify({"job_id": job_id})


@app.route("/api/status/<job_id>")
def job_status(job_id):
    job = JOBS.get(job_id)
    if job is None:
        return jsonify({"error": API_ERRORS[_lang()]["job_not_found"]}), 404
    return jsonify(job.to_dict())


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5050, debug=False)
