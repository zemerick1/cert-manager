"""In-memory certificate request and renewal jobs.

POST /api/certs/request still runs Certbot in the request. A job returns
immediately and keeps the progress lines AcmeManager already produces.
The store lives in the API process. A restart drops the job record.
The certificate files and config.yaml are unaffected.
"""

import logging
import threading
import uuid

logger = logging.getLogger("cert_manager.jobs")

MAX_JOBS = 50
_ACTIVE = ("PENDING", "RUNNING")
_FINISHED = ("SUCCESS", "FAILED")


class JobInProgress(Exception):
    """A request or renewal for this pack is already queued."""


class CertJobStore:
    """Tracks certificate jobs for the life of the process."""

    def __init__(self) -> None:
        self._jobs: dict[str, dict] = {}
        self._order: list[str] = []
        self._lock = threading.Lock()

    def create(self, pack_name: str, kind: str) -> dict:
        """Records a job and returns a snapshot. Raises JobInProgress if one is active."""
        with self._lock:
            for job in self._jobs.values():
                if job["pack_name"] == pack_name and job["status"] in _ACTIVE:
                    raise JobInProgress(
                        f"A certificate job for '{pack_name}' is already {job['status'].lower()}."
                    )
            job_id = uuid.uuid4().hex
            job = {
                "job_id": job_id,
                "pack_name": pack_name,
                "kind": kind,
                "status": "PENDING",
                "progress": [],
                "success": None,
                "message": None,
            }
            self._jobs[job_id] = job
            self._order.append(job_id)
            self._trim()
            return _snapshot(job)

    def get(self, job_id: str) -> dict | None:
        """Returns a snapshot of one job, or None."""
        with self._lock:
            job = self._jobs.get(job_id)
            return _snapshot(job) if job else None

    def list_jobs(self) -> list[dict]:
        """Returns snapshots, newest first."""
        with self._lock:
            return [_snapshot(self._jobs[job_id]) for job_id in reversed(self._order)]

    def mark_running(self, job_id: str) -> None:
        """Moves a pending job to RUNNING."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job and job["status"] == "PENDING":
                job["status"] = "RUNNING"

    def append_progress(self, job_id: str, message: str) -> None:
        """Appends one progress line from Certbot or AcmeManager."""
        text = " ".join(str(message).split())
        if len(text) > 500:
            text = text[:500] + "..."
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or not text:
                return
            job["progress"].append(text)
            if len(job["progress"]) > 200:
                del job["progress"][:-200]

    def finish(self, job_id: str, success: bool, message: str) -> None:
        """Marks a job SUCCESS or FAILED."""
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job["status"] = "SUCCESS" if success else "FAILED"
            job["success"] = success
            job["message"] = message

    def _trim(self) -> None:
        """Drops the oldest finished jobs once the store exceeds MAX_JOBS."""
        finished = [job_id for job_id in self._order if self._jobs[job_id]["status"] in _FINISHED]
        while len(self._jobs) > MAX_JOBS and finished:
            oldest = finished.pop(0)
            self._order.remove(oldest)
            self._jobs.pop(oldest, None)


def run_request_job(store: CertJobStore, job_id: str, acme, fields: dict) -> None:
    """Runs AcmeManager.request_certificate and stores progress on the job."""
    store.mark_running(job_id)

    def progress(msg: str) -> None:
        store.append_progress(job_id, msg)

    try:
        result = acme.request_certificate(progress_callback=progress, **fields)
    except Exception as e:
        logger.exception(f"Certificate job {job_id} failed.")
        store.finish(job_id, False, str(e))
        return
    store.finish(job_id, bool(result.get("success")), result.get("message", ""))


def run_renew_job(store: CertJobStore, job_id: str, acme, pack_name: str) -> None:
    """Runs AcmeManager.renew_certificate and stores progress on the job."""
    store.mark_running(job_id)

    def progress(msg: str) -> None:
        store.append_progress(job_id, msg)

    try:
        result = acme.renew_certificate(pack_name, progress_callback=progress)
    except Exception as e:
        logger.exception(f"Renewal job {job_id} failed.")
        store.finish(job_id, False, str(e))
        return
    store.finish(job_id, bool(result.get("success")), result.get("message", ""))


def _snapshot(job: dict) -> dict:
    """Copies a job so later progress updates do not change an earlier response."""
    return {
        "job_id": job["job_id"],
        "pack_name": job["pack_name"],
        "kind": job["kind"],
        "status": job["status"],
        "progress": list(job["progress"]),
        "success": job["success"],
        "message": job["message"],
    }
