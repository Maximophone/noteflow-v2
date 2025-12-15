"""Pipeline - the main orchestrator for job processing."""

import asyncio
from pathlib import Path
from typing import Optional, Callable, Awaitable, Any, List
from datetime import datetime
import logging

from ..models import Job, JobStatus, StepResult
from ..storage import Database, JobStore, ArtifactStore
from ..plugins import ProcessorRegistry, PluginLoader
from ..watchers import FileWatcher, WatchConfig, WatchEvent
from ..watchers.watch_config import FileEvent
from .context import ExecutionContext
from .router import Router
from .executor import JobExecutor

logger = logging.getLogger(__name__)


class Pipeline:
    """
    Main orchestrator for the NoteFlow pipeline.
    
    Manages:
    - Plugin loading
    - Job creation and lifecycle
    - Concurrent job execution
    - Event callbacks for UI integration
    
    Usage:
        pipeline = Pipeline(db_path="noteflow.db", plugins_dir="plugins")
        await pipeline.start()
        
        job = await pipeline.create_job(source_type="file", source_path="/path/to/audio.mp3")
        await pipeline.process_job(job.id)
        
        await pipeline.stop()
    """
    
    def __init__(
        self,
        db_path: Path | str = "noteflow.db",
        plugins_dir: Path | str = "plugins",
        max_concurrent_jobs: int = 3,
    ):
        self.db_path = Path(db_path)
        self.plugins_dir = Path(plugins_dir)
        self.max_concurrent_jobs = max_concurrent_jobs
        
        # Core components
        self.database = Database(db_path)
        self.job_store: Optional[JobStore] = None
        self.artifact_store: Optional[ArtifactStore] = None
        self.registry = ProcessorRegistry()
        self.loader: Optional[PluginLoader] = None
        self.router: Optional[Router] = None
        self.executor: Optional[JobExecutor] = None
        
        # File watching
        self.file_watcher = FileWatcher()
        self.file_watcher.on_file_event = self._handle_file_event
        
        # State
        self._running = False
        self._worker_task: Optional[asyncio.Task] = None
        self._active_jobs: set[str] = set()
        self._lock = asyncio.Lock()
        
        # Callbacks
        self._callbacks: dict[str, list[Callable]] = {
            "job_created": [],
            "job_started": [],
            "job_completed": [],
            "job_failed": [],
            "step_completed": [],
            "step_awaiting_input": [],
            "file_detected": [],
        }
    
    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------
    
    async def start(self) -> None:
        """Start the pipeline."""
        if self._running:
            logger.warning("Pipeline already running")
            return
        
        logger.info("Starting pipeline...")
        
        # Initialize database
        await self.database.connect()
        
        # Initialize stores
        self.job_store = JobStore(self.database)
        self.artifact_store = ArtifactStore(self.database)
        
        # Initialize plugin system
        self.loader = PluginLoader(self.plugins_dir, self.registry)
        await self.loader.load_all()
        
        # Initialize router and executor
        self.router = Router(self.registry)
        self.executor = JobExecutor(
            self.database,
            self.job_store,
            self.artifact_store,
            self.registry,
            self.router,
        )
        
        # Register executor callbacks
        self.executor.on_step_complete(self._handle_step_complete)
        self.executor.on_awaiting_input(self._handle_awaiting_input)
        
        self._running = True
        
        logger.info("Pipeline started")
    
    async def stop(self) -> None:
        """Stop the pipeline."""
        if not self._running:
            return
        
        logger.info("Stopping pipeline...")
        
        self._running = False
        
        # Stop file watcher
        await self.file_watcher.stop()
        
        # Cancel worker if running
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        
        # Unload plugins
        if self.loader:
            for name in list(self.registry.get_names()):
                await self.loader.unload_plugin(name)
        
        # Close database
        await self.database.close()
        
        logger.info("Pipeline stopped")
    
    async def start_background_worker(self) -> None:
        """Start the background worker that processes pending jobs."""
        if self._worker_task and not self._worker_task.done():
            logger.warning("Background worker already running")
            return
        
        self._worker_task = asyncio.create_task(self._worker_loop())
        logger.info("Background worker started")
    
    async def stop_background_worker(self) -> None:
        """Stop the background worker."""
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None
            logger.info("Background worker stopped")
    
    async def _worker_loop(self) -> None:
        """Background worker that processes pending jobs."""
        while self._running:
            try:
                await self._process_pending_jobs()
                await asyncio.sleep(1)  # Poll interval
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in worker loop: {e}")
                await asyncio.sleep(5)  # Back off on error
    
    async def _process_pending_jobs(self) -> None:
        """Process all pending jobs up to the concurrency limit."""
        if len(self._active_jobs) >= self.max_concurrent_jobs:
            return
        
        # Get pending jobs
        pending = await self.job_store.list_pending(
            limit=self.max_concurrent_jobs - len(self._active_jobs)
        )
        
        for job in pending:
            if job.id not in self._active_jobs:
                asyncio.create_task(self._process_job_async(job))
    
    async def _process_job_async(self, job: Job) -> None:
        """Process a single job (runs in background)."""
        async with self._lock:
            self._active_jobs.add(job.id)
        
        try:
            await self._emit("job_started", job)
            
            # Keep processing steps until done or paused
            while job.status == JobStatus.PENDING or job.status == JobStatus.PROCESSING:
                result = await self.executor.execute_next_step(job)
                
                if result is None:
                    # No more steps - job is complete
                    break
                
                if result.status == "awaiting_input":
                    # Job is waiting for user input
                    break
                
                if result.status == "failed":
                    # Job failed
                    break
            
            # Emit appropriate event
            if job.status == JobStatus.COMPLETED:
                await self._emit("job_completed", job)
            elif job.status == JobStatus.FAILED:
                await self._emit("job_failed", job)
            
        finally:
            async with self._lock:
                self._active_jobs.discard(job.id)
    
    # -------------------------------------------------------------------------
    # Job Management
    # -------------------------------------------------------------------------
    
    async def create_job(
        self,
        source_type: str,
        source_name: str,
        source_path: Optional[str] = None,
        source_url: Optional[str] = None,
        data: Optional[dict] = None,
        config: Optional[dict] = None,
        tags: Optional[list[str]] = None,
        priority: int = 0,
    ) -> Job:
        """
        Create a new job.
        
        Args:
            source_type: Type of source ("file", "url", "api", "manual")
            source_name: Human-readable name for display
            source_path: Path to source file (if applicable)
            source_url: Source URL (if applicable)
            data: Initial job data
            config: Job-specific configuration
            tags: Tags for organization
            priority: Processing priority (higher = first)
        
        Returns:
            The created job
        """
        job = Job(
            source_type=source_type,
            source_name=source_name,
            source_path=source_path,
            source_url=source_url,
            data=data or {},
            config=config or {},
            tags=tags or [],
            priority=priority,
        )
        
        await self.job_store.save(job)
        await self._emit("job_created", job)
        
        logger.info(f"Created job {job.id}: {source_name}")
        return job
    
    async def get_job(self, job_id: str) -> Optional[Job]:
        """Get a job by ID."""
        return await self.job_store.get(job_id)
    
    async def list_jobs(
        self,
        status: Optional[JobStatus] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Job]:
        """List jobs with optional filtering."""
        return await self.job_store.list_all(
            status=status,
            limit=limit,
            offset=offset,
        )
    
    async def delete_job(self, job_id: str, revert_first: bool = True) -> bool:
        """
        Delete a job.
        
        Args:
            job_id: ID of the job to delete
            revert_first: Whether to revert artifacts before deleting
        
        Returns:
            True if deleted successfully
        """
        job = await self.job_store.get(job_id)
        if not job:
            return False
        
        if revert_first:
            await self.executor.revert_all(job)
        
        await self.artifact_store.delete_by_job(job_id)
        await self.job_store.delete(job_id)
        
        logger.info(f"Deleted job {job_id}")
        return True
    
    async def process_job(self, job_id: str) -> Job:
        """
        Process a job immediately (blocking).
        
        Args:
            job_id: ID of the job to process
        
        Returns:
            The processed job
        """
        job = await self.job_store.get(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")
        
        await self._process_job_async(job)
        
        # Reload to get latest state
        return await self.job_store.get(job_id)
    
    async def resume_job(self, job_id: str, user_input: dict) -> Job:
        """
        Resume a job that's waiting for user input.
        
        Args:
            job_id: ID of the job to resume
            user_input: User input data
        
        Returns:
            The job
        """
        job = await self.job_store.get(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")
        
        if job.status != JobStatus.AWAITING_INPUT:
            raise ValueError(f"Job {job_id} is not awaiting input")
        
        if not job.current_step:
            raise ValueError(f"Job {job_id} has no current step")
        
        await self.executor.resume_step(job, job.current_step, user_input)
        
        # Continue processing
        await self._process_job_async(job)
        
        return await self.job_store.get(job_id)
    
    async def cancel_job(self, job_id: str) -> Job:
        """Cancel a job."""
        job = await self.job_store.get(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")
        
        job.cancel()
        await self.job_store.save(job)
        
        logger.info(f"Cancelled job {job_id}")
        return job
    
    async def revert_job(self, job_id: str, to_step: Optional[str] = None) -> Job:
        """
        Revert a job to a previous state.
        
        Args:
            job_id: ID of the job to revert
            to_step: Step to revert to (if None, reverts all)
        
        Returns:
            The reverted job
        """
        job = await self.job_store.get(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")
        
        if to_step:
            await self.executor.revert_to_step(job, to_step)
        else:
            await self.executor.revert_all(job)
        
        return await self.job_store.get(job_id)
    
    # -------------------------------------------------------------------------
    # Plugin Management
    # -------------------------------------------------------------------------
    
    def get_processors(self) -> list[dict]:
        """Get information about all loaded processors."""
        return [
            {
                "name": p.name,
                "display_name": p.display_name,
                "description": p.description,
                "version": p.version,
                "requires": p.requires,
                "has_ui": p.has_ui,
                "requires_input": p.requires_input,
            }
            for p in self.registry
        ]
    
    async def reload_plugin(self, name: str) -> bool:
        """Reload a specific plugin."""
        processor = await self.loader.reload_plugin(name)
        return processor is not None
    
    # -------------------------------------------------------------------------
    # Callbacks
    # -------------------------------------------------------------------------
    
    def on(self, event: str, callback: Callable[..., Awaitable[None]]) -> None:
        """Register an event callback."""
        if event in self._callbacks:
            self._callbacks[event].append(callback)
    
    def off(self, event: str, callback: Callable) -> None:
        """Unregister an event callback."""
        if event in self._callbacks and callback in self._callbacks[event]:
            self._callbacks[event].remove(callback)
    
    async def _emit(self, event: str, *args) -> None:
        """Emit an event to all registered callbacks."""
        for callback in self._callbacks.get(event, []):
            try:
                await callback(*args)
            except Exception as e:
                logger.error(f"Error in callback for event '{event}': {e}")
    
    async def _handle_step_complete(self, job: Job, result: StepResult) -> None:
        """Handle step completion callback from executor."""
        await self._emit("step_completed", job, result)
    
    async def _handle_awaiting_input(self, job: Job, step_name: str) -> None:
        """Handle awaiting input callback from executor."""
        await self._emit("step_awaiting_input", job, step_name)
    
    # -------------------------------------------------------------------------
    # File Watching
    # -------------------------------------------------------------------------
    
    def add_watch(self, config: WatchConfig) -> None:
        """
        Add a directory watch configuration.
        
        Args:
            config: Watch configuration specifying directory, patterns, etc.
        """
        self.file_watcher.add_watch(config)
    
    def remove_watch(self, name: str) -> bool:
        """Remove a watch by name."""
        return self.file_watcher.remove_watch(name)
    
    def get_watch(self, name: str) -> Optional[WatchConfig]:
        """Get a watch configuration by name."""
        return self.file_watcher.get_watch(name)
    
    def list_watches(self) -> List[WatchConfig]:
        """List all watch configurations."""
        return list(self.file_watcher.watches.values())
    
    async def start_watching(self) -> None:
        """Start watching all configured directories."""
        await self.file_watcher.start()
        logger.info(f"Started file watching with {len(self.file_watcher.watches)} watches")
    
    async def stop_watching(self) -> None:
        """Stop watching directories."""
        await self.file_watcher.stop()
        logger.info("Stopped file watching")
    
    async def scan_existing_files(self, watch_name: Optional[str] = None) -> List[Job]:
        """
        Scan existing files and create jobs for them.
        
        This is useful for processing files that existed before the watcher started.
        
        Args:
            watch_name: Optional specific watch to scan. If None, scans all watches.
            
        Returns:
            List of created jobs.
        """
        events = await self.file_watcher.scan_existing(watch_name)
        jobs = []
        
        for event in events:
            job = await self._create_job_from_file_event(event)
            if job:
                jobs.append(job)
        
        logger.info(f"Scanned existing files: created {len(jobs)} jobs")
        return jobs
    
    async def _handle_file_event(self, event: FileEvent) -> None:
        """Handle a file event from the watcher."""
        logger.debug(f"File event received: {event.event_type.value} {event.path}")
        
        # Emit event for UI
        await self._emit("file_detected", event)
        
        # Only create jobs for create/modify events
        if event.event_type in (WatchEvent.CREATED, WatchEvent.MODIFIED):
            await self._create_job_from_file_event(event)
    
    async def _create_job_from_file_event(self, event: FileEvent) -> Optional[Job]:
        """Create a job from a file event."""
        config = event.watch_config
        
        # Check if job already exists for this file
        existing_jobs = await self.job_store.list_all(limit=1000)
        for job in existing_jobs:
            if job.source_path == str(event.path):
                # For modified events, we might want to re-process
                if event.event_type == WatchEvent.MODIFIED and job.status == JobStatus.COMPLETED:
                    logger.info(f"File modified, resetting completed job: {event.path}")
                    # Optionally revert and restart - for now just log
                    pass
                else:
                    logger.info(f"Job already exists for file (job_id={job.id}, status={job.status}): {event.path}")
                    return None
        
        # Build job data
        data = {
            "original_filename": event.filename,
            "watch_name": config.name,
            **config.metadata,
        }
        
        # Add frontmatter for markdown files
        if event.path.suffix == ".md":
            try:
                content = event.path.read_text(encoding="utf-8")
                data["initial_content"] = content
            except Exception as e:
                logger.warning(f"Failed to read markdown file {event.path}: {e}")
        
        # Create the job
        job = await self.create_job(
            source_type=config.source_type,
            source_name=event.filename,
            source_path=str(event.path),
            data=data,
            tags=config.tags.copy(),
            priority=config.priority,
        )
        
        # If initial processor specified, set it
        if config.initial_processor:
            job.current_step = config.initial_processor
            await self.job_store.save(job)
        
        logger.info(f"Created job from file event: {job.id} ({event.filename})")
        return job
    
    # -------------------------------------------------------------------------
    # Statistics
    # -------------------------------------------------------------------------
    
    async def get_stats(self) -> dict:
        """Get pipeline statistics."""
        counts = await self.job_store.count_by_status()
        
        return {
            "running": self._running,
            "active_jobs": len(self._active_jobs),
            "max_concurrent": self.max_concurrent_jobs,
            "processors_loaded": len(self.registry),
            "jobs_by_status": counts,
            "watches": len(self.file_watcher.watches),
            "watching": self.file_watcher.is_running,
        }

