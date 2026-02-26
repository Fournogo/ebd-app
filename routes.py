# routes.py
import io
from flask import Blueprint, request, jsonify, send_file
from redis import Redis
from rq import Queue
from rq.job import Job
import os

from tasks import generate_report_task

report_bp = Blueprint("report", __name__)
redis_conn = Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379"))
q = Queue("ebd_reports", connection=redis_conn)  # single serial queue

MAX_JOB_TIMEOUT = 120  # seconds — tune to your longest expected report

def _error(message, status=400):
    return jsonify({"error": message}), status


@report_bp.route("/generate-report", methods=["POST"])
def generate_report():
    """Enqueue a report job, return a job ID immediately."""
    body = request.get_json(silent=True) or {}

    if "rainfall_data" not in body and not ("lat" in body and "lon" in body):
        return _error("Provide either 'rainfall_data' or 'lat'/'lon'.")

    job = q.enqueue(
        generate_report_task,
        body,
        job_timeout=MAX_JOB_TIMEOUT,
        result_ttl=300,   # keep result in Redis for 5 min after completion
    )
    return jsonify({"job_id": job.id, "status": "queued"}), 202


@report_bp.route("/report-status/<job_id>", methods=["GET"])
def report_status(job_id):
    """Poll this endpoint until status is 'finished' or 'failed'."""
    try:
        job = Job.fetch(job_id, connection=redis_conn)
    except Exception:
        return _error("Job not found.", 404)

    status = job.get_status()

    if status == "finished":
        zip_bytes, warnings = job.result
        response = send_file(
            io.BytesIO(zip_bytes),
            mimetype="application/zip",
            as_attachment=True,
            download_name="EBD_Analysis_Results.zip",
        )
        if warnings:
            response.headers["X-Analysis-Warnings"] = "; ".join(warnings)
        return response

    if status == "failed":
        return _error(f"Job failed: {job.exc_info}", 500)

    # queued / started / deferred
    return jsonify({"job_id": job_id, "status": str(status)}), 202