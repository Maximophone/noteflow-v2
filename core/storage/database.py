"""SQLite database connection and schema management."""

import aiosqlite
from pathlib import Path
from typing import Optional
import json
import logging

logger = logging.getLogger(__name__)


# SQL schema for jobs table
JOBS_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    source_path TEXT,
    source_url TEXT,
    source_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    current_step TEXT,
    next_step TEXT,
    data TEXT DEFAULT '{}',
    history TEXT DEFAULT '[]',
    config TEXT DEFAULT '{}',
    tags TEXT DEFAULT '[]',
    priority INTEGER DEFAULT 0,
    error_message TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_priority ON jobs(priority DESC, created_at ASC);
"""

# SQL schema for artifacts table
ARTIFACTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    step_name TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    target TEXT NOT NULL,
    before_state TEXT,
    after_state TEXT,
    metadata TEXT DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',
    reversibility TEXT NOT NULL DEFAULT 'fully_reversible',
    error_message TEXT,
    created_at TEXT NOT NULL,
    reverted_at TEXT,
    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_artifacts_job_id ON artifacts(job_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_step_name ON artifacts(step_name);
CREATE INDEX IF NOT EXISTS idx_artifacts_status ON artifacts(status);
"""

# SQL schema for step_results table (for faster queries)
STEP_RESULTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS step_results (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    step_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    started_at TEXT,
    completed_at TEXT,
    output_data TEXT DEFAULT '{}',
    error_message TEXT,
    error_traceback TEXT,
    awaiting_input_since TEXT,
    user_input TEXT,
    reverted_at TEXT,
    revert_error TEXT,
    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_step_results_job_id ON step_results(job_id);
CREATE INDEX IF NOT EXISTS idx_step_results_status ON step_results(status);
"""


class Database:
    """
    Async SQLite database connection manager.
    
    Provides connection pooling and schema management.
    """
    
    def __init__(self, db_path: Path | str = "noteflow.db"):
        self.db_path = Path(db_path)
        self._connection: Optional[aiosqlite.Connection] = None
    
    async def connect(self) -> None:
        """Establish database connection and initialize schema."""
        if self._connection is not None:
            return
        
        # Ensure directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Connecting to database: {self.db_path}")
        self._connection = await aiosqlite.connect(
            self.db_path,
            isolation_level=None,  # Autocommit mode
        )
        
        # Enable foreign keys
        await self._connection.execute("PRAGMA foreign_keys = ON")
        
        # Enable WAL mode for better concurrency
        await self._connection.execute("PRAGMA journal_mode = WAL")
        
        # Initialize schema
        await self._init_schema()
        
        logger.info("Database connected and schema initialized")
    
    async def _init_schema(self) -> None:
        """Create tables if they don't exist."""
        async with self._connection.executescript(JOBS_SCHEMA):
            pass
        async with self._connection.executescript(ARTIFACTS_SCHEMA):
            pass
        async with self._connection.executescript(STEP_RESULTS_SCHEMA):
            pass
    
    async def close(self) -> None:
        """Close database connection."""
        if self._connection is not None:
            await self._connection.close()
            self._connection = None
            logger.info("Database connection closed")
    
    @property
    def connection(self) -> aiosqlite.Connection:
        """Get the current connection (raises if not connected)."""
        if self._connection is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._connection
    
    async def execute(self, sql: str, params: tuple = ()) -> aiosqlite.Cursor:
        """Execute a SQL statement."""
        return await self.connection.execute(sql, params)
    
    async def execute_many(self, sql: str, params_list: list[tuple]) -> None:
        """Execute a SQL statement with multiple parameter sets."""
        await self.connection.executemany(sql, params_list)
    
    async def fetch_one(self, sql: str, params: tuple = ()) -> Optional[dict]:
        """Fetch a single row as a dictionary."""
        self.connection.row_factory = aiosqlite.Row
        async with self.connection.execute(sql, params) as cursor:
            row = await cursor.fetchone()
            if row:
                return dict(row)
            return None
    
    async def fetch_all(self, sql: str, params: tuple = ()) -> list[dict]:
        """Fetch all rows as dictionaries."""
        self.connection.row_factory = aiosqlite.Row
        async with self.connection.execute(sql, params) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
    
    async def begin_transaction(self) -> None:
        """Begin an explicit transaction."""
        await self.connection.execute("BEGIN")
    
    async def commit(self) -> None:
        """Commit the current transaction."""
        await self.connection.commit()
    
    async def rollback(self) -> None:
        """Rollback the current transaction."""
        await self.connection.rollback()


# Utility functions for JSON serialization in SQLite

def serialize_json(data) -> str:
    """Serialize data to JSON string for storage."""
    return json.dumps(data, default=str)


def deserialize_json(data: Optional[str], default=None):
    """Deserialize JSON string from storage."""
    if data is None:
        return default
    try:
        return json.loads(data)
    except json.JSONDecodeError:
        return default

