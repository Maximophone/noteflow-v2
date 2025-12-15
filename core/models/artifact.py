"""Artifact model - tracks side effects created by processors."""

from datetime import datetime
from typing import Optional, Any
from pydantic import BaseModel, Field
from uuid import uuid4

from .enums import ArtifactType, ArtifactStatus, ReversibilityLevel


class Artifact(BaseModel):
    """
    Represents any side effect created by a processor.
    
    Artifacts are the key to reversibility - every file created, API call made,
    or frontmatter change is tracked here. When reverting, we walk through
    artifacts in reverse order and undo each one.
    """
    
    id: str = Field(default_factory=lambda: str(uuid4()))
    """Unique identifier for this artifact."""
    
    job_id: str
    """The job that created this artifact."""
    
    step_name: str
    """Which processing step created this artifact."""
    
    artifact_type: ArtifactType
    """What kind of artifact this is (file, API call, etc.)."""
    
    # Target information
    target: str
    """
    The target of the artifact:
    - For files: the file path
    - For API calls: service:action format (e.g., "notion:create_page")
    - For frontmatter: the file path
    """
    
    # State for reversal
    before_state: Optional[str] = None
    """
    The state before this artifact was created.
    - For file modifications: the original content
    - For file creations: None
    - For API calls: None (or previous state if modifying)
    """
    
    after_state: Optional[str] = None
    """
    The state after this artifact was created.
    - For file operations: the new content
    - For API calls: response data (JSON string)
    """
    
    # Metadata
    metadata: dict[str, Any] = Field(default_factory=dict)
    """
    Additional metadata about the artifact.
    - For API calls: request params, response status
    - For files: encoding, permissions
    - For frontmatter: the specific fields changed
    """
    
    # Status tracking
    status: ArtifactStatus = ArtifactStatus.PENDING
    """Current status of this artifact."""
    
    reversibility: ReversibilityLevel = ReversibilityLevel.FULLY_REVERSIBLE
    """How reversible this artifact is."""
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    """When this artifact was created."""
    
    reverted_at: Optional[datetime] = None
    """When this artifact was reverted (if applicable)."""
    
    # Error tracking
    error_message: Optional[str] = None
    """Error message if the artifact creation/revert failed."""
    
    class Config:
        """Pydantic configuration."""
        use_enum_values = True
    
    def mark_created(self) -> None:
        """Mark this artifact as successfully created."""
        self.status = ArtifactStatus.CREATED
    
    def mark_reverted(self) -> None:
        """Mark this artifact as reverted."""
        self.status = ArtifactStatus.REVERTED
        self.reverted_at = datetime.utcnow()
    
    def mark_failed(self, error: str) -> None:
        """Mark this artifact as failed."""
        self.status = ArtifactStatus.FAILED
        self.error_message = error
    
    def mark_irreversible(self, reason: Optional[str] = None) -> None:
        """Mark this artifact as irreversible."""
        self.status = ArtifactStatus.IRREVERSIBLE
        self.reversibility = ReversibilityLevel.IRREVERSIBLE
        if reason:
            self.metadata["irreversible_reason"] = reason
    
    @property
    def can_revert(self) -> bool:
        """Check if this artifact can be reverted."""
        return (
            self.status == ArtifactStatus.CREATED
            and self.reversibility != ReversibilityLevel.IRREVERSIBLE
        )
    
    @property
    def is_file_artifact(self) -> bool:
        """Check if this artifact is a file operation."""
        return self.artifact_type in (
            ArtifactType.FILE_CREATE,
            ArtifactType.FILE_MODIFY,
            ArtifactType.FILE_DELETE,
            ArtifactType.FILE_MOVE,
        )
    
    @property
    def is_external_artifact(self) -> bool:
        """Check if this artifact involves an external service."""
        return self.artifact_type in (
            ArtifactType.EXTERNAL_API_CREATE,
            ArtifactType.EXTERNAL_API_MODIFY,
        )

