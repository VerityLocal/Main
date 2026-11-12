"""One startup attempt per detector; failures stay explicit and independent."""

from collections.abc import Callable
from copy import deepcopy
import logging
from threading import Lock

from backend.config import DISCLAIMER, Settings
from backend.detectors.artifacts import MODEL_INFO, ModelLoadError
from backend.detectors.inference import LoadedDetector
from backend.detectors.loaders import load_detector


logger = logging.getLogger(__name__)


class ModelRuntime:
    def __init__(self, settings: Settings, loader: Callable = load_detector) -> None:
        self.settings = settings
        self._loader = loader
        self._initialization_lock = Lock()
        self._state_lock = Lock()
        self._started = False
        self._detectors: dict[str, LoadedDetector] = {}
        self._states = {kind: {"status": "not_started", "error": None} for kind in MODEL_INFO}

    def initialize(self) -> None:
        with self._initialization_lock:
            if self._started:
                return
            self._started = True
            for kind in MODEL_INFO:
                with self._state_lock:
                    self._states[kind] = {"status": "loading", "error": None}
                try:
                    detector = self._loader(kind, self.settings)
                    if detector is None:
                        raise ModelLoadError("load_failed", "Loader returned no model.")
                except Exception as exc:
                    if isinstance(exc, ModelLoadError):
                        code, message = exc.code, str(exc)
                    elif isinstance(exc, ImportError):
                        code, message = "dependency_missing", "A required model dependency is unavailable."
                    else:
                        code, message = "load_failed", "Model initialization failed; check backend logs."
                    logger.exception("%s detector unavailable (%s)", kind, code)
                    with self._state_lock:
                        self._states[kind] = {"status": "unavailable", "error": {"code": code, "message": message}}
                else:
                    with self._state_lock:
                        self._detectors[kind] = detector
                        self._states[kind] = {"status": "ready", "error": None}
                    logger.info("%s detector ready on %s", kind, self.settings.device)

    def get_detector(self, kind: str) -> LoadedDetector:
        with self._state_lock:
            if kind not in self._detectors:
                raise RuntimeError(f"{kind} detector is unavailable; no score can be produced")
            return self._detectors[kind]

    def health(self) -> dict:
        with self._state_lock:
            states = deepcopy(self._states)
        ready_count = sum(state["status"] == "ready" for state in states.values())
        statuses = {state["status"] for state in states.values()}
        if ready_count == len(states):
            status = "ready"
        elif statuses & {"loading", "not_started"}:
            status = "starting"
        elif statuses == {"stopped"}:
            status = "stopped"
        elif ready_count:
            status = "degraded"
        else:
            status = "unavailable"
        return {
            "status": status,
            "ready": status == "ready",
            "phase": "backend_foundation",
            "analysis_available": False,
            "device": self.settings.device,
            "max_tokens": self.settings.max_tokens,
            "batch_size": self.settings.batch_size,
            "threshold": self.settings.threshold,
            "models": {
                kind: {**deepcopy(MODEL_INFO[kind]), **state,
                       "integrity_verified": state["status"] == "ready"}
                for kind, state in states.items()
            },
            "disclaimer": DISCLAIMER,
        }

    def close(self) -> None:
        with self._initialization_lock, self._state_lock:
            self._detectors.clear()
            self._states = {kind: {"status": "stopped", "error": None} for kind in MODEL_INFO}
