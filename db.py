"""
PostgreSQL database layer.

Schema is created on first run.  All public functions acquire a connection
from the thread-safe pool, execute the query and return plain Python dicts
(datetimes are serialised to ISO-8601 strings so Flask can jsonify them
without a custom encoder).
"""

import os
from contextlib import contextmanager
from datetime import datetime

import psycopg2
import psycopg2.pool
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv(
    'DATABASE_URL',
    'postgresql://scraper:scraper@localhost:5432/scraper',
)

# Allowed column names – prevents accidental SQL injection from kwargs
_SCRAPE_COLS = frozenset({
    'status', 'progress', 'platform', 'job_keywords', 'job_location',
    'file_id', 'timestamp', 'started_at', 'jobs_found', 'jobs_processed',
    'results_count', 'output_file', 'output_filename', 'output_csv_content', 'error',
})

_CONTACT_COLS = frozenset({
    'status', 'progress', 'source_scraping_job', 'input_csv', 'output_csv',
    'input_csv_content', 'output_csv_content', 'started_at', 'contacts_found', 'total_companies', 'api_calls', 'error',
})

_pool: psycopg2.pool.ThreadedConnectionPool | None = None


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

def init() -> None:
    """Create the connection pool and ensure the schema exists."""
    global _pool
    _pool = psycopg2.pool.ThreadedConnectionPool(1, 10, DATABASE_URL)
    _create_schema()


@contextmanager
def _conn():
    conn = _pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _pool.putconn(conn)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_dict(row) -> dict | None:
    """Convert a RealDictRow (or None) to a plain dict with datetimes as strings."""
    if row is None:
        return None
    result = {}
    for k, v in dict(row).items():
        result[k] = v.isoformat() if hasattr(v, 'isoformat') else v
    return result


def _validate_fields(fields: dict, allowed: frozenset, label: str) -> None:
    bad = set(fields) - allowed
    if bad:
        raise ValueError(f"Unknown {label} field(s): {bad}")


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def _create_schema() -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            CREATE TABLE IF NOT EXISTS scrape_jobs (
                id              SERIAL       PRIMARY KEY,
                status          VARCHAR(20)  NOT NULL DEFAULT 'running',
                progress        TEXT,
                platform        VARCHAR(50),
                job_keywords    VARCHAR(200),
                job_location    VARCHAR(200),
                file_id         VARCHAR(50),
                timestamp       VARCHAR(50),
                started_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
                jobs_found      INT          NOT NULL DEFAULT 0,
                jobs_processed  INT          NOT NULL DEFAULT 0,
                results_count   INT          NOT NULL DEFAULT 0,
                output_file     TEXT,
                output_filename TEXT,
                output_csv_content TEXT,
                error           TEXT
            );

            CREATE TABLE IF NOT EXISTS contact_jobs (
                id                   SERIAL      PRIMARY KEY,
                status               VARCHAR(20) NOT NULL DEFAULT 'running',
                progress             TEXT,
                source_scraping_job  INT         REFERENCES scrape_jobs(id) ON DELETE SET NULL,
                input_csv            TEXT,
                input_csv_content    TEXT,
                output_csv           TEXT,
                output_csv_content   TEXT,
                started_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
                contacts_found       INT         NOT NULL DEFAULT 0,
                total_companies      INT         NOT NULL DEFAULT 0,
                api_calls            INT         NOT NULL DEFAULT 0,
                error                TEXT
            );

            ALTER TABLE scrape_jobs ADD COLUMN IF NOT EXISTS output_csv_content TEXT;
            ALTER TABLE contact_jobs ADD COLUMN IF NOT EXISTS input_csv_content TEXT;
            ALTER TABLE contact_jobs ADD COLUMN IF NOT EXISTS output_csv_content TEXT;
            """)


# ---------------------------------------------------------------------------
# Scrape Jobs
# ---------------------------------------------------------------------------

def create_scrape_job(data: dict) -> int:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO scrape_jobs
                    (platform, job_keywords, job_location, file_id, timestamp, started_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    data.get('platform'),
                    data.get('job_keywords'),
                    data.get('job_location'),
                    data.get('file_id'),
                    data.get('timestamp'),
                    data.get('started_at', datetime.now()),
                ),
            )
            return cur.fetchone()[0]


def update_scrape_job(job_id: int, **fields) -> None:
    if not fields:
        return
    _validate_fields(fields, _SCRAPE_COLS, 'scrape_job')
    set_clause = ', '.join(f'{k} = %s' for k in fields)
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f'UPDATE scrape_jobs SET {set_clause} WHERE id = %s',
                [*fields.values(), job_id],
            )


def get_scrape_job(job_id: int) -> dict | None:
    with _conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute('SELECT * FROM scrape_jobs WHERE id = %s', (job_id,))
            return _to_dict(cur.fetchone())


def list_scrape_jobs() -> list[dict]:
    with _conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute('SELECT * FROM scrape_jobs ORDER BY id DESC')
            return [_to_dict(r) for r in cur.fetchall()]


def delete_scrape_job(job_id: int) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute('DELETE FROM scrape_jobs WHERE id = %s', (job_id,))


# ---------------------------------------------------------------------------
# Contact Jobs
# ---------------------------------------------------------------------------

def create_contact_job(data: dict) -> int:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO contact_jobs
                    (source_scraping_job, input_csv, input_csv_content, started_at)
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                (
                    data.get('source_scraping_job'),
                    data.get('input_csv'),
                    data.get('input_csv_content'),
                    data.get('started_at', datetime.now()),
                ),
            )
            return cur.fetchone()[0]


def update_contact_job(contact_job_id: int, **fields) -> None:
    if not fields:
        return
    _validate_fields(fields, _CONTACT_COLS, 'contact_job')
    set_clause = ', '.join(f'{k} = %s' for k in fields)
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f'UPDATE contact_jobs SET {set_clause} WHERE id = %s',
                [*fields.values(), contact_job_id],
            )


def get_contact_job(contact_job_id: int) -> dict | None:
    with _conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute('SELECT * FROM contact_jobs WHERE id = %s', (contact_job_id,))
            return _to_dict(cur.fetchone())


def list_contact_jobs() -> list[dict]:
    with _conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute('SELECT * FROM contact_jobs ORDER BY id')
            return [_to_dict(r) for r in cur.fetchall()]


def delete_contact_job(contact_job_id: int) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute('DELETE FROM contact_jobs WHERE id = %s', (contact_job_id,))


def delete_contact_jobs_for_scrape(source_scraping_job: int) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute('DELETE FROM contact_jobs WHERE source_scraping_job = %s', (source_scraping_job,))
