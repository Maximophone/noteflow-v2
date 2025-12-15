"""File system watcher that creates jobs from file events."""

import asyncio
import logging
from pathlib import Path
from typing import Dict, List, Optional, Callable, Awaitable, Set
from datetime import datetime, timedelta
from dataclasses import dataclass, field
import fnmatch

from watchfiles import awatch, Change

from .watch_config import WatchConfig, WatchEvent, FileEvent

logger = logging.getLogger(__name__)


@dataclass
class PendingEvent:
    """An event waiting to be processed (for debouncing)."""
    file_event: FileEvent
    scheduled_time: datetime


class FileWatcher:
    """Watches multiple directories for file changes and creates jobs.
    
    Features:
    - Multiple directory watches with different configurations
    - Pattern matching for file types
    - Debouncing to handle rapid changes
    - Recursive or non-recursive watching
    - Event filtering (create, modify, delete, move)
    
    Usage:
        watcher = FileWatcher()
        
        # Add watches
        watcher.add_watch(WatchConfig(
            path=Path("/path/to/audio"),
            name="Audio Input",
            patterns=["*.mp3", "*.wav"],
            source_type="audio",
            initial_processor="transcribe"
        ))
        
        # Set callback for when files are detected
        watcher.on_file_event = my_callback_function
        
        # Start watching
        await watcher.start()
    """
    
    def __init__(self):
        self._watches: Dict[str, WatchConfig] = {}
        self._pending_events: Dict[str, PendingEvent] = {}  # path -> pending event
        self._running = False
        self._tasks: List[asyncio.Task] = []
        self._debounce_task: Optional[asyncio.Task] = None
        
        # Callback when a file event is ready to process
        self._on_file_event: Optional[Callable[[FileEvent], Awaitable[None]]] = None
        
        # Track what we've seen to detect moves
        self._seen_files: Dict[str, Set[str]] = {}  # watch_name -> set of paths
    
    @property
    def on_file_event(self) -> Optional[Callable[[FileEvent], Awaitable[None]]]:
        return self._on_file_event
    
    @on_file_event.setter
    def on_file_event(self, callback: Callable[[FileEvent], Awaitable[None]]):
        self._on_file_event = callback
    
    @property
    def watches(self) -> Dict[str, WatchConfig]:
        """Get all registered watches."""
        return self._watches.copy()
    
    @property
    def is_running(self) -> bool:
        return self._running
    
    def add_watch(self, config: WatchConfig) -> None:
        """Add a directory watch configuration."""
        if not config.path.exists():
            logger.warning(f"Watch path does not exist, will be created: {config.path}")
            config.path.mkdir(parents=True, exist_ok=True)
        
        self._watches[config.name] = config
        self._seen_files[config.name] = set()
        logger.info(f"Added watch: {config.name} -> {config.path} (patterns: {config.patterns})")
    
    def remove_watch(self, name: str) -> bool:
        """Remove a directory watch by name."""
        if name in self._watches:
            del self._watches[name]
            if name in self._seen_files:
                del self._seen_files[name]
            logger.info(f"Removed watch: {name}")
            return True
        return False
    
    def get_watch(self, name: str) -> Optional[WatchConfig]:
        """Get a watch configuration by name."""
        return self._watches.get(name)
    
    async def start(self) -> None:
        """Start watching all configured directories."""
        if self._running:
            logger.warning("FileWatcher is already running")
            return
        
        self._running = True
        logger.info(f"Starting file watcher with {len(self._watches)} watches")
        
        # Start debounce processor
        self._debounce_task = asyncio.create_task(self._process_debounce_queue())
        
        # Start a watcher task for each watch
        for name, config in self._watches.items():
            if config.enabled:
                task = asyncio.create_task(self._watch_directory(config))
                self._tasks.append(task)
                logger.info(f"Started watching: {name}")
    
    async def stop(self) -> None:
        """Stop all watches."""
        self._running = False
        
        # Cancel all tasks
        for task in self._tasks:
            task.cancel()
        
        if self._debounce_task:
            self._debounce_task.cancel()
        
        # Wait for tasks to complete
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        
        self._tasks.clear()
        self._pending_events.clear()
        
        logger.info("File watcher stopped")
    
    async def scan_existing(self, watch_name: Optional[str] = None) -> List[FileEvent]:
        """Scan for existing files that match watch patterns.
        
        This is useful for processing files that existed before the watcher started.
        
        Args:
            watch_name: Optional specific watch to scan. If None, scans all watches.
            
        Returns:
            List of FileEvent objects for matching files.
        """
        events = []
        
        watches_to_scan = (
            [self._watches[watch_name]] if watch_name and watch_name in self._watches
            else self._watches.values()
        )
        
        for config in watches_to_scan:
            if not config.enabled:
                continue
            
            if not config.path.exists():
                continue
            
            # Get all files in the directory
            if config.recursive:
                files = list(config.path.rglob("*"))
            else:
                files = list(config.path.iterdir())
            
            for file_path in files:
                if not file_path.is_file():
                    continue
                
                if config.matches_file(file_path):
                    event = FileEvent(
                        event_type=WatchEvent.CREATED,
                        path=file_path,
                        watch_config=config,
                    )
                    events.append(event)
                    self._seen_files[config.name].add(str(file_path))
        
        logger.info(f"Scanned existing files: found {len(events)} matching files")
        return events
    
    async def _watch_directory(self, config: WatchConfig) -> None:
        """Watch a single directory for changes."""
        try:
            logger.debug(f"Starting watch loop for: {config.name}")
            
            async for changes in awatch(
                config.path,
                recursive=config.recursive,
                step=100,  # Check every 100ms
            ):
                if not self._running:
                    break
                
                for change_type, path_str in changes:
                    path = Path(path_str)
                    
                    # Skip directories
                    if path.is_dir():
                        continue
                    
                    # Check if file matches patterns
                    if not config.matches_file(path):
                        continue
                    
                    # Map watchfiles Change to our WatchEvent
                    event_type = self._map_change_type(change_type, path_str, config)
                    
                    if event_type and event_type in config.events:
                        file_event = FileEvent(
                            event_type=event_type,
                            path=path,
                            watch_config=config,
                        )
                        
                        # Add to debounce queue
                        self._queue_event(file_event)
                        
        except asyncio.CancelledError:
            logger.debug(f"Watch cancelled: {config.name}")
        except Exception as e:
            logger.error(f"Error in watch {config.name}: {e}", exc_info=True)
    
    def _map_change_type(self, change: Change, path_str: str, config: WatchConfig) -> Optional[WatchEvent]:
        """Map watchfiles Change to our WatchEvent."""
        path_key = str(path_str)
        seen = self._seen_files.get(config.name, set())
        
        if change == Change.added:
            seen.add(path_key)
            return WatchEvent.CREATED
        elif change == Change.modified:
            if path_key in seen:
                return WatchEvent.MODIFIED
            else:
                # First time seeing this file, treat as created
                seen.add(path_key)
                return WatchEvent.CREATED
        elif change == Change.deleted:
            seen.discard(path_key)
            return WatchEvent.DELETED
        
        return None
    
    def _queue_event(self, event: FileEvent) -> None:
        """Add an event to the debounce queue."""
        path_key = str(event.path)
        scheduled_time = datetime.now() + timedelta(seconds=event.watch_config.debounce_seconds)
        
        self._pending_events[path_key] = PendingEvent(
            file_event=event,
            scheduled_time=scheduled_time,
        )
        
        logger.debug(f"Queued event: {event.event_type.value} {event.path} (debounce: {event.watch_config.debounce_seconds}s)")
    
    async def _process_debounce_queue(self) -> None:
        """Process events that have passed their debounce time."""
        try:
            while self._running:
                now = datetime.now()
                events_to_process = []
                
                # Find events ready to process
                for path_key, pending in list(self._pending_events.items()):
                    if now >= pending.scheduled_time:
                        events_to_process.append(pending.file_event)
                        del self._pending_events[path_key]
                
                # Process ready events
                for event in events_to_process:
                    await self._emit_event(event)
                
                # Small sleep to prevent busy loop
                await asyncio.sleep(0.1)
                
        except asyncio.CancelledError:
            pass
    
    async def _emit_event(self, event: FileEvent) -> None:
        """Emit a file event to the callback."""
        logger.info(f"File event: {event.event_type.value} {event.path} (watch: {event.watch_config.name})")
        
        if self._on_file_event:
            try:
                await self._on_file_event(event)
            except Exception as e:
                logger.error(f"Error in file event callback: {e}", exc_info=True)
    
    # Convenience methods for common watch patterns
    
    def add_audio_watch(self, path: Path, name: str = "Audio Input") -> None:
        """Add a watch for audio files."""
        from .watch_config import audio_watch
        self.add_watch(audio_watch(path, name))
    
    def add_video_watch(self, path: Path, name: str = "Video Input") -> None:
        """Add a watch for video files."""
        from .watch_config import video_watch
        self.add_watch(video_watch(path, name))
    
    def add_markdown_watch(
        self, 
        path: Path, 
        name: str = "Markdown Files",
        initial_processor: Optional[str] = None
    ) -> None:
        """Add a watch for markdown files."""
        from .watch_config import markdown_watch
        self.add_watch(markdown_watch(path, name, initial_processor))
    
    def add_obsidian_watch(self, path: Path, name: str = "Obsidian Vault") -> None:
        """Add a watch for an Obsidian vault."""
        from .watch_config import obsidian_watch
        self.add_watch(obsidian_watch(path, name))

