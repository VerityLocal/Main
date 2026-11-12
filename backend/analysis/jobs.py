"""Single worker, bounded upload/queue/results, private temporary files, expiring results."""

from collections import deque
from copy import deepcopy
from dataclasses import dataclass, field
import logging
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Condition, Thread
import time
from uuid import uuid4

from backend.analysis.types import AnalysisError
from backend.config import Settings


logger = logging.getLogger(__name__)
STAGES = {"receiving":(0,.04),"validating":(.04,.08),"extracting":(.08,.35),"ocr":(.35,.5),
          "segmenting":(.5,.6),"scoring_text":(.6,.8),"scoring_code":(.8,.96),"aggregating":(.96,.99)}


@dataclass
class Job:
    id: str
    threshold: float
    directory: TemporaryDirectory
    file_format: str = "pdf"
    status: str = "receiving"
    stage: str = "receiving"
    progress: float = 0.0
    current: int = 0
    total: int = 1
    result: dict | None = None
    error: dict | None = None
    finished: float | None = None
    history: list[str] = field(default_factory=lambda:["receiving"])

    @property
    def path(self):
        extension = {'pdf':'pdf','python':'py','javascript':'js','text':'txt'}[self.file_format]
        return Path(self.directory.name)/('input.'+extension)


class JobManager:
    def __init__(self, settings: Settings, pipeline):
        self.settings, self.pipeline = settings, pipeline
        self._condition = Condition()
        self._jobs, self._queue = {}, deque()
        self._stopping = False
        self._thread = None

    @property
    def accepting(self):
        return self._thread is not None and self._thread.is_alive() and not self._stopping

    def _cleanup(self, job):
        try:
            job.directory.cleanup()
        except OSError:
            logger.exception("Private PDF job cleanup failed; manual cleanup may be required")
            return False
        return True

    def start(self):
        self.settings.temp_dir.mkdir(mode=0o700,parents=True,exist_ok=True)
        self._thread = Thread(target=self._worker,name="pdf-analysis-worker",daemon=True)
        self._thread.start()

    def _prune(self):
        now = time.monotonic()
        for job_id,job in list(self._jobs.items()):
            if job.finished is not None and now-job.finished >= self.settings.result_ttl_seconds:
                del self._jobs[job_id]

    def reserve(self, threshold, file_format="pdf"):
        with self._condition:
            self._prune()
            if not self.accepting:
                raise AnalysisError("backend_stopping","Backend is not accepting analyses.")
            active = sum(job.finished is None for job in self._jobs.values())
            if active >= self.settings.max_active_jobs:
                raise AnalysisError("queue_full","Analysis queue is full; retry later.")
            if len(self._jobs) >= self.settings.max_retained_jobs:
                finished = [job for job in self._jobs.values() if job.finished is not None]
                if finished:
                    del self._jobs[min(finished,key=lambda job:job.finished).id]
            job = Job(uuid4().hex,threshold,TemporaryDirectory(prefix="job-",dir=self.settings.temp_dir),file_format)
            self._jobs[job.id] = job
            return job

    def abandon(self, job_id):
        with self._condition:
            job = self._jobs.pop(job_id,None)
            if job:
                self._cleanup(job)

    def enqueue(self, job_id):
        with self._condition:
            if self._stopping:
                raise AnalysisError("backend_stopping","Backend is shutting down.")
            job = self._jobs[job_id]
            job.status,job.stage = "queued","queued"
            job.history.append("queued")
            self._queue.append(job_id)
            self._condition.notify_all()

    def snapshot(self, job_id):
        with self._condition:
            self._prune()
            job = self._jobs.get(job_id)
            if job is None:
                return None
            return deepcopy({"job_id":job.id,"status":job.status,"stage":job.stage,"progress":job.progress,
                             "current":job.current,"total":job.total,"stages_seen":job.history,
                             "result":job.result,"error":job.error,
                             "expires_in_seconds":max(0,self.settings.result_ttl_seconds-(time.monotonic()-job.finished))
                             if job.finished is not None else None})

    def update(self, job, stage, current=0, total=1):
        with self._condition:
            low,high = STAGES.get(stage,(job.progress,job.progress))
            job.progress = max(job.progress,low+(high-low)*min(1,max(0,current/max(1,total))))
            job.stage,job.current,job.total = stage,current,total
            if job.history[-1] != stage:
                job.history.append(stage)

    def _worker(self):
        while True:
            with self._condition:
                self._prune()
                while not self._queue and not self._stopping:
                    self._condition.wait(timeout=min(30,self.settings.result_ttl_seconds))
                    self._prune()
                if self._stopping:
                    return
                job = self._jobs[self._queue.popleft()]
                job.status = "running"
            try:
                result = self.pipeline.run(job.path,job.threshold,
                                           lambda *args:self.update(job,*args),lambda:self._stopping)
                if not isinstance(result,dict):
                    raise RuntimeError("Pipeline did not return an analysis result")
            except AnalysisError as exc:
                error = {"code":exc.code,"message":str(exc)}
                result = None
            except Exception:
                logger.exception("PDF analysis job failed")
                error = {"code":"analysis_failed","message":"Analysis failed; no result was published. Check backend logs."}
                result = None
            finally:
                if not self._cleanup(job):
                    result = None
                    error = {"code":"cleanup_failed","message":"Private temporary-file cleanup failed. Check backend logs before continuing."}
            with self._condition:
                job.result = result
                job.error = error if result is None else None
                job.status = "failed" if result is None else "completed"
                job.stage = job.status
                if result is not None:
                    job.progress = 1.0
                job.history.append(job.status)
                job.finished = time.monotonic()
                self._condition.notify_all()

    def close(self):
        with self._condition:
            self._stopping = True
            self._condition.notify_all()
        if self._thread is not None:
            self._thread.join()
        with self._condition:
            for job in self._jobs.values():
                self._cleanup(job)
            self._jobs.clear()
            self._queue.clear()
