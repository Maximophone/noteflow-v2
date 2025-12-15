"""File watching system for auto-creating jobs from filesystem events."""

from .file_watcher import FileWatcher
from .watch_config import WatchConfig, WatchEvent, FileEvent
from .watch_config import audio_watch, video_watch, markdown_watch, obsidian_watch
from .config_loader import load_watches_from_yaml, save_watches_to_yaml, write_example_config

__all__ = [
    "FileWatcher",
    "WatchConfig",
    "WatchEvent",
    "FileEvent",
    # Factory functions
    "audio_watch",
    "video_watch",
    "markdown_watch",
    "obsidian_watch",
    # Config loading
    "load_watches_from_yaml",
    "save_watches_to_yaml",
    "write_example_config",
]

