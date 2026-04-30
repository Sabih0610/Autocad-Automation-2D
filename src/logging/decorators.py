from __future__ import annotations

import sys
import threading
from functools import wraps

from src.logging.jobs import log_job_end, log_job_start


_state = threading.local()


def log_job(use_case_name: str):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if getattr(_state, "logging_active", False):
                return func(*args, **kwargs)

            _state.logging_active = True
            job_id = log_job_start(
                use_case=use_case_name,
                source="cli",
                request_data={"argv": sys.argv},
                user_agent="cli",
            )

            try:
                result = func(*args, **kwargs)
                log_job_end(
                    job_id,
                    status="ok",
                    result_data={"completed": True},
                )
                return result
            except SystemExit as exc:
                if exc.code in (None, 0):
                    log_job_end(
                        job_id,
                        status="ok",
                        result_data={"completed": True},
                    )
                else:
                    log_job_end(
                        job_id,
                        status="error",
                        error_message=str(exc),
                    )
                raise
            except Exception as exc:
                log_job_end(
                    job_id,
                    status="error",
                    error_message=str(exc),
                )
                raise
            finally:
                _state.logging_active = False

        return wrapper

    return decorator
