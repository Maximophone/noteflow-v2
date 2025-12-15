# NoteFlow v2

A modular, reversible document processing pipeline with a native UI.

## Architecture

NoteFlow v2 is built around several core concepts:

### Core Concepts

- **Job**: A unit of work flowing through the pipeline (e.g., processing an audio recording)
- **Artifact**: Any side effect created by a processor (files, API calls, frontmatter changes) - tracked for reversal
- **Processor**: A plugin that performs a specific task (transcription, classification, speaker identification)
- **ExecutionContext**: A transaction-like wrapper that tracks all artifacts created during processing

### Key Features

- **Reversible Processing**: Every action is tracked and can be undone
- **Human-in-the-Loop**: Processors can pause for user input via native UI
- **Plugin System**: Add new processors without modifying core code
- **Native UI**: Built with Tauri (Rust + React) for cross-platform desktop support
- **Parallel Execution**: Jobs run concurrently with configurable resource limits

## Project Structure

```
noteflow-v2/
├── core/                   # Core pipeline engine
│   ├── models/             # Data models (Job, Artifact, Step)
│   ├── engine/             # Pipeline execution logic
│   ├── storage/            # SQLite persistence layer
│   ├── plugins/            # Plugin system (loader, registry)
│   └── api/                # HTTP API for UI communication
├── plugins/                # Processor plugins (user-extensible)
├── ui/                     # Tauri native UI
└── tests/                  # Test suite
```

## Installation

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows

# Install dependencies
pip install -e .
```

## Development

```bash
# Run the pipeline server
python -m core.api.server

# Run the UI (in a separate terminal)
cd ui
npm run tauri dev
```

## Creating a Processor Plugin

See `plugins/example/` for a template. Each plugin needs:

1. `manifest.yaml` - Metadata, dependencies, config schema
2. `processor.py` - Implementation of the `Processor` base class
3. `ui/` (optional) - React components for human-in-the-loop workflows

## License

MIT

