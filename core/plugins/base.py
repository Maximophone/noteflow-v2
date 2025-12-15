"""Base Processor class - the plugin interface."""

from abc import ABC, abstractmethod
from typing import Optional, Any
from pathlib import Path
import logging

from ..models import Job, StepResult, StepDefinition
from ..engine.context import ExecutionContext

logger = logging.getLogger(__name__)


class Processor(ABC):
    """
    Base class for all pipeline processors.
    
    A processor is a plugin that performs a specific task in the pipeline.
    Processors are discovered and loaded at runtime from the plugins directory.
    
    Each processor must implement:
    - should_process(): Determine if this processor should handle a job
    - process(): Execute the processing
    - revert(): Undo what process() did
    
    Optionally, processors can:
    - Provide a UI component for human-in-the-loop workflows
    - Define configuration options
    - Specify dependencies on other processors
    
    Example:
        class TranscriptionProcessor(Processor):
            name = "transcribe"
            display_name = "Audio Transcription"
            description = "Transcribes audio files using AssemblyAI"
            requires = []  # No dependencies
            
            async def should_process(self, job: Job) -> bool:
                return job.source_type == "file" and job.get_data("file_type") == "audio"
            
            async def process(self, job: Job, ctx: ExecutionContext) -> StepResult:
                # Transcription logic...
                await ctx.create_file(output_path, transcript)
                return StepResult(step_name=self.name, status="completed")
            
            async def revert(self, job: Job, step_result: StepResult, ctx: ExecutionContext) -> bool:
                # Artifacts are auto-reverted, but we can do custom cleanup
                return True
    """
    
    # -------------------------------------------------------------------------
    # Metadata (must be defined by subclasses)
    # -------------------------------------------------------------------------
    
    name: str = ""
    """Unique identifier for this processor. Used in dependencies and routing."""
    
    display_name: str = ""
    """Human-readable name for UI display."""
    
    description: str = ""
    """Description of what this processor does."""
    
    version: str = "1.0.0"
    """Version of this processor."""
    
    # -------------------------------------------------------------------------
    # Dependencies
    # -------------------------------------------------------------------------
    
    requires: list[str] = []
    """
    List of processor names that must complete before this one.
    
    The pipeline router will ensure dependencies are satisfied before
    scheduling this processor.
    """
    
    # -------------------------------------------------------------------------
    # Configuration
    # -------------------------------------------------------------------------
    
    config_schema: dict[str, Any] = {}
    """
    JSON Schema for configuration options.
    
    Example:
        config_schema = {
            "ai_model": {
                "type": "string",
                "default": "gemini-pro",
                "description": "AI model to use for processing"
            },
            "max_retries": {
                "type": "integer",
                "default": 3,
                "minimum": 1
            }
        }
    """
    
    default_config: dict[str, Any] = {}
    """Default values for configuration options."""
    
    # -------------------------------------------------------------------------
    # UI Integration
    # -------------------------------------------------------------------------
    
    has_ui: bool = False
    """Whether this processor has a custom UI component."""
    
    ui_component_path: Optional[str] = None
    """Path to the UI component (relative to plugin directory)."""
    
    requires_input: str = "never"  # "never", "always", "conditional"
    """
    When this processor requires user input:
    - "never": Fully automated
    - "always": Always needs user confirmation
    - "conditional": Only needs input in certain cases (check requires_user_input())
    """
    
    # -------------------------------------------------------------------------
    # Behavior
    # -------------------------------------------------------------------------
    
    can_skip: bool = True
    """Whether this processor can be skipped if conditions aren't met."""
    
    auto_revert_on_error: bool = True
    """Whether to auto-revert artifacts if the processor fails."""
    
    max_concurrent: int = 0
    """Maximum concurrent executions (0 = unlimited)."""
    
    # -------------------------------------------------------------------------
    # Internal state
    # -------------------------------------------------------------------------
    
    _config: dict[str, Any]
    """Runtime configuration (merged from defaults and job config)."""
    
    def __init__(self, config: Optional[dict[str, Any]] = None):
        """
        Initialize the processor with optional configuration.
        
        Args:
            config: Configuration overrides
        """
        self._config = {**self.default_config, **(config or {})}
    
    @property
    def config(self) -> dict[str, Any]:
        """Get the runtime configuration."""
        return self._config
    
    # -------------------------------------------------------------------------
    # Abstract methods (must be implemented by subclasses)
    # -------------------------------------------------------------------------
    
    @abstractmethod
    async def should_process(self, job: Job) -> bool:
        """
        Determine if this processor should handle the given job.
        
        This is called by the router to decide whether to schedule
        this processor for a job.
        
        Args:
            job: The job to check
        
        Returns:
            True if this processor should process the job
        """
        pass
    
    @abstractmethod
    async def process(self, job: Job, ctx: ExecutionContext) -> StepResult:
        """
        Execute the processing.
        
        All side effects (file creation, API calls) should go through the
        ExecutionContext so they can be tracked and reverted if needed.
        
        Args:
            job: The job being processed
            ctx: Execution context for tracking artifacts
        
        Returns:
            StepResult with the outcome of processing
        """
        pass
    
    @abstractmethod
    async def revert(
        self,
        job: Job,
        step_result: StepResult,
        ctx: ExecutionContext,
    ) -> bool:
        """
        Undo what process() did.
        
        Artifacts are automatically reverted, but this method allows
        for custom cleanup (e.g., updating external state).
        
        Args:
            job: The job being reverted
            step_result: The result from the original process() call
            ctx: Execution context
        
        Returns:
            True if revert was successful
        """
        pass
    
    # -------------------------------------------------------------------------
    # Optional methods (can be overridden by subclasses)
    # -------------------------------------------------------------------------
    
    def requires_user_input(self, job: Job) -> bool:
        """
        Check if this job requires user input.
        
        Only called if requires_input == "conditional".
        
        Args:
            job: The job to check
        
        Returns:
            True if user input is required
        """
        return False
    
    def get_ui_component(self) -> Optional[str]:
        """
        Get the path to the UI component for this processor.
        
        Returns:
            Path to React component, or None if no UI
        """
        return self.ui_component_path
    
    def get_input_schema(self, job: Job) -> dict[str, Any]:
        """
        Get JSON Schema for the expected user input.
        
        Used by the UI to render an appropriate input form.
        
        Args:
            job: The job awaiting input
        
        Returns:
            JSON Schema for the input
        """
        return {}
    
    async def validate_input(self, job: Job, user_input: dict[str, Any]) -> tuple[bool, str]:
        """
        Validate user input before resuming processing.
        
        Args:
            job: The job awaiting input
            user_input: Input provided by the user
        
        Returns:
            Tuple of (is_valid, error_message)
        """
        return True, ""
    
    async def on_load(self) -> None:
        """Called when the processor is loaded. Use for initialization."""
        pass
    
    async def on_unload(self) -> None:
        """Called when the processor is unloaded. Use for cleanup."""
        pass
    
    # -------------------------------------------------------------------------
    # Utility methods
    # -------------------------------------------------------------------------
    
    def get_config(self, key: str, default: Any = None) -> Any:
        """Get a configuration value."""
        return self._config.get(key, default)
    
    def to_definition(self) -> StepDefinition:
        """Convert processor metadata to a StepDefinition."""
        return StepDefinition(
            name=self.name,
            display_name=self.display_name,
            description=self.description,
            requires=self.requires,
            config_schema=self.config_schema,
            default_config=self.default_config,
            has_ui=self.has_ui,
            requires_input=self.requires_input,
            can_skip=self.can_skip,
            auto_revert_on_error=self.auto_revert_on_error,
        )
    
    def __repr__(self) -> str:
        return f"<Processor {self.name}>"

