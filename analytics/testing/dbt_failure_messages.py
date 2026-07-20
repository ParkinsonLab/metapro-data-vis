"""Format dbt failures for run_context.last_error and SSE error events."""
from __future__ import annotations

# dbt singular/data tests fail when SQL returns rows; message is always row-count based.
_GENERIC_ROW_COUNT_MARKERS = ("configured to fail if",)


def _normalize_dbt_error_message(msg: str) -> str:
    stripped = msg.strip()
    for prefix in ("Invalid Input Error: ", "Binder Error: ", "Catalog Error: "):
        if prefix in stripped:
            return stripped.split(prefix, 1)[-1].strip()
    lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    return lines[-1] if lines else stripped


def _is_generic_row_count_failure(message: str) -> bool:
    return any(marker in message for marker in _GENERIC_ROW_COUNT_MARKERS)


def _test_name(*, unique_id: str, node_name: str | None) -> str:
    if node_name:
        return node_name
    if unique_id.startswith("test."):
        return unique_id.rsplit(".", 1)[-1]
    return ""


def format_dbt_failure_message(
    *,
    unique_id: str = "",
    node_name: str | None = None,
    message: str = "",
) -> str:
    message = _normalize_dbt_error_message(message)
    test_name = _test_name(unique_id=unique_id, node_name=node_name)
    if test_name and _is_generic_row_count_failure(message):
        return f"Assertion failed: {test_name}"
    if unique_id.startswith("test.") and message and test_name not in message:
        return f"{test_name}: {message}"
    return message or test_name or unique_id


def format_dbt_run_result(result: dict) -> str:
    node_info = result.get("node_info") or {}
    return format_dbt_failure_message(
        unique_id=result.get("unique_id") or "",
        node_name=node_info.get("node_name"),
        message=result.get("message") or "",
    )
