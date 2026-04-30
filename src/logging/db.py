from pathlib import Path
import sqlite3


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "jobs.db"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL UNIQUE,
    timestamp_start TEXT NOT NULL,
    timestamp_end TEXT,
    duration_seconds REAL,
    source TEXT NOT NULL,
    use_case TEXT NOT NULL,
    request_data TEXT,
    ai_output TEXT,
    result_data TEXT,
    status TEXT NOT NULL,
    error_message TEXT,
    user_agent TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_timestamp ON jobs(timestamp_start DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_use_case ON jobs(use_case);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
"""


def get_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(
        DB_PATH,
        detect_types=sqlite3.PARSE_DECLTYPES,
        timeout=2.0,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL;")
    connection.executescript(SCHEMA_SQL)
    connection.commit()
    return connection
