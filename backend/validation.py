"""Request validation and limits for the diagnose endpoint."""
from __future__ import annotations

from typing import Any


MAX_LOG_LENGTH = 12_000
MAX_WORKFLOW_LENGTH = 8_000
MAX_QUESTION_LENGTH = 500


class RequestValidationError(ValueError):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def validate_request(payload: Any) -> dict[str, str]:
    if not isinstance(payload, dict):
        raise RequestValidationError("Request body must be a JSON object.")

    log = payload.get("log")
    if not isinstance(log, str) or not log.strip():
        raise RequestValidationError("The log field is required and cannot be empty.")
    if len(log) > MAX_LOG_LENGTH:
        raise RequestValidationError(
            f"The log is too large. Keep it under {MAX_LOG_LENGTH:,} characters.", 413
        )

    workflow = payload.get("workflow", "")
    if workflow is None:
        workflow = ""
    if not isinstance(workflow, str):
        raise RequestValidationError("The workflow field must be text.")
    if len(workflow) > MAX_WORKFLOW_LENGTH:
        raise RequestValidationError(
            f"The workflow is too large. Keep it under {MAX_WORKFLOW_LENGTH:,} characters.", 413
        )

    question = payload.get("question", "")
    if question is None:
        question = ""
    if not isinstance(question, str):
        raise RequestValidationError("The question field must be text.")
    if len(question) > MAX_QUESTION_LENGTH:
        raise RequestValidationError(
            f"The question is too large. Keep it under {MAX_QUESTION_LENGTH:,} characters.", 413
        )

    return {"log": log, "workflow": workflow, "question": question}
