"""Load watch configurations from YAML files."""

import logging
from pathlib import Path
from typing import List, Optional
import yaml

from .watch_config import WatchConfig, WatchEvent

logger = logging.getLogger(__name__)


def load_watches_from_yaml(config_path: Path) -> List[WatchConfig]:
    """
    Load watch configurations from a YAML file.
    
    Expected format:
    
    ```yaml
    watches:
      - name: Audio Input
        path: /path/to/audio/incoming
        patterns:
          - "*.mp3"
          - "*.m4a"
          - "*.wav"
        source_type: audio
        initial_processor: transcribe
        tags:
          - transcription
        
      - name: Transcriptions
        path: /path/to/vault/Transcriptions
        patterns:
          - "*.md"
        source_type: markdown
        events:
          - created
          - modified
        tags:
          - transcript
    ```
    
    Args:
        config_path: Path to the YAML configuration file
        
    Returns:
        List of WatchConfig objects
    """
    if not config_path.exists():
        logger.warning(f"Watch config file not found: {config_path}")
        return []
    
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception as e:
        logger.error(f"Error loading watch config: {e}")
        return []
    
    if not data:
        return []
    
    watches_data = data.get("watches", [])
    if not watches_data:
        return []
    
    watches = []
    for watch_data in watches_data:
        try:
            config = _parse_watch_config(watch_data)
            if config:
                watches.append(config)
        except Exception as e:
            logger.error(f"Error parsing watch config: {e}")
            continue
    
    logger.info(f"Loaded {len(watches)} watch configurations from {config_path}")
    return watches


def _parse_watch_config(data: dict) -> Optional[WatchConfig]:
    """Parse a single watch configuration from dict."""
    if "name" not in data or "path" not in data:
        logger.warning("Watch config missing required 'name' or 'path' field")
        return None
    
    # Parse path - expand user home and environment variables
    path_str = str(data["path"])
    path = Path(path_str).expanduser()
    
    # Handle environment variable expansion
    import os
    path = Path(os.path.expandvars(str(path)))
    
    # Parse events
    events = {WatchEvent.CREATED, WatchEvent.MODIFIED}  # Default
    if "events" in data:
        events = {WatchEvent(e) for e in data["events"]}
    
    return WatchConfig(
        path=path,
        name=data["name"],
        patterns=data.get("patterns", ["*"]),
        recursive=data.get("recursive", False),
        events=events,
        source_type=data.get("source_type", "file"),
        initial_processor=data.get("initial_processor"),
        debounce_seconds=data.get("debounce_seconds", 1.0),
        ignore_patterns=data.get("ignore_patterns", WatchConfig.__dataclass_fields__["ignore_patterns"].default_factory()),
        enabled=data.get("enabled", True),
        tags=data.get("tags", []),
        priority=data.get("priority", 0),
        metadata=data.get("metadata", {}),
    )


def save_watches_to_yaml(watches: List[WatchConfig], config_path: Path) -> None:
    """
    Save watch configurations to a YAML file.
    
    Args:
        watches: List of WatchConfig objects
        config_path: Path to write the YAML file
    """
    data = {
        "watches": [
            {
                "name": w.name,
                "path": str(w.path),
                "patterns": w.patterns,
                "recursive": w.recursive,
                "events": [e.value for e in w.events],
                "source_type": w.source_type,
                "initial_processor": w.initial_processor,
                "debounce_seconds": w.debounce_seconds,
                "ignore_patterns": w.ignore_patterns,
                "enabled": w.enabled,
                "tags": w.tags,
                "priority": w.priority,
                "metadata": w.metadata,
            }
            for w in watches
        ]
    }
    
    config_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True)
    
    logger.info(f"Saved {len(watches)} watch configurations to {config_path}")


# Example configuration template
EXAMPLE_CONFIG = """# NoteFlow v2 Watch Configuration
# 
# Define directories to watch for automatic job creation.
# Each watch monitors a directory for file changes and creates jobs.

watches:
  # Audio input - transcribes audio files
  - name: Audio Input
    path: ~/path/to/audio/incoming
    patterns:
      - "*.mp3"
      - "*.m4a"
      - "*.wav"
      - "*.flac"
    source_type: audio
    initial_processor: transcribe
    tags:
      - transcription
    priority: 10
  
  # Video input - converts to audio then transcribes
  - name: Video Input
    path: ~/path/to/video/incoming
    patterns:
      - "*.mp4"
      - "*.mkv"
      - "*.mov"
    source_type: video
    initial_processor: video_to_audio
    tags:
      - video
      - transcription
  
  # Transcriptions - classify and process transcripts
  - name: Transcriptions
    path: ~/path/to/vault/Transcriptions
    patterns:
      - "*.md"
    source_type: markdown
    initial_processor: classify
    events:
      - created
      - modified
    tags:
      - transcript
    ignore_patterns:
      - "*.tmp"
      - ".DS_Store"
  
  # Obsidian vault - watch for notes
  - name: Obsidian Vault
    path: ~/Obsidian/MyVault
    patterns:
      - "*.md"
    recursive: true
    source_type: obsidian
    events:
      - created
      - modified
    ignore_patterns:
      - ".obsidian/*"
      - ".trash/*"
      - "*.tmp"
    tags:
      - obsidian
"""


def write_example_config(config_path: Path) -> None:
    """Write an example configuration file."""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(EXAMPLE_CONFIG)
    logger.info(f"Wrote example watch configuration to {config_path}")

