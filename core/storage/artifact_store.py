"""Artifact storage layer."""

from typing import Optional
from datetime import datetime

from .database import Database, serialize_json, deserialize_json
from ..models import Artifact, ArtifactType, ArtifactStatus


class ArtifactStore:
    """
    Persistent storage for artifacts.
    
    Artifacts track all side effects created by processors, enabling reversal.
    """
    
    def __init__(self, database: Database):
        self.db = database
    
    async def save(self, artifact: Artifact) -> None:
        """Save an artifact (insert or update)."""
        sql = """
        INSERT INTO artifacts (
            id, job_id, step_name, artifact_type, target,
            before_state, after_state, metadata, status, reversibility,
            error_message, created_at, reverted_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            status = excluded.status,
            reversibility = excluded.reversibility,
            error_message = excluded.error_message,
            reverted_at = excluded.reverted_at
        """
        
        await self.db.execute(sql, (
            artifact.id,
            artifact.job_id,
            artifact.step_name,
            artifact.artifact_type,
            artifact.target,
            artifact.before_state,
            artifact.after_state,
            serialize_json(artifact.metadata),
            artifact.status,
            artifact.reversibility,
            artifact.error_message,
            artifact.created_at.isoformat() if artifact.created_at else None,
            artifact.reverted_at.isoformat() if artifact.reverted_at else None,
        ))
    
    async def save_many(self, artifacts: list[Artifact]) -> None:
        """Save multiple artifacts in a batch."""
        for artifact in artifacts:
            await self.save(artifact)
    
    async def get(self, artifact_id: str) -> Optional[Artifact]:
        """Get an artifact by ID."""
        row = await self.db.fetch_one(
            "SELECT * FROM artifacts WHERE id = ?",
            (artifact_id,)
        )
        if row:
            return self._row_to_artifact(row)
        return None
    
    async def delete(self, artifact_id: str) -> bool:
        """Delete an artifact by ID. Returns True if deleted."""
        cursor = await self.db.execute(
            "DELETE FROM artifacts WHERE id = ?",
            (artifact_id,)
        )
        return cursor.rowcount > 0
    
    async def list_by_job(
        self,
        job_id: str,
        status: Optional[ArtifactStatus] = None,
    ) -> list[Artifact]:
        """Get all artifacts for a job."""
        sql = "SELECT * FROM artifacts WHERE job_id = ?"
        params = [job_id]
        
        if status:
            sql += " AND status = ?"
            params.append(status.value if isinstance(status, ArtifactStatus) else status)
        
        sql += " ORDER BY created_at ASC"
        
        rows = await self.db.fetch_all(sql, tuple(params))
        return [self._row_to_artifact(row) for row in rows]
    
    async def list_by_step(self, job_id: str, step_name: str) -> list[Artifact]:
        """Get all artifacts for a specific step of a job."""
        rows = await self.db.fetch_all(
            """
            SELECT * FROM artifacts 
            WHERE job_id = ? AND step_name = ?
            ORDER BY created_at ASC
            """,
            (job_id, step_name)
        )
        return [self._row_to_artifact(row) for row in rows]
    
    async def list_reversible_by_job(self, job_id: str) -> list[Artifact]:
        """Get all reversible artifacts for a job (in reverse order for undo)."""
        rows = await self.db.fetch_all(
            """
            SELECT * FROM artifacts 
            WHERE job_id = ? 
              AND status = 'created' 
              AND reversibility != 'irreversible'
            ORDER BY created_at DESC
            """,
            (job_id,)
        )
        return [self._row_to_artifact(row) for row in rows]
    
    async def list_by_target(self, target: str) -> list[Artifact]:
        """Get all artifacts affecting a specific target (file path, API endpoint)."""
        rows = await self.db.fetch_all(
            "SELECT * FROM artifacts WHERE target = ? ORDER BY created_at DESC",
            (target,)
        )
        return [self._row_to_artifact(row) for row in rows]
    
    async def mark_reverted(self, artifact_id: str) -> None:
        """Mark an artifact as reverted."""
        now = datetime.utcnow().isoformat()
        await self.db.execute(
            "UPDATE artifacts SET status = 'reverted', reverted_at = ? WHERE id = ?",
            (now, artifact_id)
        )
    
    async def mark_failed(self, artifact_id: str, error: str) -> None:
        """Mark an artifact as failed."""
        await self.db.execute(
            "UPDATE artifacts SET status = 'failed', error_message = ? WHERE id = ?",
            (error, artifact_id)
        )
    
    async def mark_irreversible(self, artifact_id: str, reason: Optional[str] = None) -> None:
        """Mark an artifact as irreversible."""
        metadata = {}
        if reason:
            metadata["irreversible_reason"] = reason
        
        await self.db.execute(
            """
            UPDATE artifacts 
            SET status = 'irreversible', reversibility = 'irreversible', metadata = ?
            WHERE id = ?
            """,
            (serialize_json(metadata), artifact_id)
        )
    
    async def count_by_job(self, job_id: str) -> dict[str, int]:
        """Get artifact counts by status for a job."""
        rows = await self.db.fetch_all(
            "SELECT status, COUNT(*) as count FROM artifacts WHERE job_id = ? GROUP BY status",
            (job_id,)
        )
        return {row["status"]: row["count"] for row in rows}
    
    async def delete_by_job(self, job_id: str) -> int:
        """Delete all artifacts for a job. Returns count deleted."""
        cursor = await self.db.execute(
            "DELETE FROM artifacts WHERE job_id = ?",
            (job_id,)
        )
        return cursor.rowcount
    
    def _row_to_artifact(self, row: dict) -> Artifact:
        """Convert a database row to an Artifact object."""
        def parse_datetime(val):
            if val:
                return datetime.fromisoformat(val)
            return None
        
        return Artifact(
            id=row["id"],
            job_id=row["job_id"],
            step_name=row["step_name"],
            artifact_type=row["artifact_type"],
            target=row["target"],
            before_state=row.get("before_state"),
            after_state=row.get("after_state"),
            metadata=deserialize_json(row.get("metadata"), {}),
            status=row["status"],
            reversibility=row["reversibility"],
            error_message=row.get("error_message"),
            created_at=parse_datetime(row.get("created_at")) or datetime.utcnow(),
            reverted_at=parse_datetime(row.get("reverted_at")),
        )

