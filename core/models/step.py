"""Step models - processing step definitions and results."""

from datetime import datetime
from typing import Optional, Any
from pydantic import BaseModel, Field
from uuid import uuid4

from .enums import StepStatus
from .artifact import Artifact


class StepDefinition(BaseModel):
    """
    Defines a processing step in the pipeline.
    
    This is loaded from processor manifests and defines what a step does,
    its dependencies, and configuration.
    """
    
    name: str
    """Unique identifier for this step (processor name)."""
    
    display_name: str
    """Human-readable name for UI."""
    
    description: str = ""
    """Description of what this step does."""
    
    requires: list[str] = Field(default_factory=list)
    """Names of steps that must complete before this one."""
    
    # Configuration
    config_schema: dict[str, Any] = Field(default_factory=dict)
    """JSON Schema for the step's configuration options."""
    
    default_config: dict[str, Any] = Field(default_factory=dict)
    """Default values for configuration."""
    
    # UI
    has_ui: bool = False
    """Whether this step has a custom UI component."""
    
    requires_input: str = "never"  # "never", "always", "conditional"
    """When this step requires user input."""
    
    # Behavior
    can_skip: bool = True
    """Whether this step can be skipped if conditions aren't met."""
    
    auto_revert_on_error: bool = True
    """Whether to auto-revert artifacts if the step fails."""


class StepResult(BaseModel):
    """
    Records the result of executing a processing step.
    
    This is stored as part of job history and contains everything needed
    to understand what happened and to revert it.
    """
    
    id: str = Field(default_factory=lambda: str(uuid4()))
    """Unique identifier for this step execution."""
    
    job_id: str
    """The job this step was executed for."""
    
    step_name: str
    """The processor/step that was executed."""
    
    # Status
    status: StepStatus = StepStatus.PENDING
    """Current status of this step."""
    
    # Timing
    started_at: Optional[datetime] = None
    """When this step started executing."""
    
    completed_at: Optional[datetime] = None
    """When this step finished (success or failure)."""
    
    # Results
    artifacts: list[Artifact] = Field(default_factory=list)
    """All artifacts created by this step (for reversal)."""
    
    output_data: dict[str, Any] = Field(default_factory=dict)
    """Data produced by this step (passed to subsequent steps)."""
    
    # Error handling
    error_message: Optional[str] = None
    """Error message if the step failed."""
    
    error_traceback: Optional[str] = None
    """Full traceback if the step failed."""
    
    # User input (for human-in-the-loop)
    awaiting_input_since: Optional[datetime] = None
    """When the step started waiting for user input."""
    
    user_input: Optional[dict[str, Any]] = None
    """Input received from the user."""
    
    # Revert tracking
    reverted_at: Optional[datetime] = None
    """When this step was reverted (if applicable)."""
    
    revert_error: Optional[str] = None
    """Error message if revert failed."""
    
    class Config:
        """Pydantic configuration."""
        use_enum_values = True
    
    def start(self) -> None:
        """Mark the step as started."""
        self.status = StepStatus.RUNNING
        self.started_at = datetime.utcnow()
    
    def complete(self, output: Optional[dict[str, Any]] = None) -> None:
        """Mark the step as successfully completed."""
        self.status = StepStatus.COMPLETED
        self.completed_at = datetime.utcnow()
        if output:
            self.output_data = output
    
    def fail(self, error: str, traceback: Optional[str] = None) -> None:
        """Mark the step as failed."""
        self.status = StepStatus.FAILED
        self.completed_at = datetime.utcnow()
        self.error_message = error
        self.error_traceback = traceback
    
    def skip(self, reason: Optional[str] = None) -> None:
        """Mark the step as skipped."""
        self.status = StepStatus.SKIPPED
        self.completed_at = datetime.utcnow()
        if reason:
            self.output_data["skip_reason"] = reason
    
    def await_input(self) -> None:
        """Mark the step as waiting for user input."""
        self.status = StepStatus.AWAITING_INPUT
        self.awaiting_input_since = datetime.utcnow()
    
    def provide_input(self, user_input: dict[str, Any]) -> None:
        """Record user input and resume processing."""
        self.user_input = user_input
        self.status = StepStatus.RUNNING
    
    def mark_reverted(self) -> None:
        """Mark this step as reverted."""
        self.status = StepStatus.REVERTED
        self.reverted_at = datetime.utcnow()
    
    def add_artifact(self, artifact: Artifact) -> None:
        """Add an artifact to this step's list."""
        self.artifacts.append(artifact)
    
    @property
    def duration_seconds(self) -> Optional[float]:
        """Calculate how long this step took to execute."""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None
    
    @property
    def is_terminal(self) -> bool:
        """Check if this step is in a terminal state."""
        return self.status in (
            StepStatus.COMPLETED,
            StepStatus.FAILED,
            StepStatus.SKIPPED,
            StepStatus.REVERTED,
        )
    
    @property
    def can_revert(self) -> bool:
        """Check if this step can be reverted."""
        return self.status == StepStatus.COMPLETED and all(
            a.can_revert for a in self.artifacts
        )

