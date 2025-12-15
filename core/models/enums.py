"""Enumerations for NoteFlow v2."""

from enum import Enum


class JobStatus(str, Enum):
    """Status of a job in the pipeline."""
    
    PENDING = "pending"
    """Job is waiting to be processed."""
    
    PROCESSING = "processing"
    """Job is currently being processed by a step."""
    
    AWAITING_INPUT = "awaiting_input"
    """Job is paused waiting for user input via UI."""
    
    COMPLETED = "completed"
    """Job has finished all steps successfully."""
    
    FAILED = "failed"
    """Job encountered an error and stopped."""
    
    CANCELLED = "cancelled"
    """Job was cancelled by the user."""
    
    REVERTING = "reverting"
    """Job is in the process of being reverted."""
    
    REVERTED = "reverted"
    """Job has been reverted to a previous state."""


class StepStatus(str, Enum):
    """Status of a processing step."""
    
    PENDING = "pending"
    """Step has not started."""
    
    RUNNING = "running"
    """Step is currently executing."""
    
    AWAITING_INPUT = "awaiting_input"
    """Step is waiting for user input."""
    
    COMPLETED = "completed"
    """Step finished successfully."""
    
    FAILED = "failed"
    """Step encountered an error."""
    
    SKIPPED = "skipped"
    """Step was skipped (condition not met)."""
    
    REVERTED = "reverted"
    """Step was reverted."""


class ArtifactType(str, Enum):
    """Type of artifact created by a processor."""
    
    FILE_CREATE = "file_create"
    """A new file was created."""
    
    FILE_MODIFY = "file_modify"
    """An existing file was modified."""
    
    FILE_DELETE = "file_delete"
    """A file was deleted (stores the original content)."""
    
    FILE_MOVE = "file_move"
    """A file was moved/renamed."""
    
    FRONTMATTER_UPDATE = "frontmatter_update"
    """Frontmatter in a markdown file was updated."""
    
    EXTERNAL_API_CREATE = "external_api_create"
    """Something was created via an external API (Notion, etc.)."""
    
    EXTERNAL_API_MODIFY = "external_api_modify"
    """Something was modified via an external API."""
    
    METADATA = "metadata"
    """Internal metadata change (no external effect)."""


class ArtifactStatus(str, Enum):
    """Status of an artifact."""
    
    PENDING = "pending"
    """Artifact creation is in progress."""
    
    CREATED = "created"
    """Artifact was successfully created."""
    
    REVERTED = "reverted"
    """Artifact was reverted (undone)."""
    
    FAILED = "failed"
    """Artifact creation failed."""
    
    ORPHANED = "orphaned"
    """Artifact exists but its job was deleted."""
    
    IRREVERSIBLE = "irreversible"
    """Artifact cannot be reverted (e.g., external API call)."""


class ReversibilityLevel(str, Enum):
    """How reversible an artifact is."""
    
    FULLY_REVERSIBLE = "fully_reversible"
    """Can be completely undone (file creation, frontmatter change)."""
    
    PARTIALLY_REVERSIBLE = "partially_reversible"
    """Can be partially undone (API call that created something we can delete)."""
    
    IRREVERSIBLE = "irreversible"
    """Cannot be undone (sent email, posted to social media)."""
    
    MANUAL_REVERT = "manual_revert"
    """Requires manual intervention to revert."""

