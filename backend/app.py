"""AWS Lambda HTTP API entry point for ActionFix."""
from __future__ import annotations

import base64
import json
import logging
import os
import time
from typing import Any

from agent import diagnose
from tools import redact_secrets
from validation import RequestValidationError, validate_request


LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)

_RATE_WINDOW_SECONDS = 60
_RATE_LIMIT = max(1, int(os.getenv("RATE_LIMIT_PER_MINUTE", "20")))
_RATE_STATE: dict[str, list[float]] = {}


def _cors_headers(request_headers: dict[str, Any] | None = None) -> dict[str, str]:
    configured = os.getenv("ALLOWED_ORIGIN", "*")
    origin = (request_headers or {}).get("origin") or (request_headers or {}).get("Origin")
    allow_origin = origin if configured == "*" and origin else configured
    if configured != "*" and origin != configured:
        allow_origin = configured
    return {
        "content-type": "application/json; charset=utf-8",
        "access-control-allow-origin": allow_origin,
        "access-control-allow-headers": "content-type",
        "access-control-allow-methods": "POST, OPTIONS",
        "cache-control": "no-store",
    }


def _response(status_code: int, payload: dict[str, Any], request_headers: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": _cors_headers(request_headers),
        "isBase64Encoded": False,
        "body": json.dumps(payload, ensure_ascii=False),
    }


def _event_headers(event: dict[str, Any]) -> dict[str, Any]:
    headers = event.get("headers")
    return headers if isinstance(headers, dict) else {}


def _method_and_path(event: dict[str, Any]) -> tuple[str, str]:
    context = event.get("requestContext") or {}
    http = context.get("http") if isinstance(context, dict) else {}
    if isinstance(http, dict):
        method = str(http.get("method") or "").upper()
        path = str(http.get("path") or event.get("rawPath") or "")
    else:
        method = str(event.get("httpMethod") or "").upper()
        path = str(event.get("path") or event.get("rawPath") or "")
    return method, path


def _source_key(event: dict[str, Any]) -> str:
    context = event.get("requestContext") or {}
    http = context.get("http") if isinstance(context, dict) else {}
    if isinstance(http, dict) and http.get("sourceIp"):
        return str(http["sourceIp"])
    return "unknown-source"


def _allow_request(source: str, now: float | None = None) -> bool:
    current = now if now is not None else time.monotonic()
    recent = [timestamp for timestamp in _RATE_STATE.get(source, []) if current - timestamp < _RATE_WINDOW_SECONDS]
    if len(recent) >= _RATE_LIMIT:
        _RATE_STATE[source] = recent
        return False
    recent.append(current)
    _RATE_STATE[source] = recent
    if len(_RATE_STATE) > 4096:
        oldest_key = min(_RATE_STATE, key=lambda key: _RATE_STATE[key][-1] if _RATE_STATE[key] else 0)
        _RATE_STATE.pop(oldest_key, None)
    return True


def _decode_body(event: dict[str, Any]) -> str:
    body = event.get("body", "")
    if body is None:
        return ""
    if not isinstance(body, str):
        raise RequestValidationError("Request body must be JSON text.")
    if event.get("isBase64Encoded"):
        try:
            return base64.b64decode(body).decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise RequestValidationError("Request body is not valid UTF-8 JSON.") from exc
    return body


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    del context
    headers = _event_headers(event)
    method, path = _method_and_path(event)

    if method == "OPTIONS":
        return _response(204, {}, headers)
    if method != "POST" or not path.rstrip("/").endswith("/diagnose"):
        return _response(404, {"error": "Use POST /diagnose."}, headers)
    if not _allow_request(_source_key(event)):
        return _response(429, {"error": "Too many requests. Please wait a minute and try again."}, headers)

    content_type = str(headers.get("content-type") or headers.get("Content-Type") or "").lower()
    if content_type and not content_type.startswith("application/json"):
        return _response(415, {"error": "Content-Type must be application/json."}, headers)

    try:
        body_text = _decode_body(event)
        if len(body_text) > 24_000:
            return _response(413, {"error": "Request body is too large."}, headers)
        payload = json.loads(body_text)
        request = validate_request(payload)
        result = diagnose(
            redact_secrets(request["log"]),
            redact_secrets(request["workflow"]),
            redact_secrets(request["question"]),
        )
        LOGGER.info(
            "diagnosis_complete category=%s status=%s model_status=%s",
            result.get("category"),
            result.get("status"),
            result.get("model_status"),
        )
        return _response(200, result, headers)
    except RequestValidationError as exc:
        return _response(exc.status_code, {"error": exc.message}, headers)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _response(400, {"error": "Request body must contain valid JSON."}, headers)
    except Exception:
        LOGGER.exception("diagnosis_request_failed")
        return _response(500, {"error": "ActionFix could not process that request safely."}, headers)
