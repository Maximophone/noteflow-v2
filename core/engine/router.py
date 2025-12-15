"""Router - determines which processor should handle a job next."""

from typing import Optional
import logging

from ..models import Job, JobStatus
from ..plugins import ProcessorRegistry

logger = logging.getLogger(__name__)


class Router:
    """
    Determines which processor should handle a job next.
    
    The router considers:
    - Which steps have already been completed
    - Processor dependencies
    - Which processors are applicable to this job
    """
    
    def __init__(self, registry: ProcessorRegistry):
        self.registry = registry
    
    async def get_next_step(self, job: Job) -> Optional[str]:
        """
        Determine the next processing step for a job.
        
        Args:
            job: The job to route
        
        Returns:
            Name of the next processor, or None if processing is complete
        """
        completed_steps = set(job.get_completed_steps())
        
        # Get all applicable processors in dependency order
        applicable = await self._get_applicable_processors(job)
        
        if not applicable:
            logger.debug(f"No applicable processors for job {job.id}")
            return None
        
        # Get execution order
        try:
            ordered = self.registry.get_execution_order(applicable)
        except ValueError as e:
            logger.error(f"Dependency error for job {job.id}: {e}")
            return None
        
        # Find the first step that hasn't been completed
        for step_name in ordered:
            if step_name not in completed_steps:
                # Check if dependencies are satisfied
                processor = self.registry.get(step_name)
                if processor:
                    deps_satisfied = all(
                        dep in completed_steps
                        for dep in processor.requires
                    )
                    if deps_satisfied:
                        logger.debug(f"Next step for job {job.id}: {step_name}")
                        return step_name
        
        logger.debug(f"All steps completed for job {job.id}")
        return None
    
    async def _get_applicable_processors(self, job: Job) -> list[str]:
        """
        Get all processors that could apply to this job.
        
        Args:
            job: The job to check
        
        Returns:
            List of applicable processor names
        """
        applicable = []
        
        for processor in self.registry:
            try:
                if await processor.should_process(job):
                    applicable.append(processor.name)
            except Exception as e:
                logger.error(
                    f"Error checking should_process for {processor.name}: {e}"
                )
        
        return applicable
    
    async def get_all_applicable_steps(self, job: Job) -> list[str]:
        """
        Get all steps that could apply to this job (in order).
        
        Args:
            job: The job to check
        
        Returns:
            Ordered list of all applicable processor names
        """
        applicable = await self._get_applicable_processors(job)
        
        if not applicable:
            return []
        
        try:
            return self.registry.get_execution_order(applicable)
        except ValueError as e:
            logger.error(f"Dependency error for job {job.id}: {e}")
            return []
    
    async def get_pending_steps(self, job: Job) -> list[str]:
        """
        Get all steps that still need to be executed.
        
        Args:
            job: The job to check
        
        Returns:
            List of pending step names
        """
        all_steps = await self.get_all_applicable_steps(job)
        completed = set(job.get_completed_steps())
        
        return [step for step in all_steps if step not in completed]
    
    def get_revertable_steps(self, job: Job) -> list[str]:
        """
        Get all steps that can be reverted for a job.
        
        Args:
            job: The job to check
        
        Returns:
            List of step names that can be reverted (in order)
        """
        return [r.step_name for r in job.history if r.can_revert]
    
    def can_run_step(self, job: Job, step_name: str) -> tuple[bool, str]:
        """
        Check if a specific step can run for a job.
        
        Args:
            job: The job to check
            step_name: Name of the step
        
        Returns:
            Tuple of (can_run, reason)
        """
        processor = self.registry.get(step_name)
        if not processor:
            return False, f"Processor '{step_name}' not found"
        
        # Check if already completed
        if job.has_completed_step(step_name):
            return False, f"Step '{step_name}' already completed"
        
        # Check dependencies
        completed = set(job.get_completed_steps())
        missing_deps = [dep for dep in processor.requires if dep not in completed]
        
        if missing_deps:
            return False, f"Missing dependencies: {missing_deps}"
        
        return True, ""

