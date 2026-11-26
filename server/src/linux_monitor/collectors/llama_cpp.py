"""llama.cpp monitoring collector."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

from ..config import Settings
from ..schemas import LlamaCppInfo, LlamaCppModel, LlamaCppSlot

_TOTAL_BUDGET_SECONDS = 2.5
_PER_REQUEST_CAP_SECONDS = 1.0
_READ_LIMIT_BYTES = 1 * 1024 * 1024

_SUPPORTED_MODEL_STATUSES = {
    "loaded",
    "unloaded",
    "loading",
    "sleeping",
    "downloading",
    "incomplete",
    "downloaded",
    "stopping",
}


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        return None


_OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({}),
    _NoRedirectHandler,
)


def _positive_int(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value > 0:
        return value
    return None


def _nonnegative_int(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value >= 0:
        return value
    return None


def _remaining(deadline: float) -> float:
    return deadline - time.monotonic()


def _read_limited(response: Any, deadline: float) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while total <= _READ_LIMIT_BYTES:
        remaining = _remaining(deadline)
        if remaining <= 0:
            raise TimeoutError("budget exhausted")
        to_read = _READ_LIMIT_BYTES + 1 - total
        if to_read <= 0:
            break
        chunk = response.read1(to_read)
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > _READ_LIMIT_BYTES:
            raise ValueError("response too large")
    return b"".join(chunks)


def _parse_json(raw: bytes) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def _get_json(
    url: str, headers: Optional[dict[str, str]], deadline: float
) -> tuple[int, Any]:
    remaining = _remaining(deadline)
    if remaining <= 0:
        raise TimeoutError("budget exhausted")
    timeout = min(_PER_REQUEST_CAP_SECONDS, remaining)
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    try:
        with _OPENER.open(req, timeout=timeout) as response:
            status = response.getcode()
            raw = _read_limited(response, deadline)
            return status, _parse_json(raw)
    except urllib.error.HTTPError as exc:
        status = exc.code
        with exc:
            if status != 503:
                return status, None
            raw = _read_limited(exc, deadline)
            return status, _parse_json(raw)


def _collect_slots(
    url: str, headers: Optional[dict[str, str]], deadline: float
) -> Optional[list[LlamaCppSlot]]:
    try:
        status, body = _get_json(url, headers, deadline)
    except Exception:
        return None
    if status != 200 or not isinstance(body, list):
        return None
    if not body:
        return []
    parsed: list[LlamaCppSlot] = []
    for raw in body:
        if not isinstance(raw, dict):
            continue
        slot_id = _nonnegative_int(raw.get("id"))
        slot_n_ctx = _positive_int(raw.get("n_ctx"))
        if slot_id is None or slot_n_ctx is None:
            continue
        used = _nonnegative_int(raw.get("n_prompt_tokens"))
        if used is None:
            used = _nonnegative_int(raw.get("n_past"))
        if used is None:
            remaining = None
        else:
            remaining = max(0, slot_n_ctx - used)
        is_processing = raw.get("is_processing")
        if not isinstance(is_processing, bool):
            is_processing = None
        parsed.append(
            LlamaCppSlot(
                id=slot_id,
                context_tokens=slot_n_ctx,
                used_tokens=used,
                remaining_tokens=remaining,
                is_processing=is_processing,
            )
        )
    if not parsed:
        return None
    return parsed


def collect_llama_cpp(settings: Settings, include_llama_context: bool = False) -> LlamaCppInfo:
    deadline = time.monotonic() + _TOTAL_BUDGET_SECONDS
    base = settings.llama_cpp_url.rstrip("/")
    api_key = settings.llama_cpp_api_key.get_secret_value() if settings.llama_cpp_api_key else None

    # Health (no auth).
    health_url = base + "/health"
    try:
        status_code, body = _get_json(health_url, None, deadline)
    except Exception:
        return LlamaCppInfo(status="unavailable", error="unreachable")
    if status_code == 503:
        if isinstance(body, dict):
            if body.get("status") == "loading model":
                return LlamaCppInfo(status="loading", error=None)
            err = body.get("error")
            if isinstance(err, dict) and err.get("message") == "Loading model":
                return LlamaCppInfo(status="loading", error=None)
        return LlamaCppInfo(status="unavailable", error="invalid health response")
    if status_code != 200 or not isinstance(body, dict) or body.get("status") != "ok":
        return LlamaCppInfo(status="unavailable", error="invalid health response")

    # Catalog.
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    models_url = base + "/models"
    try:
        status_code, body = _get_json(models_url, headers, deadline)
    except Exception:
        return LlamaCppInfo(status="running", error="catalog request failed", models=[])

    if status_code in (404, 405):
        # Fallback to OpenAI-compatible path.
        try:
            status_code, body = _get_json(base + "/v1/models", headers, deadline)
        except Exception:
            return LlamaCppInfo(status="running", error="catalog request failed", models=[])

    if status_code in (401, 403):
        return LlamaCppInfo(status="running", error="catalog authentication failed", models=[])
    if status_code != 200 or not isinstance(body, dict) or not isinstance(body.get("data"), list):
        return LlamaCppInfo(status="running", error="invalid catalog response", models=[])

    items = body["data"]
    parsed_models: list[LlamaCppModel] = []

    for item in items:
        if not isinstance(item, dict):
            continue
        model_id = item.get("id")
        if not isinstance(model_id, str) or not model_id:
            continue

        has_status_field = "status" in item
        raw_status = item.get("status") if has_status_field else None

        if not has_status_field:
            model_status = "loaded"
        else:
            if isinstance(raw_status, dict):
                status_value = raw_status.get("value")
            elif isinstance(raw_status, str):
                status_value = raw_status
            else:
                status_value = None

            if isinstance(status_value, str) and status_value in _SUPPORTED_MODEL_STATUSES:
                model_status = status_value
            else:
                model_status = "unknown"

        # Training context.
        training_context: Optional[int] = None
        top_context = _positive_int(item.get("context_length"))
        if top_context is not None:
            training_context = top_context
        meta = item.get("meta")
        meta_n_ctx_train = None
        meta_n_ctx = None
        if isinstance(meta, dict):
            meta_n_ctx_train = _positive_int(meta.get("n_ctx_train"))
            meta_n_ctx = _positive_int(meta.get("n_ctx"))
        if training_context is None and meta_n_ctx_train is not None:
            training_context = meta_n_ctx_train

        # Runtime context fallback only for loaded models.
        runtime_context: Optional[int] = meta_n_ctx if model_status == "loaded" else None

        total_slots: Optional[int] = None

        if has_status_field:
            query_suffix = "?" + urllib.parse.urlencode({"model": model_id, "autoload": "false"})
        else:
            query_suffix = ""

        slots_list: Optional[list[LlamaCppSlot]] = None

        if model_status == "loaded":
            props_url = base + "/props" + query_suffix
            try:
                props_status, props_body = _get_json(props_url, headers, deadline)
            except Exception:
                props_status, props_body = 0, None

            if props_status == 200 and isinstance(props_body, dict):
                if props_body.get("is_sleeping") is True:
                    model_status = "sleeping"

                gen = props_body.get("default_generation_settings")
                if isinstance(gen, dict):
                    n_ctx = _positive_int(gen.get("n_ctx"))
                    if n_ctx is not None:
                        runtime_context = n_ctx
                slots = _positive_int(props_body.get("total_slots"))
                if slots is not None:
                    total_slots = slots

                if include_llama_context and model_status == "loaded":
                    slots_list = _collect_slots(base + "/slots" + query_suffix, headers, deadline)

        model = LlamaCppModel(
            id=model_id,
            status=model_status,
            context_tokens=runtime_context,
            training_context_tokens=training_context,
            total_slots=total_slots,
            slots=slots_list,
        )
        parsed_models.append(model)

    return LlamaCppInfo(status="running", error=None, models=parsed_models)
