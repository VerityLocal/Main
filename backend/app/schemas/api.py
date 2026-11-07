"""Typed foundation responses."""

from typing import Literal

from backend.app.core.resource_manager import HardwareSnapshot
from backend.app.schemas.document import Contract


class HealthResponse(Contract):
    status: Literal["ok"] = "ok"
    api_version: Literal["v1"] = "v1"
    platform_version: Literal["0.1.0"] = "0.1.0"
    implementation: Literal["local_analysis_platform"] = "local_analysis_platform"
    hardware: HardwareSnapshot
    components: dict[str, str]
    gpu_allocated_ceiling_bytes: int


class RegistrationResponse(Contract):
    document_id: str
    revision: int
    offset_unit: Literal["utf16_code_unit"] = "utf16_code_unit"
    registered: Literal[True] = True
    changed: bool


class ErrorDetail(Contract):
    code: str
    message: str


class ErrorResponse(Contract):
    error: ErrorDetail
    request_id: str
