"""Example processor demonstrating the plugin system."""

from core.plugins.base import Processor
from core.models import Job, StepResult, StepStatus
from core.engine.context import ExecutionContext


class ExampleProcessor(Processor):
    """
    An example processor that demonstrates the plugin system.
    
    This processor simply logs a greeting and optionally creates a file.
    Use it as a template for creating your own processors.
    """
    
    # Metadata (can be overridden by manifest.yaml)
    name = "example"
    display_name = "Example Processor"
    description = "An example processor that demonstrates the plugin system"
    
    # No dependencies
    requires = []
    
    # Configuration
    config_schema = {
        "greeting": {
            "type": "string",
            "default": "Hello",
            "description": "Greeting to use when processing",
        },
        "uppercase": {
            "type": "boolean",
            "default": False,
            "description": "Whether to uppercase the output",
        },
    }
    default_config = {
        "greeting": "Hello",
        "uppercase": False,
    }
    
    async def should_process(self, job: Job) -> bool:
        """
        Determine if this processor should handle the job.
        
        This example processor handles all jobs with source_type "example"
        or jobs that have "run_example" in their data.
        """
        if job.source_type == "example":
            return True
        
        if job.get_data("run_example"):
            return True
        
        return False
    
    async def process(self, job: Job, ctx: ExecutionContext) -> StepResult:
        """
        Execute the processing.
        
        This example processor:
        1. Gets the greeting from config
        2. Creates a greeting message
        3. Optionally creates a file
        4. Stores the result in job data
        """
        result = StepResult(job_id=job.id, step_name=self.name)
        result.start()
        
        try:
            # Get configuration
            greeting = self.get_config("greeting", "Hello")
            uppercase = self.get_config("uppercase", False)
            
            # Create greeting message
            message = f"{greeting}, {job.source_name}!"
            if uppercase:
                message = message.upper()
            
            # Optionally create a file
            output_path = job.get_data("output_path")
            if output_path:
                await ctx.create_file(output_path, message)
            
            # Store result in output data
            result.complete({
                "message": message,
                "output_path": output_path,
            })
            
        except Exception as e:
            result.fail(str(e))
        
        return result
    
    async def revert(
        self,
        job: Job,
        step_result: StepResult,
        ctx: ExecutionContext,
    ) -> bool:
        """
        Undo what process() did.
        
        File artifacts are automatically reverted by the ExecutionContext.
        This method is for any custom cleanup needed.
        """
        # No custom cleanup needed for this example
        # File creation is automatically reverted
        return True
    
    async def on_load(self) -> None:
        """Called when the processor is loaded."""
        print(f"Example processor loaded with config: {self._config}")
    
    async def on_unload(self) -> None:
        """Called when the processor is unloaded."""
        print("Example processor unloaded")

