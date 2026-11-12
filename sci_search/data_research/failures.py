"""Separate expected source failures from internal processing diagnostics."""

import csv
import http.client
import traceback
import zipfile
from xml.etree.ElementTree import ParseError

EXPECTED_SOURCE_ERRORS = (
    OSError,
    ValueError,
    csv.Error,
    http.client.HTTPException,
    zipfile.BadZipFile,
    ParseError,
    StopIteration,
)


def record_failure(record, error, *, stage):
    """Preserve recoverability without attributing a programming bug to a dataset.

    Cancellation and budget exhaustion are BaseExceptions, not accepted here.
    Callers still decide their state transition; this helper only records failure.
    """
    if not isinstance(error, Exception):
        raise error
    internal = not isinstance(error, EXPECTED_SOURCE_ERRORS)
    record.update(
        failure_stage=stage,
        failure_category="internal_error" if internal else "source_error",
        error_class=type(error).__name__,
        reason="Processing failed; retained source material can be inspected and retried."
        if internal
        else str(error)[:1000],
    )
    if internal:
        record.pop("availability", None)
        record["diagnostic"] = {
            "exception_class": type(error).__name__,
            "traceback": "".join(traceback.format_exception(error))[-12000:],
        }
    else:
        record.pop("diagnostic", None)
    return internal
