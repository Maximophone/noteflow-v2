"""Job storage layer."""

from typing import Optional
from datetime import datetime
import json

from .database import Database, serialize_json, deserialize_json
from ..models import Job, JobStatus, StepResult


class JobStore:
    """
    Persistent storage for jobs.
    
    Handles CRUD operations and queries for Job objects.
    """
    
    def __init__(self, database: Database):
        self.db = database
    
    async def save(self, job: Job) -> None:
        """Save a job (insert or update)."""
        # Serialize history (list of StepResult)
        history_json = serialize_json([r.model_dump() for r in job.history])
        
        sql = """
        INSERT INTO jobs (
            id, source_type, source_path, source_url, source_name,
            status, current_step, next_step, data, history, config, tags,
            priority, error_message, created_at, started_at, completed_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            source_type = excluded.source_type,
            source_path = excluded.source_path,
            source_url = excluded.source_url,
            source_name = excluded.source_name,
            status = excluded.status,
            current_step = excluded.current_step,
            next_step = excluded.next_step,
            data = excluded.data,
            history = excluded.history,
            config = excluded.config,
            tags = excluded.tags,
            priority = excluded.priority,
            error_message = excluded.error_message,
            started_at = excluded.started_at,
            completed_at = excluded.completed_at,
            updated_at = excluded.updated_at
        """
        
        await self.db.execute(sql, (
            job.id,
            job.source_type,
            job.source_path,
            job.source_url,
            job.source_name,
            job.status,
            job.current_step,
            job.next_step,
            serialize_json(job.data),
            history_json,
            serialize_json(job.config),
            serialize_json(job.tags),
            job.priority,
            job.error_message,
            job.created_at.isoformat() if job.created_at else None,
            job.started_at.isoformat() if job.started_at else None,
            job.completed_at.isoformat() if job.completed_at else None,
            job.updated_at.isoformat() if job.updated_at else None,
        ))
    
    async def get(self, job_id: str) -> Optional[Job]:
        """Get a job by ID."""
        row = await self.db.fetch_one(
            "SELECT * FROM jobs WHERE id = ?",
            (job_id,)
        )
        if row:
            return self._row_to_job(row)
        return None
    
    async def delete(self, job_id: str) -> bool:
        """Delete a job by ID. Returns True if deleted."""
        cursor = await self.db.execute(
            "DELETE FROM jobs WHERE id = ?",
            (job_id,)
        )
        return cursor.rowcount > 0
    
    async def list_all(
        self,
        limit: int = 100,
        offset: int = 0,
        status: Optional[JobStatus] = None,
        order_by: str = "created_at",
        order_dir: str = "DESC",
    ) -> list[Job]:
        """List jobs with optional filtering."""
        sql = "SELECT * FROM jobs"
        params = []
        
        if status:
            sql += " WHERE status = ?"
            params.append(status.value if isinstance(status, JobStatus) else status)
        
        # Validate order_by to prevent SQL injection
        valid_columns = ["created_at", "updated_at", "priority", "status"]
        if order_by not in valid_columns:
            order_by = "created_at"
        
        order_dir = "DESC" if order_dir.upper() == "DESC" else "ASC"
        sql += f" ORDER BY {order_by} {order_dir}"
        sql += " LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        
        rows = await self.db.fetch_all(sql, tuple(params))
        return [self._row_to_job(row) for row in rows]
    
    async def list_pending(self, limit: int = 50) -> list[Job]:
        """Get pending jobs ordered by priority."""
        rows = await self.db.fetch_all(
            """
            SELECT * FROM jobs 
            WHERE status = 'pending'
            ORDER BY priority DESC, created_at ASC
            LIMIT ?
            """,
            (limit,)
        )
        return [self._row_to_job(row) for row in rows]
    
    async def list_awaiting_input(self) -> list[Job]:
        """Get all jobs waiting for user input."""
        rows = await self.db.fetch_all(
            "SELECT * FROM jobs WHERE status = 'awaiting_input' ORDER BY updated_at ASC"
        )
        return [self._row_to_job(row) for row in rows]
    
    async def list_active(self) -> list[Job]:
        """Get all active (non-terminal) jobs."""
        rows = await self.db.fetch_all(
            """
            SELECT * FROM jobs 
            WHERE status IN ('pending', 'processing', 'awaiting_input')
            ORDER BY priority DESC, created_at ASC
            """
        )
        return [self._row_to_job(row) for row in rows]
    
    async def count_by_status(self) -> dict[str, int]:
        """Get count of jobs by status."""
        rows = await self.db.fetch_all(
            "SELECT status, COUNT(*) as count FROM jobs GROUP BY status"
        )
        # Ensure no None keys (use "unknown" as fallback)
        return {
            (row["status"] or "unknown"): row["count"] 
            for row in rows
        }
    
    async def update_status(
        self,
        job_id: str,
        status: JobStatus,
        current_step: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """Quick status update without full save."""
        now = datetime.utcnow().isoformat()
        
        sql = "UPDATE jobs SET status = ?, updated_at = ?"
        params = [status.value if isinstance(status, JobStatus) else status, now]
        
        if current_step is not None:
            sql += ", current_step = ?"
            params.append(current_step)
        
        if error_message is not None:
            sql += ", error_message = ?"
            params.append(error_message)
        
        if status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
            sql += ", completed_at = ?"
            params.append(now)
        
        sql += " WHERE id = ?"
        params.append(job_id)
        
        await self.db.execute(sql, tuple(params))
    
    def _row_to_job(self, row: dict) -> Job:
        """Convert a database row to a Job object."""
        # Parse datetime strings
        def parse_datetime(val):
            if val:
                return datetime.fromisoformat(val)
            return None
        
        # Parse history JSON back to StepResult objects
        history_data = deserialize_json(row.get("history"), [])
        history = [StepResult(**step) for step in history_data]
        
        return Job(
            id=row["id"],
            source_type=row["source_type"],
            source_path=row.get("source_path"),
            source_url=row.get("source_url"),
            source_name=row["source_name"],
            status=row["status"],
            current_step=row.get("current_step"),
            next_step=row.get("next_step"),
            data=deserialize_json(row.get("data"), {}),
            history=history,
            config=deserialize_json(row.get("config"), {}),
            tags=deserialize_json(row.get("tags"), []),
            priority=row.get("priority", 0),
            error_message=row.get("error_message"),
            created_at=parse_datetime(row.get("created_at")) or datetime.utcnow(),
            started_at=parse_datetime(row.get("started_at")),
            completed_at=parse_datetime(row.get("completed_at")),
            updated_at=parse_datetime(row.get("updated_at")) or datetime.utcnow(),
        )

