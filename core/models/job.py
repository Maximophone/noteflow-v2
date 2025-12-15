"""Job model - the primary unit of work in the pipeline."""

from datetime import datetime
from typing import Optional, Any
from pydantic import BaseModel, Field
from uuid import uuid4

from .enums import JobStatus
from .step import StepResult


class Job(BaseModel):
    """
    Represents a unit of work flowing through the pipeline.
    
    A job tracks the entire lifecycle of processing something (e.g., an audio
    recording becoming a transcription, then identified speakers, then a
    meeting note).
    """
    
    id: str = Field(default_factory=lambda: str(uuid4()))
    """Unique identifier for this job."""
    
    # Source information
    source_type: str
    """
    Type of source that initiated this job:
    - "file": Local file was added
    - "url": URL was provided
    - "api": Created via API
    - "manual": User manually created
    """
    
    source_path: Optional[str] = None
    """Original source path (for file-based jobs)."""
    
    source_url: Optional[str] = None
    """Original source URL (for URL-based jobs)."""
    
    source_name: str
    """Human-readable name for the source (for display)."""
    
    # Pipeline state
    status: JobStatus = JobStatus.PENDING
    """Current status of this job."""
    
    current_step: Optional[str] = None
    """Name of the step currently being executed (or awaiting)."""
    
    next_step: Optional[str] = None
    """Name of the next step to execute (computed by router)."""
    
    # Mutable data context
    data: dict[str, Any] = Field(default_factory=dict)
    """
    Mutable context passed between processing steps.
    Each step can read from and write to this.
    """
    
    # History
    history: list[StepResult] = Field(default_factory=list)
    """
    Ordered list of all step executions.
    Used for reverting and auditing.
    """
    
    # Configuration
    config: dict[str, Any] = Field(default_factory=dict)
    """
    Job-specific configuration that overrides processor defaults.
    """
    
    # Tags/labels
    tags: list[str] = Field(default_factory=list)
    """User-defined tags for organization."""
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    """When this job was created."""
    
    started_at: Optional[datetime] = None
    """When this job started processing."""
    
    completed_at: Optional[datetime] = None
    """When this job finished (success, failure, or cancellation)."""
    
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    """When this job was last updated."""
    
    # Error tracking
    error_message: Optional[str] = None
    """Error message if the job failed."""
    
    # Priority
    priority: int = 0
    """Job priority (higher = processed first)."""
    
    class Config:
        """Pydantic configuration."""
        use_enum_values = True
    
    # State transitions
    
    def start_processing(self, step_name: str) -> None:
        """Mark the job as starting to process a step."""
        self.status = JobStatus.PROCESSING
        self.current_step = step_name
        if self.started_at is None:
            self.started_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()
    
    def await_input(self, step_name: str) -> None:
        """Mark the job as waiting for user input."""
        self.status = JobStatus.AWAITING_INPUT
        self.current_step = step_name
        self.updated_at = datetime.utcnow()
    
    def complete(self) -> None:
        """Mark the job as successfully completed."""
        self.status = JobStatus.COMPLETED
        self.current_step = None
        self.completed_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()
    
    def fail(self, error: str) -> None:
        """Mark the job as failed."""
        self.status = JobStatus.FAILED
        self.error_message = error
        self.completed_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()
    
    def cancel(self) -> None:
        """Mark the job as cancelled."""
        self.status = JobStatus.CANCELLED
        self.completed_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()
    
    def start_revert(self) -> None:
        """Mark the job as being reverted."""
        self.status = JobStatus.REVERTING
        self.updated_at = datetime.utcnow()
    
    def complete_revert(self, to_step: Optional[str] = None) -> None:
        """Mark the job as reverted."""
        self.status = JobStatus.REVERTED if to_step is None else JobStatus.PENDING
        self.current_step = to_step
        self.updated_at = datetime.utcnow()
    
    # History management
    
    def add_step_result(self, result: StepResult) -> None:
        """Add a step result to history."""
        self.history.append(result)
        self.updated_at = datetime.utcnow()
    
    def get_step_result(self, step_name: str) -> Optional[StepResult]:
        """Get the most recent result for a specific step."""
        for result in reversed(self.history):
            if result.step_name == step_name:
                return result
        return None
    
    def get_completed_steps(self) -> list[str]:
        """Get names of all completed steps."""
        return [
            r.step_name for r in self.history
            if r.status == "completed"
        ]
    
    def has_completed_step(self, step_name: str) -> bool:
        """Check if a specific step has been completed."""
        return step_name in self.get_completed_steps()
    
    # Data access
    
    def get_data(self, key: str, default: Any = None) -> Any:
        """Get a value from the job's data context."""
        return self.data.get(key, default)
    
    def set_data(self, key: str, value: Any) -> None:
        """Set a value in the job's data context."""
        self.data[key] = value
        self.updated_at = datetime.utcnow()
    
    def merge_data(self, data: dict[str, Any]) -> None:
        """Merge data into the job's data context."""
        self.data.update(data)
        self.updated_at = datetime.utcnow()
    
    # Computed properties
    
    @property
    def is_active(self) -> bool:
        """Check if the job is currently active (not terminal)."""
        return self.status in (
            JobStatus.PENDING,
            JobStatus.PROCESSING,
            JobStatus.AWAITING_INPUT,
        )
    
    @property
    def is_terminal(self) -> bool:
        """Check if the job is in a terminal state."""
        return self.status in (
            JobStatus.COMPLETED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
            JobStatus.REVERTED,
        )
    
    @property
    def duration_seconds(self) -> Optional[float]:
        """Calculate total processing time."""
        if self.started_at:
            end = self.completed_at or datetime.utcnow()
            return (end - self.started_at).total_seconds()
        return None
    
    @property
    def all_artifacts(self) -> list:
        """Get all artifacts from all steps."""
        artifacts = []
        for result in self.history:
            artifacts.extend(result.artifacts)
        return artifacts
    
    @property 
    def reversible_steps(self) -> list[StepResult]:
        """Get all steps that can be reverted."""
        return [r for r in self.history if r.can_revert]

