"""Job executor - executes processing steps for jobs."""

import asyncio
import traceback
from typing import Optional, Callable, Awaitable
import logging

from ..models import Job, JobStatus, StepResult, StepStatus
from ..storage import Database, JobStore, ArtifactStore
from ..plugins import ProcessorRegistry
from .context import ExecutionContext
from .router import Router

logger = logging.getLogger(__name__)


class JobExecutor:
    """
    Executes processing steps for jobs.
    
    Handles:
    - Step execution with artifact tracking
    - Error handling and auto-rollback
    - Human-in-the-loop pausing
    - Reverting steps
    """
    
    def __init__(
        self,
        database: Database,
        job_store: JobStore,
        artifact_store: ArtifactStore,
        registry: ProcessorRegistry,
        router: Router,
    ):
        self.db = database
        self.job_store = job_store
        self.artifact_store = artifact_store
        self.registry = registry
        self.router = router
        
        # Callbacks for UI integration
        self._on_step_complete: Optional[Callable[[Job, StepResult], Awaitable[None]]] = None
        self._on_awaiting_input: Optional[Callable[[Job, str], Awaitable[None]]] = None
    
    def on_step_complete(
        self,
        callback: Callable[[Job, StepResult], Awaitable[None]],
    ) -> None:
        """Register callback for when a step completes."""
        self._on_step_complete = callback
    
    def on_awaiting_input(
        self,
        callback: Callable[[Job, str], Awaitable[None]],
    ) -> None:
        """Register callback for when a step awaits user input."""
        self._on_awaiting_input = callback
    
    async def execute_next_step(self, job: Job) -> Optional[StepResult]:
        """
        Execute the next pending step for a job.
        
        Args:
            job: The job to process
        
        Returns:
            StepResult if a step was executed, None if no steps pending
        """
        # Get next step from router
        step_name = await self.router.get_next_step(job)
        
        if not step_name:
            # No more steps - mark job complete
            job.complete()
            await self.job_store.save(job)
            logger.info(f"Job {job.id} completed - no more steps")
            return None
        
        return await self.execute_step(job, step_name)
    
    async def execute_step(self, job: Job, step_name: str) -> StepResult:
        """
        Execute a specific step for a job.
        
        Args:
            job: The job to process
            step_name: Name of the step to execute
        
        Returns:
            The step result
        """
        processor = self.registry.get(step_name)
        if not processor:
            raise ValueError(f"Processor '{step_name}' not found")
        
        # Check if we can run this step
        can_run, reason = self.router.can_run_step(job, step_name)
        if not can_run:
            result = StepResult(job_id=job.id, step_name=step_name)
            result.skip(reason)
            return result
        
        # Create step result
        result = StepResult(job_id=job.id, step_name=step_name)
        result.start()
        
        # Update job status
        job.start_processing(step_name)
        await self.job_store.save(job)
        
        # Check if user input is needed
        if processor.requires_input == "always" or (
            processor.requires_input == "conditional"
            and processor.requires_user_input(job)
        ):
            result.await_input()
            job.await_input(step_name)
            job.add_step_result(result)
            await self.job_store.save(job)
            
            if self._on_awaiting_input:
                await self._on_awaiting_input(job, step_name)
            
            logger.info(f"Job {job.id} awaiting input for step {step_name}")
            return result
        
        # Execute the processor
        return await self._do_execute(job, processor, result)
    
    async def resume_step(
        self,
        job: Job,
        step_name: str,
        user_input: dict,
    ) -> StepResult:
        """
        Resume a step that was waiting for user input.
        
        Args:
            job: The job to resume
            step_name: Name of the step to resume
            user_input: Input provided by the user
        
        Returns:
            The step result
        """
        processor = self.registry.get(step_name)
        if not processor:
            raise ValueError(f"Processor '{step_name}' not found")
        
        # Find the pending step result
        result = job.get_step_result(step_name)
        if not result or result.status != StepStatus.AWAITING_INPUT:
            raise ValueError(f"Step '{step_name}' is not awaiting input")
        
        # Validate input
        is_valid, error = await processor.validate_input(job, user_input)
        if not is_valid:
            raise ValueError(f"Invalid input: {error}")
        
        # Record user input and resume
        result.provide_input(user_input)
        job.set_data("user_input", user_input)
        
        return await self._do_execute(job, processor, result)
    
    async def _do_execute(
        self,
        job: Job,
        processor,
        result: StepResult,
    ) -> StepResult:
        """Actually execute the processor."""
        ctx = ExecutionContext(job, processor.name, self.artifact_store)
        
        try:
            async with ctx:
                # Run the processor
                step_result = await processor.process(job, ctx)
                
                # Merge the returned result with our tracking result
                result.status = step_result.status
                result.output_data = step_result.output_data
                result.error_message = step_result.error_message
                result.artifacts = ctx.artifacts
            
            # Commit artifacts
            for artifact in result.artifacts:
                await self.artifact_store.save(artifact)
            
            if result.status == StepStatus.COMPLETED:
                result.complete(result.output_data)
                
                # Merge output data into job
                job.merge_data(result.output_data)
            
            elif result.status == StepStatus.AWAITING_INPUT:
                job.await_input(processor.name)
                
                if self._on_awaiting_input:
                    await self._on_awaiting_input(job, processor.name)
            
        except Exception as e:
            logger.error(
                f"Error executing step {processor.name} for job {job.id}: {e}\n"
                f"{traceback.format_exc()}"
            )
            result.fail(str(e), traceback.format_exc())
            
            # Auto-rollback if configured
            if processor.auto_revert_on_error:
                await ctx.rollback()
            
            job.fail(str(e))
        
        # Update job history and save
        job.add_step_result(result)
        await self.job_store.save(job)
        
        # Notify callback
        if self._on_step_complete:
            await self._on_step_complete(job, result)
        
        logger.info(
            f"Step {processor.name} for job {job.id} finished with status {result.status}"
        )
        
        return result
    
    async def revert_step(self, job: Job, step_name: str) -> bool:
        """
        Revert a specific step for a job.
        
        Args:
            job: The job to revert
            step_name: Name of the step to revert
        
        Returns:
            True if revert was successful
        """
        processor = self.registry.get(step_name)
        if not processor:
            logger.error(f"Processor '{step_name}' not found for revert")
            return False
        
        # Find the step result
        result = job.get_step_result(step_name)
        if not result:
            logger.error(f"No result found for step '{step_name}'")
            return False
        
        if not result.can_revert:
            logger.error(f"Step '{step_name}' cannot be reverted")
            return False
        
        logger.info(f"Reverting step {step_name} for job {job.id}")
        
        # Revert artifacts in reverse order
        for artifact in reversed(result.artifacts):
            if artifact.can_revert:
                try:
                    ctx = ExecutionContext(job, step_name, self.artifact_store)
                    await ctx._revert_artifact(artifact)
                    await self.artifact_store.mark_reverted(artifact.id)
                except Exception as e:
                    logger.error(f"Error reverting artifact {artifact.id}: {e}")
                    result.revert_error = str(e)
        
        # Call processor's custom revert logic
        try:
            ctx = ExecutionContext(job, step_name, self.artifact_store)
            await processor.revert(job, result, ctx)
        except Exception as e:
            logger.error(f"Error in processor revert for {step_name}: {e}")
            result.revert_error = str(e)
        
        # Mark step as reverted
        result.mark_reverted()
        await self.job_store.save(job)
        
        logger.info(f"Successfully reverted step {step_name} for job {job.id}")
        return True
    
    async def revert_to_step(self, job: Job, target_step: str) -> bool:
        """
        Revert a job to a previous step, undoing all subsequent work.
        
        Args:
            job: The job to revert
            target_step: The step to revert to (this step will NOT be reverted)
        
        Returns:
            True if revert was successful
        """
        # Find all steps after the target
        target_found = False
        steps_to_revert = []
        
        for result in job.history:
            if target_found and result.can_revert:
                steps_to_revert.append(result.step_name)
            if result.step_name == target_step:
                target_found = True
        
        if not target_found:
            logger.error(f"Target step '{target_step}' not found in job history")
            return False
        
        job.start_revert()
        await self.job_store.save(job)
        
        # Revert in reverse order
        for step_name in reversed(steps_to_revert):
            success = await self.revert_step(job, step_name)
            if not success:
                logger.error(f"Failed to revert step {step_name}")
                job.fail(f"Revert failed at step {step_name}")
                await self.job_store.save(job)
                return False
        
        # Update job status to re-run from target step
        job.complete_revert(target_step)
        job.status = JobStatus.PENDING
        job.current_step = None
        await self.job_store.save(job)
        
        logger.info(f"Successfully reverted job {job.id} to step {target_step}")
        return True
    
    async def revert_all(self, job: Job) -> bool:
        """
        Revert all steps for a job.
        
        Args:
            job: The job to revert
        
        Returns:
            True if revert was successful
        """
        job.start_revert()
        await self.job_store.save(job)
        
        # Get all reversible steps in reverse order
        reversible = [r for r in reversed(job.history) if r.can_revert]
        
        for result in reversible:
            success = await self.revert_step(job, result.step_name)
            if not success:
                logger.error(f"Failed to revert step {result.step_name}")
        
        job.complete_revert()
        await self.job_store.save(job)
        
        logger.info(f"Reverted all steps for job {job.id}")
        return True

