"""Configuration and events for file watching."""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional, List, Set, Callable, Any
from datetime import datetime


class WatchEvent(Enum):
    """Types of file system events to watch for."""
    CREATED = "created"
    MODIFIED = "modified"
    DELETED = "deleted"
    MOVED = "moved"


@dataclass
class WatchConfig:
    """Configuration for a single directory watch.
    
    Attributes:
        path: Directory path to watch
        name: Human-readable name for this watch
        patterns: File patterns to match (e.g., ["*.md", "*.mp3"])
        recursive: Whether to watch subdirectories
        events: Which events trigger job creation
        source_type: The source_type to assign to created jobs
        initial_processor: Optional processor to start with
        debounce_seconds: Delay before processing (for rapid changes)
        ignore_patterns: Patterns to ignore (e.g., ["*.tmp", ".DS_Store"])
        enabled: Whether this watch is active
        tags: Tags to add to created jobs
        priority: Priority for created jobs
        metadata: Additional metadata to include in job data
    """
    path: Path
    name: str
    patterns: List[str] = field(default_factory=lambda: ["*"])
    recursive: bool = False
    events: Set[WatchEvent] = field(default_factory=lambda: {WatchEvent.CREATED, WatchEvent.MODIFIED})
    source_type: str = "file"
    initial_processor: Optional[str] = None
    debounce_seconds: float = 1.0
    ignore_patterns: List[str] = field(default_factory=lambda: [
        "*.tmp",
        "*.temp",
        ".DS_Store",
        "Thumbs.db",
        "*.swp",
        "*.swo",
        "*~",
        ".git/*",
    ])
    enabled: bool = True
    tags: List[str] = field(default_factory=list)
    priority: int = 0
    metadata: dict = field(default_factory=dict)
    
    def matches_file(self, file_path: Path) -> bool:
        """Check if a file matches this watch's patterns."""
        import fnmatch
        
        filename = file_path.name
        
        # Check ignore patterns first
        for pattern in self.ignore_patterns:
            if fnmatch.fnmatch(filename, pattern):
                return False
            # Also check full path for patterns like ".git/*"
            if fnmatch.fnmatch(str(file_path), pattern):
                return False
        
        # Check if matches any positive pattern
        for pattern in self.patterns:
            if fnmatch.fnmatch(filename, pattern):
                return True
        
        return False
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "path": str(self.path),
            "name": self.name,
            "patterns": self.patterns,
            "recursive": self.recursive,
            "events": [e.value for e in self.events],
            "source_type": self.source_type,
            "initial_processor": self.initial_processor,
            "debounce_seconds": self.debounce_seconds,
            "ignore_patterns": self.ignore_patterns,
            "enabled": self.enabled,
            "tags": self.tags,
            "priority": self.priority,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "WatchConfig":
        """Create from dictionary."""
        events = {WatchEvent(e) for e in data.get("events", ["created", "modified"])}
        return cls(
            path=Path(data["path"]),
            name=data["name"],
            patterns=data.get("patterns", ["*"]),
            recursive=data.get("recursive", False),
            events=events,
            source_type=data.get("source_type", "file"),
            initial_processor=data.get("initial_processor"),
            debounce_seconds=data.get("debounce_seconds", 1.0),
            ignore_patterns=data.get("ignore_patterns", cls.__dataclass_fields__["ignore_patterns"].default_factory()),
            enabled=data.get("enabled", True),
            tags=data.get("tags", []),
            priority=data.get("priority", 0),
            metadata=data.get("metadata", {}),
        )


@dataclass
class FileEvent:
    """A file system event that occurred."""
    event_type: WatchEvent
    path: Path
    watch_config: WatchConfig
    timestamp: datetime = field(default_factory=datetime.now)
    old_path: Optional[Path] = None  # For move events
    
    @property
    def filename(self) -> str:
        return self.path.name
    
    @property
    def relative_path(self) -> Path:
        """Path relative to the watch directory."""
        try:
            return self.path.relative_to(self.watch_config.path)
        except ValueError:
            return self.path


# Common watch configurations for typical use cases
def audio_watch(path: Path, name: str = "Audio Input") -> WatchConfig:
    """Create a watch config for audio files."""
    return WatchConfig(
        path=path,
        name=name,
        patterns=["*.mp3", "*.m4a", "*.wav", "*.flac", "*.aac", "*.ogg", "*.wma", "*.aiff"],
        source_type="audio",
        initial_processor="transcribe",
        tags=["transcription"],
    )


def video_watch(path: Path, name: str = "Video Input") -> WatchConfig:
    """Create a watch config for video files."""
    return WatchConfig(
        path=path,
        name=name,
        patterns=["*.mp4", "*.mkv", "*.avi", "*.mov", "*.wmv", "*.webm"],
        source_type="video",
        initial_processor="video_to_audio",
        tags=["video", "transcription"],
    )


def markdown_watch(path: Path, name: str = "Markdown Files", initial_processor: Optional[str] = None) -> WatchConfig:
    """Create a watch config for markdown files."""
    return WatchConfig(
        path=path,
        name=name,
        patterns=["*.md"],
        source_type="markdown",
        initial_processor=initial_processor,
        events={WatchEvent.CREATED, WatchEvent.MODIFIED},
        tags=["markdown"],
    )


def obsidian_watch(path: Path, name: str = "Obsidian Vault") -> WatchConfig:
    """Create a watch config for an Obsidian vault."""
    return WatchConfig(
        path=path,
        name=name,
        patterns=["*.md"],
        recursive=True,
        source_type="obsidian",
        ignore_patterns=[
            "*.tmp",
            ".DS_Store",
            ".obsidian/*",
            ".trash/*",
            "*.swp",
        ],
        tags=["obsidian"],
    )

