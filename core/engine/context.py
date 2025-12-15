"""Execution context - transaction-like wrapper for processor operations."""

from pathlib import Path
from typing import Optional, Any
from datetime import datetime
import aiofiles
import aiofiles.os
import json
import logging
import traceback

from ..models import (
    Job,
    Artifact,
    ArtifactType,
    ArtifactStatus,
    ReversibilityLevel,
)
from ..storage import ArtifactStore

logger = logging.getLogger(__name__)


class ExecutionContext:
    """
    Transaction-like context for processor operations.
    
    All side effects (file creation, API calls, etc.) should go through this
    context so they can be tracked and potentially reverted.
    
    Usage:
        async with ExecutionContext(job, step_name, artifact_store) as ctx:
            await ctx.create_file(path, content)
            await ctx.update_frontmatter(path, {"key": "value"})
            # If an exception occurs, pending artifacts are rolled back
    """
    
    def __init__(
        self,
        job: Job,
        step_name: str,
        artifact_store: ArtifactStore,
    ):
        self.job = job
        self.step_name = step_name
        self._artifact_store = artifact_store
        self._pending_artifacts: list[Artifact] = []
        self._committed = False
    
    async def __aenter__(self) -> "ExecutionContext":
        """Enter the context."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Exit the context, handling commit or rollback."""
        if exc_type is not None:
            # An exception occurred - rollback pending artifacts
            logger.warning(
                f"Exception in context for job {self.job.id}, step {self.step_name}: "
                f"{exc_type.__name__}: {exc_val}"
            )
            await self.rollback()
            return False  # Don't suppress the exception
        
        if not self._committed:
            # Auto-commit on successful exit
            await self.commit()
        
        return False
    
    # -------------------------------------------------------------------------
    # File Operations
    # -------------------------------------------------------------------------
    
    async def create_file(
        self,
        path: Path | str,
        content: str,
        encoding: str = "utf-8",
    ) -> Artifact:
        """
        Create a new file and track it as an artifact.
        
        Args:
            path: Path to create the file at
            content: File content
            encoding: Text encoding (default utf-8)
        
        Returns:
            The created artifact
        
        Raises:
            FileExistsError: If the file already exists
        """
        path = Path(path)
        
        if path.exists():
            raise FileExistsError(f"File already exists: {path}")
        
        artifact = Artifact(
            job_id=self.job.id,
            step_name=self.step_name,
            artifact_type=ArtifactType.FILE_CREATE,
            target=str(path),
            after_state=content,
            metadata={"encoding": encoding},
            reversibility=ReversibilityLevel.FULLY_REVERSIBLE,
        )
        
        # Create parent directories if needed
        path.parent.mkdir(parents=True, exist_ok=True)
        
        # Write the file
        async with aiofiles.open(path, "w", encoding=encoding) as f:
            await f.write(content)
        
        artifact.mark_created()
        self._pending_artifacts.append(artifact)
        
        logger.debug(f"Created file: {path}")
        return artifact
    
    async def modify_file(
        self,
        path: Path | str,
        new_content: str,
        encoding: str = "utf-8",
    ) -> Artifact:
        """
        Modify an existing file, storing the original content for reversal.
        
        Args:
            path: Path to the file
            new_content: New file content
            encoding: Text encoding (default utf-8)
        
        Returns:
            The created artifact
        
        Raises:
            FileNotFoundError: If the file doesn't exist
        """
        path = Path(path)
        
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        
        # Read current content for reversal
        async with aiofiles.open(path, "r", encoding=encoding) as f:
            before_content = await f.read()
        
        artifact = Artifact(
            job_id=self.job.id,
            step_name=self.step_name,
            artifact_type=ArtifactType.FILE_MODIFY,
            target=str(path),
            before_state=before_content,
            after_state=new_content,
            metadata={"encoding": encoding},
            reversibility=ReversibilityLevel.FULLY_REVERSIBLE,
        )
        
        # Write new content
        async with aiofiles.open(path, "w", encoding=encoding) as f:
            await f.write(new_content)
        
        artifact.mark_created()
        self._pending_artifacts.append(artifact)
        
        logger.debug(f"Modified file: {path}")
        return artifact
    
    async def delete_file(self, path: Path | str) -> Artifact:
        """
        Delete a file, storing its content for reversal.
        
        Args:
            path: Path to the file to delete
        
        Returns:
            The created artifact
        
        Raises:
            FileNotFoundError: If the file doesn't exist
        """
        path = Path(path)
        
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        
        # Read current content for reversal
        async with aiofiles.open(path, "r", encoding="utf-8") as f:
            before_content = await f.read()
        
        artifact = Artifact(
            job_id=self.job.id,
            step_name=self.step_name,
            artifact_type=ArtifactType.FILE_DELETE,
            target=str(path),
            before_state=before_content,
            metadata={"original_path": str(path)},
            reversibility=ReversibilityLevel.FULLY_REVERSIBLE,
        )
        
        # Delete the file
        await aiofiles.os.remove(path)
        
        artifact.mark_created()
        self._pending_artifacts.append(artifact)
        
        logger.debug(f"Deleted file: {path}")
        return artifact
    
    async def move_file(self, source: Path | str, dest: Path | str) -> Artifact:
        """
        Move/rename a file.
        
        Args:
            source: Source path
            dest: Destination path
        
        Returns:
            The created artifact
        """
        source = Path(source)
        dest = Path(dest)
        
        if not source.exists():
            raise FileNotFoundError(f"Source file not found: {source}")
        
        if dest.exists():
            raise FileExistsError(f"Destination already exists: {dest}")
        
        artifact = Artifact(
            job_id=self.job.id,
            step_name=self.step_name,
            artifact_type=ArtifactType.FILE_MOVE,
            target=str(dest),
            before_state=str(source),
            after_state=str(dest),
            reversibility=ReversibilityLevel.FULLY_REVERSIBLE,
        )
        
        # Create parent directories if needed
        dest.parent.mkdir(parents=True, exist_ok=True)
        
        # Move the file
        await aiofiles.os.rename(source, dest)
        
        artifact.mark_created()
        self._pending_artifacts.append(artifact)
        
        logger.debug(f"Moved file: {source} -> {dest}")
        return artifact
    
    # -------------------------------------------------------------------------
    # Frontmatter Operations
    # -------------------------------------------------------------------------
    
    async def update_frontmatter(
        self,
        path: Path | str,
        updates: dict[str, Any],
    ) -> Artifact:
        """
        Update frontmatter in a markdown file.
        
        Args:
            path: Path to the markdown file
            updates: Dictionary of frontmatter fields to update
        
        Returns:
            The created artifact
        """
        path = Path(path)
        
        # Read current content
        async with aiofiles.open(path, "r", encoding="utf-8") as f:
            content = await f.read()
        
        # Parse existing frontmatter
        before_frontmatter, body = self._parse_frontmatter(content)
        
        # Apply updates
        after_frontmatter = {**before_frontmatter, **updates}
        
        # Rebuild content
        new_content = self._build_frontmatter(after_frontmatter) + body
        
        artifact = Artifact(
            job_id=self.job.id,
            step_name=self.step_name,
            artifact_type=ArtifactType.FRONTMATTER_UPDATE,
            target=str(path),
            before_state=json.dumps(before_frontmatter),
            after_state=json.dumps(after_frontmatter),
            metadata={"updates": updates},
            reversibility=ReversibilityLevel.FULLY_REVERSIBLE,
        )
        
        # Write updated content
        async with aiofiles.open(path, "w", encoding="utf-8") as f:
            await f.write(new_content)
        
        artifact.mark_created()
        self._pending_artifacts.append(artifact)
        
        logger.debug(f"Updated frontmatter in: {path}")
        return artifact
    
    def _parse_frontmatter(self, content: str) -> tuple[dict, str]:
        """Parse frontmatter from markdown content."""
        import yaml
        
        lines = content.split("\n")
        if not lines or lines[0].strip() != "---":
            return {}, content
        
        # Find closing delimiter
        end_idx = -1
        for i, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                end_idx = i
                break
        
        if end_idx == -1:
            return {}, content
        
        # Parse YAML
        yaml_content = "\n".join(lines[1:end_idx])
        try:
            frontmatter = yaml.safe_load(yaml_content) or {}
        except yaml.YAMLError:
            return {}, content
        
        # Return frontmatter and body
        body = "\n".join(lines[end_idx + 1:])
        return frontmatter, body
    
    def _build_frontmatter(self, frontmatter: dict) -> str:
        """Build frontmatter string from dictionary."""
        import yaml
        
        if not frontmatter:
            return ""
        
        yaml_str = yaml.dump(frontmatter, allow_unicode=True, default_flow_style=False)
        return f"---\n{yaml_str}---\n"
    
    # -------------------------------------------------------------------------
    # External API Operations
    # -------------------------------------------------------------------------
    
    async def record_api_call(
        self,
        service: str,
        action: str,
        request_data: dict[str, Any],
        response_data: dict[str, Any],
        reversible: bool = False,
        reverse_action: Optional[str] = None,
    ) -> Artifact:
        """
        Record an external API call as an artifact.
        
        For external services like Notion, we can't automatically revert,
        but we can track what was done.
        
        Args:
            service: Service name (e.g., "notion", "discord")
            action: Action performed (e.g., "create_page", "send_message")
            request_data: Request parameters
            response_data: Response from the API
            reversible: Whether this action can be reversed
            reverse_action: The action to call to reverse this (if reversible)
        
        Returns:
            The created artifact
        """
        artifact = Artifact(
            job_id=self.job.id,
            step_name=self.step_name,
            artifact_type=ArtifactType.EXTERNAL_API_CREATE,
            target=f"{service}:{action}",
            after_state=json.dumps(response_data),
            metadata={
                "service": service,
                "action": action,
                "request": request_data,
                "response": response_data,
                "reverse_action": reverse_action,
            },
            reversibility=(
                ReversibilityLevel.PARTIALLY_REVERSIBLE if reversible
                else ReversibilityLevel.IRREVERSIBLE
            ),
        )
        
        if not reversible:
            artifact.mark_irreversible(
                f"External API call to {service}:{action} cannot be automatically reversed"
            )
        else:
            artifact.mark_created()
        
        self._pending_artifacts.append(artifact)
        
        logger.debug(f"Recorded API call: {service}:{action}")
        return artifact
    
    # -------------------------------------------------------------------------
    # Transaction Management
    # -------------------------------------------------------------------------
    
    async def commit(self) -> list[Artifact]:
        """
        Commit all pending artifacts to storage.
        
        Returns:
            List of committed artifacts
        """
        if self._committed:
            return self._pending_artifacts
        
        for artifact in self._pending_artifacts:
            await self._artifact_store.save(artifact)
        
        self._committed = True
        logger.debug(
            f"Committed {len(self._pending_artifacts)} artifacts for "
            f"job {self.job.id}, step {self.step_name}"
        )
        
        return self._pending_artifacts
    
    async def rollback(self) -> None:
        """
        Rollback all pending artifacts (undo side effects).
        
        Called automatically if an exception occurs within the context.
        """
        if self._committed:
            logger.warning("Cannot rollback: artifacts already committed")
            return
        
        # Rollback in reverse order
        for artifact in reversed(self._pending_artifacts):
            try:
                await self._revert_artifact(artifact)
            except Exception as e:
                logger.error(
                    f"Error rolling back artifact {artifact.id}: {e}\n"
                    f"{traceback.format_exc()}"
                )
        
        self._pending_artifacts.clear()
        logger.debug(f"Rolled back pending artifacts for job {self.job.id}")
    
    async def _revert_artifact(self, artifact: Artifact) -> None:
        """Revert a single artifact."""
        if artifact.artifact_type == ArtifactType.FILE_CREATE:
            # Delete the created file
            path = Path(artifact.target)
            if path.exists():
                await aiofiles.os.remove(path)
                logger.debug(f"Reverted file creation: {path}")
        
        elif artifact.artifact_type == ArtifactType.FILE_MODIFY:
            # Restore original content
            path = Path(artifact.target)
            if artifact.before_state is not None:
                async with aiofiles.open(path, "w", encoding="utf-8") as f:
                    await f.write(artifact.before_state)
                logger.debug(f"Reverted file modification: {path}")
        
        elif artifact.artifact_type == ArtifactType.FILE_DELETE:
            # Recreate the deleted file
            path = Path(artifact.target)
            if artifact.before_state is not None:
                async with aiofiles.open(path, "w", encoding="utf-8") as f:
                    await f.write(artifact.before_state)
                logger.debug(f"Reverted file deletion: {path}")
        
        elif artifact.artifact_type == ArtifactType.FILE_MOVE:
            # Move back to original location
            if artifact.before_state and artifact.after_state:
                dest = Path(artifact.after_state)
                source = Path(artifact.before_state)
                if dest.exists():
                    await aiofiles.os.rename(dest, source)
                logger.debug(f"Reverted file move: {dest} -> {source}")
        
        elif artifact.artifact_type == ArtifactType.FRONTMATTER_UPDATE:
            # Restore original frontmatter
            path = Path(artifact.target)
            if artifact.before_state and path.exists():
                before_fm = json.loads(artifact.before_state)
                async with aiofiles.open(path, "r", encoding="utf-8") as f:
                    content = await f.read()
                _, body = self._parse_frontmatter(content)
                new_content = self._build_frontmatter(before_fm) + body
                async with aiofiles.open(path, "w", encoding="utf-8") as f:
                    await f.write(new_content)
                logger.debug(f"Reverted frontmatter update: {path}")
    
    @property
    def artifacts(self) -> list[Artifact]:
        """Get all pending artifacts."""
        return self._pending_artifacts.copy()

