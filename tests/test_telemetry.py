from __future__ import annotations

import logging

from app.telemetry import _HealthLogFilter


def _access_record(path: str) -> logging.LogRecord:
    """A record shaped exactly like uvicorn.access builds them.

    uvicorn logs '%s - "%s %s HTTP/%s" %d' with
    args = (client_addr, method, full_path, http_version, status_code),
    which is why the filter reads args[2].
    """
    return logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1:54321", "GET", path, "1.1", 200),
        exc_info=None,
    )


def test_health_probe_access_log_is_dropped() -> None:
    assert _HealthLogFilter().filter(_access_record("/health")) is False


def test_health_probe_with_query_string_is_dropped() -> None:
    assert _HealthLogFilter().filter(_access_record("/health?verbose=1")) is False


def test_ordinary_request_access_log_is_kept() -> None:
    log_filter = _HealthLogFilter()
    assert log_filter.filter(_access_record("/api/chat")) is True
    # Only the path prefix matches, so a nested route keeps its logs.
    assert log_filter.filter(_access_record("/api/health")) is True


def test_non_access_records_pass_through() -> None:
    """The filter sits on the root OTLP handler, so it sees every log record.

    Anything that isn't a uvicorn access record must survive untouched, whatever
    shape its args are.
    """
    log_filter = _HealthLogFilter()

    plain = logging.LogRecord("app", logging.INFO, "", 0, "hello", None, None)
    assert log_filter.filter(plain) is True

    short_args = logging.LogRecord("app", logging.INFO, "", 0, "%s %s", ("a", "b"), None)
    assert log_filter.filter(short_args) is True

    non_str_path = _access_record("/health")
    non_str_path.args = ("127.0.0.1:1", "GET", 42, "1.1", 200)
    assert log_filter.filter(non_str_path) is True

    mapping_args = logging.LogRecord("app", logging.INFO, "", 0, "%(a)s", None, None)
    mapping_args.args = {"a": 1}
    assert log_filter.filter(mapping_args) is True
