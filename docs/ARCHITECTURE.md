# NoteFlow v2 - Architecture & Design Document

## Table of Contents

1. [Project Origins](#project-origins)
2. [Why a Rewrite?](#why-a-rewrite)
3. [Design Goals](#design-goals)
4. [Core Concepts](#core-concepts)
5. [Architecture Overview](#architecture-overview)
6. [Key Abstractions](#key-abstractions)
7. [Data Flow](#data-flow)
8. [File Watching System](#file-watching-system)
9. [Plugin System](#plugin-system)
10. [Reversibility Model](#reversibility-model)
11. [UI Architecture](#ui-architecture)
12. [Migration Path from v1](#migration-path-from-v1)

---

## Project Origins

NoteFlow v2 is a complete architectural redesign of [NoteFlow v1](../../../noteflow/), a document processing pipeline for audio transcription and note management.

### What NoteFlow v1 Does

NoteFlow v1 is a Python-based pipeline that:

- **Transcribes audio/video** files using AssemblyAI
- **Identifies speakers** in transcripts using AI with human-in-the-loop confirmation
- **Classifies transcripts** (meeting, diary, ideas, todos, etc.)
- **Processes notes** based on classification (formatting, summarization, extraction)
- **Integrates with external services** (Notion, Coda, Google Docs, Discord)
- **Manages an Obsidian vault** with markdown files and frontmatter

### NoteFlow v1 Codebase Structure

```
noteflow/
├── main.py                 # Entry point, scheduler, processor instantiation
├── config/                 # Configuration (paths, secrets, services)
├── processors/
│   ├── audio/              # Audio transcription
│   │   ├── transcriber.py  # AssemblyAI integration
│   │   └── video_to_audio.py
│   ├── common/             # Shared utilities
│   │   ├── frontmatter.py  # YAML frontmatter parsing
│   │   └── markdown.py
│   └── notes/              # Note processors
│       ├── base.py         # NoteProcessor base class
│       ├── speaker_identifier.py  # Most complex processor
│       ├── transcript_classifier.py
│       ├── meeting.py
│       ├── diary.py
│       ├── ideas.py
│       ├── todo.py
│       └── ...
├── integrations/           # External service integrations
│   ├── discord/
│   ├── notion_integration.py
│   └── ...
└── prompts/                # AI prompt templates
```

---

## Why a Rewrite?

After extensive analysis of NoteFlow v1, several fundamental issues were identified that couldn't be easily patched:

### 1. No Transactional Undo

**Problem**: When processing goes wrong (e.g., wrong title assigned), effects cascade:
- Files are created in multiple directories
- Frontmatter is updated across many files
- External services are modified (Notion pages created)
- Obsidian links reference the incorrect data

**v1 Approach**: Some processors implement a `reset()` method, but:
- It's manually implemented per processor
- Not all processors have it
- There's no central tracking of what was created
- Reverting requires manual frontmatter editing

**v2 Solution**: Every side effect is tracked as an `Artifact` with before/after state, enabling automatic rollback.

### 2. Tight Coupling Between Processors

**Problem**: Processors depend on each other through direct imports:

```python
# v1: Direct coupling
from .speaker_identifier import SpeakerIdentifier

class MeetingProcessor(NoteProcessor):
    required_stage = SpeakerIdentifier.stage_name  # Tight coupling
```

**v2 Solution**: Declarative dependencies via manifest:

```yaml
# v2: Loose coupling
name: meeting_processor
requires:
  - speaker_identifier
```

### 3. Hardcoded Pipeline Configuration

**Problem**: Processor instantiation in `main.py` is verbose and hardcoded:

```python
# v1: 50+ lines of manual instantiation
if cls is MeetingProcessor:
    instance = cls(input_dir=PATHS.transcriptions, output_dir=PATHS.meetings, template_path=PATHS.meeting_template)
elif cls is DiaryProcessor:
    instance = cls(input_dir=PATHS.transcriptions, output_dir=PATHS.diary)
# ... many more
```

**v2 Solution**: Auto-discovery from `plugins/` directory with configuration in `manifest.yaml`.

### 4. No Central State Management

**Problem**: Processing state is scattered:
- `processing_stages` list in file frontmatter
- `speaker_matcher_task_id` for async UI tasks
- No unified view of pipeline status

**v2 Solution**: Centralized `Job` model in SQLite with full history.

### 5. External UI is Disconnected

**Problem**: The speaker identification UI (`speaker_resolver_app/`) is a separate Flask application:
- Runs on a different port
- Uses polling for status
- No unified experience

**v2 Solution**: Native UI shell with plugin UI components embedded.

### 6. Human-in-the-Loop is Bolted On

**Problem**: The speaker identifier has complex substage logic:

```python
# v1: Manual substage management
async def process_file(self, filename: str) -> None:
    if 'identified_speakers' not in frontmatter:
        await self._substage1_identify_speakers(...)
    if 'speaker_matcher_task_id' not in frontmatter:
        await self._substage2_initiate_matching(...)
    if 'final_speaker_mapping' not in frontmatter:
        await self._substage3_process_results(...)
```

**v2 Solution**: First-class `AWAITING_INPUT` job status with structured input/resume flow.

---

## Design Goals

### Primary Goals

1. **Reversibility First**: Every action can be undone
2. **Modular Plugin System**: Add processors without modifying core
3. **Native UI**: Single application for all interactions
4. **Human-in-the-Loop Native**: Pause/resume is a core concept
5. **Parallel Execution**: Process multiple jobs concurrently

### Secondary Goals

1. **Type Safety**: Full type hints throughout
2. **Async Native**: Built on asyncio from the ground up
3. **Observable**: Real-time status via WebSocket
4. **Testable**: Clean abstractions enable unit testing

### Non-Goals (for v2.0)

1. Backward compatibility with v1 file formats
2. Distributed processing across machines
3. Multi-user support

---

## Core Concepts

### Job

A **Job** is the primary unit of work. It represents something being processed through the pipeline (e.g., an audio file becoming a meeting note).

```
Job Lifecycle:
  PENDING → PROCESSING → AWAITING_INPUT → PROCESSING → COMPLETED
                ↓                              ↓
              FAILED                       REVERTED
```

### Artifact

An **Artifact** is any side effect created during processing:
- File creation/modification/deletion
- Frontmatter updates
- External API calls

Artifacts enable reversibility by storing before/after state.

### Processor

A **Processor** is a plugin that performs a specific task. It implements:
- `should_process(job)` - Should this processor handle this job?
- `process(job, ctx)` - Execute the processing
- `revert(job, result, ctx)` - Custom cleanup during revert

### ExecutionContext

The **ExecutionContext** is a transaction-like wrapper that:
- Tracks all artifacts created during processing
- Auto-rollbacks on exception
- Provides safe file/API operations

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              NoteFlow v2                                │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                         Native UI (Tauri)                         │  │
│  │                                                                   │  │
│  │  React + TypeScript + Vite                                        │  │
│  │  - Job list and status                                            │  │
│  │  - Processing timeline                                            │  │
│  │  - Artifact browser                                               │  │
│  │  - Plugin UI panels (dynamic)                                     │  │
│  │                                                                   │  │
│  └───────────────────────────────┬──────────────────────────────────┘  │
│                                  │ WebSocket + REST                    │
│                                  ▼                                     │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                      API Server (FastAPI)                         │  │
│  │                                                                   │  │
│  │  /api/jobs      - CRUD, process, revert                          │  │
│  │  /api/artifacts - List, inspect                                   │  │
│  │  /api/processors - List, reload                                   │  │
│  │  /ws            - Real-time events                                │  │
│  │                                                                   │  │
│  └───────────────────────────────┬──────────────────────────────────┘  │
│                                  │                                     │
│                                  ▼                                     │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                        Pipeline Engine                            │  │
│  │                                                                   │  │
│  │  ┌─────────────┐    ┌─────────────┐    ┌──────────────────────┐  │  │
│  │  │   Pipeline  │───▶│   Router    │───▶│     Executor         │  │  │
│  │  │ (orchestr.) │    │ (deps/order)│    │ (run/revert steps)   │  │  │
│  │  └─────────────┘    └─────────────┘    └──────────────────────┘  │  │
│  │         │                                        │                │  │
│  │         ▼                                        ▼                │  │
│  │  ┌─────────────┐                      ┌──────────────────────┐   │  │
│  │  │   Plugin    │                      │  ExecutionContext    │   │  │
│  │  │   Loader    │                      │  (artifact tracking) │   │  │
│  │  └─────────────┘                      └──────────────────────┘   │  │
│  │         │                                        │                │  │
│  └─────────┼────────────────────────────────────────┼────────────────┘  │
│            │                                        │                   │
│            ▼                                        ▼                   │
│  ┌─────────────────┐                    ┌────────────────────────────┐ │
│  │    Processor    │                    │      Storage Layer         │ │
│  │    Registry     │                    │                            │ │
│  │                 │                    │  ┌──────────┐ ┌──────────┐ │ │
│  │  - example      │                    │  │ JobStore │ │ Artifact │ │ │
│  │  - transcribe   │                    │  │          │ │  Store   │ │ │
│  │  - classify     │                    │  └────┬─────┘ └────┬─────┘ │ │
│  │  - speakers     │                    │       │            │       │ │
│  │  - meeting      │                    │       └─────┬──────┘       │ │
│  │  - ...          │                    │             ▼              │ │
│  └─────────────────┘                    │      ┌──────────────┐      │ │
│                                         │      │   SQLite     │      │ │
│                                         │      │  (noteflow.db)│     │ │
│                                         │      └──────────────┘      │ │
│                                         └────────────────────────────┘ │
│                                                                         │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                     Processor Plugins                             │  │
│  │                                                                   │  │
│  │  plugins/                                                         │  │
│  │  ├── example/          (built-in demo)                           │  │
│  │  ├── transcribe/       (AssemblyAI)                              │  │
│  │  ├── classify/         (AI classification)                       │  │
│  │  ├── speaker_match/    (with embedded UI)                        │  │
│  │  └── ...                                                          │  │
│  │                                                                   │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Key Abstractions

### Job Model

```python
class Job(BaseModel):
    id: str                      # UUID
    source_type: str             # "file", "url", "api", "manual"
    source_name: str             # Human-readable name
    source_path: Optional[str]   # Original file path
    
    status: JobStatus            # pending, processing, awaiting_input, completed, failed
    current_step: Optional[str]  # Active processor name
    
    data: dict                   # Mutable context passed between steps
    history: list[StepResult]    # All step executions (for audit/revert)
    
    config: dict                 # Job-specific config overrides
    tags: list[str]              # User-defined tags
    priority: int                # Higher = processed first
```

### Artifact Model

```python
class Artifact(BaseModel):
    id: str
    job_id: str
    step_name: str
    artifact_type: ArtifactType  # file_create, file_modify, frontmatter_update, external_api_create, ...
    
    target: str                  # File path or "service:action"
    before_state: Optional[str]  # Original content (for revert)
    after_state: Optional[str]   # New content
    
    status: ArtifactStatus       # pending, created, reverted, irreversible
    reversibility: ReversibilityLevel  # fully_reversible, partially_reversible, irreversible
```

### Processor Base Class

```python
class Processor(ABC):
    # Metadata
    name: str                    # Unique identifier
    display_name: str            # For UI
    requires: list[str] = []     # Dependencies (processor names)
    
    # Configuration
    config_schema: dict = {}     # JSON Schema for options
    
    # UI
    has_ui: bool = False
    requires_input: str = "never"  # "never", "always", "conditional"
    
    @abstractmethod
    async def should_process(self, job: Job) -> bool:
        """Should this processor handle this job?"""
    
    @abstractmethod
    async def process(self, job: Job, ctx: ExecutionContext) -> StepResult:
        """Execute processing. Use ctx for all side effects."""
    
    @abstractmethod
    async def revert(self, job: Job, result: StepResult, ctx: ExecutionContext) -> bool:
        """Custom cleanup during revert."""
```

### ExecutionContext

```python
class ExecutionContext:
    """Transaction-like wrapper for processor operations."""
    
    async def create_file(self, path, content) -> Artifact:
        """Create file and track as artifact."""
    
    async def modify_file(self, path, new_content) -> Artifact:
        """Modify file, storing original for revert."""
    
    async def update_frontmatter(self, path, updates) -> Artifact:
        """Update YAML frontmatter."""
    
    async def record_api_call(self, service, action, request, response, reversible=False) -> Artifact:
        """Track external API call."""
    
    async def commit(self) -> list[Artifact]:
        """Finalize all artifacts."""
    
    async def rollback(self):
        """Undo all pending artifacts."""
```

---

## Data Flow

### Processing Flow

```
1. Job Created (status: PENDING)
   └─> Stored in SQLite

2. Background Worker picks up job
   └─> Router.get_next_step(job) → determines first processor

3. For each applicable processor:
   ├─> Executor.execute_step(job, step_name)
   │   ├─> processor.should_process(job) → skip if False
   │   ├─> Check if requires_input → pause if needed
   │   ├─> Create ExecutionContext
   │   ├─> processor.process(job, ctx)
   │   │   └─> ctx.create_file(), ctx.update_frontmatter(), etc.
   │   ├─> ctx.commit() → save artifacts
   │   └─> Update job.history with StepResult
   └─> Router.get_next_step(job) → next processor or None

4. Job Complete (status: COMPLETED)
   └─> All steps in history, all artifacts tracked
```

### Revert Flow

```
1. User requests revert to step X

2. Find all steps after X in job.history

3. For each step (reverse order):
   ├─> Get StepResult.artifacts
   ├─> For each artifact (reverse order):
   │   ├─> If FILE_CREATE: delete file
   │   ├─> If FILE_MODIFY: restore before_state
   │   ├─> If FRONTMATTER_UPDATE: restore original
   │   └─> Mark artifact as REVERTED
   ├─> processor.revert(job, result, ctx) for custom cleanup
   └─> Mark step as REVERTED

4. Update job status to PENDING, current_step to X
   └─> Job can now be re-processed
```

---

## File Watching System

The file watcher automatically monitors directories for new files and creates jobs when matching files are detected.

### Watch Configuration

Watches are configured via `config/watches.yaml`:

```yaml
watches:
  - name: Audio Input
    path: ~/NoteFlow/Audio/Incoming
    patterns:
      - "*.mp3"
      - "*.m4a"
      - "*.wav"
    source_type: audio
    initial_processor: transcribe
    tags:
      - transcription
    priority: 10
    
  - name: Transcriptions
    path: ~/Obsidian/KnowledgeBot/Transcriptions
    patterns:
      - "*.md"
    source_type: markdown
    events:
      - created
      - modified
    tags:
      - transcript
```

### WatchConfig Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `name` | string | required | Unique identifier for this watch |
| `path` | string | required | Directory path to watch |
| `patterns` | list | `["*"]` | File patterns to match (e.g., `["*.md", "*.mp3"]`) |
| `recursive` | bool | `false` | Watch subdirectories |
| `events` | list | `["created", "modified"]` | Events to trigger jobs |
| `source_type` | string | `"file"` | Type for created jobs |
| `initial_processor` | string | `null` | First processor to run |
| `debounce_seconds` | float | `1.0` | Delay before processing (handles rapid saves) |
| `ignore_patterns` | list | common ignores | Patterns to skip |
| `enabled` | bool | `true` | Whether this watch is active |
| `tags` | list | `[]` | Tags for created jobs |
| `priority` | int | `0` | Priority for created jobs |

### Watch Events

| Event | Description |
|-------|-------------|
| `created` | New file detected |
| `modified` | Existing file changed |
| `deleted` | File removed |
| `moved` | File renamed/moved |

### Convenience Factory Functions

```python
from core.watchers import audio_watch, video_watch, markdown_watch, obsidian_watch

# Preset configurations
pipeline.add_watch(audio_watch(Path("~/Audio/Incoming")))
pipeline.add_watch(markdown_watch(Path("~/Notes"), initial_processor="classify"))
pipeline.add_watch(obsidian_watch(Path("~/Obsidian/Vault")))
```

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/watches` | GET | List all watches |
| `/api/watches` | POST | Add a new watch |
| `/api/watches/{name}` | GET | Get watch by name |
| `/api/watches/{name}` | DELETE | Remove a watch |
| `/api/watches/start` | POST | Start file watching |
| `/api/watches/stop` | POST | Stop file watching |
| `/api/watches/scan` | POST | Scan existing files |
| `/api/watches/status` | GET | Get watcher status |

### How It Works

1. **Startup**: Watches are loaded from `config/watches.yaml`
2. **Detection**: `watchfiles` library monitors directories for changes
3. **Debouncing**: Rapid changes are coalesced (e.g., multiple saves)
4. **Job Creation**: Matching files create new jobs with configured properties
5. **Processing**: Background worker picks up jobs and processes them

```
File Created/Modified
        │
        ▼
   FileWatcher
        │
   ┌────┴────┐
   │ Match?  │──No──> Ignore
   └────┬────┘
        │Yes
        ▼
   Debounce (1s)
        │
        ▼
  Create Job
        │
        ▼
  Background Worker
        │
        ▼
   Process Job
```

---

## Plugin System

### Plugin Structure

```
plugins/
└── my_processor/
    ├── manifest.yaml      # Metadata, dependencies, config schema
    ├── processor.py       # Processor implementation
    └── ui/                # Optional UI components
        ├── Panel.tsx      # Main UI panel
        └── components/    # Supporting components
```

### manifest.yaml

```yaml
name: my_processor
display_name: My Processor
description: What this processor does
version: 1.0.0

# Dependencies
requires:
  - other_processor      # Must complete first

# Configuration schema
config:
  api_key:
    type: string
    description: API key for the service
  max_retries:
    type: integer
    default: 3
    minimum: 1

# UI configuration
ui:
  has_panel: true
  requires_input: conditional  # never, always, conditional
```

### Plugin Discovery

On startup:
1. `PluginLoader` scans `plugins/` directory
2. For each subdirectory with `processor.py`:
   - Load `manifest.yaml` (optional)
   - Import processor module
   - Find `Processor` subclass
   - Instantiate with config from manifest
   - Register in `ProcessorRegistry`
3. Validate all dependencies exist

### Hot Reload

Plugins can be reloaded at runtime:
```
POST /api/processors/{name}/reload
```

This calls `processor.on_unload()`, reimports the module, and calls `on_load()`.

---

## Reversibility Model

### Reversibility Levels

| Level | Description | Example |
|-------|-------------|---------|
| `FULLY_REVERSIBLE` | Can be completely undone | File creation, frontmatter update |
| `PARTIALLY_REVERSIBLE` | Can be mostly undone | API call that created something deletable |
| `IRREVERSIBLE` | Cannot be undone | Email sent, social media post |
| `MANUAL_REVERT` | Requires human intervention | Complex external system change |

### Artifact Types

| Type | Reversible | Revert Action |
|------|------------|---------------|
| `FILE_CREATE` | ✅ Fully | Delete the file |
| `FILE_MODIFY` | ✅ Fully | Restore `before_state` |
| `FILE_DELETE` | ✅ Fully | Recreate from `before_state` |
| `FILE_MOVE` | ✅ Fully | Move back |
| `FRONTMATTER_UPDATE` | ✅ Fully | Restore original frontmatter |
| `EXTERNAL_API_CREATE` | ⚠️ Depends | If deletable, delete; else mark irreversible |
| `EXTERNAL_API_MODIFY` | ⚠️ Depends | If reversible, call reverse action |

### Handling Irreversible Actions

For actions that cannot be undone (e.g., Notion page creation):

```python
artifact = await ctx.record_api_call(
    service="notion",
    action="create_page",
    request_data={...},
    response_data={...},
    reversible=False  # Mark as irreversible
)
```

The UI will show this artifact with a warning, and revert will skip it but continue with others.

---

## UI Architecture

### Technology Stack

- **Tauri**: Native app shell (Rust backend, web frontend)
- **React 18**: UI framework
- **TypeScript**: Type safety
- **Vite**: Build tool with hot reload

### Component Structure

```
ui/src/
├── App.tsx                 # Main app, layout
├── main.tsx               # Entry point
├── styles.css             # Global styles
├── types/
│   └── index.ts           # TypeScript types
├── api/
│   └── client.ts          # API client
├── hooks/
│   ├── useJobs.ts         # Job data fetching
│   └── useWebSocket.ts    # Real-time updates
└── components/
    ├── Header.tsx         # App header with stats
    ├── Sidebar.tsx        # Job list
    └── JobDetail.tsx      # Job details, timeline, artifacts
```

### Real-time Updates

The UI connects to `/ws` for real-time events:

```typescript
// Events received:
{ event: "job_created", job_id: "...", job: {...} }
{ event: "job_started", job_id: "..." }
{ event: "step_completed", job_id: "...", step_name: "...", status: "..." }
{ event: "step_awaiting_input", job_id: "...", step_name: "..." }
{ event: "job_completed", job_id: "..." }
{ event: "job_failed", job_id: "...", error: "..." }
```

### Plugin UI Integration

Plugins can provide custom UI components that are loaded dynamically:

```tsx
// Future implementation
const PluginPanel = lazy(() => import(`/plugins/${processor.name}/ui/Panel`));
```

---

## Migration Path from v1

### Phase 1: Core Infrastructure ✅

- [x] Data models (Job, Artifact, StepResult)
- [x] SQLite storage layer
- [x] ExecutionContext with artifact tracking
- [x] Plugin system with loader/registry
- [x] Pipeline engine with router/executor
- [x] API server with WebSocket
- [x] Basic UI shell

### Phase 2: Migrate Simple Processors

Start with processors that:
- Don't require user input
- Don't have complex side effects
- Have clear input/output

Candidates:
- `TranscriptClassifier` - Simple AI classification
- `DiaryProcessor` - Format and save
- `IdeaProcessor` - Extract and append

### Phase 3: Migrate Complex Processors

- `AudioTranscriber` - Involves external API (AssemblyAI)
- `SpeakerIdentifier` - Requires human-in-the-loop UI
- `MeetingProcessor` - Creates files in multiple locations
- `NotionUploadProcessor` - External API with partial reversibility

### Phase 4: Integrate External UI

Pull the speaker resolver Flask app into the native UI:
- Convert Flask templates to React components
- Use the plugin UI system
- Replace polling with WebSocket

### Phase 5: Advanced Features

- File watching for auto-job creation
- Batch operations
- Job templates
- Processing presets

---

## Appendix: v1 to v2 Mapping

| v1 Concept | v2 Equivalent |
|------------|---------------|
| `NoteProcessor` base class | `Processor` base class |
| `stage_name` | `Processor.name` |
| `required_stage` | `Processor.requires` list |
| `processing_stages` in frontmatter | `Job.history` (StepResults) |
| Manual `reset()` method | Automatic artifact-based revert |
| `files_in_process` set | `Job.status == PROCESSING` |
| APScheduler polling | Background worker + WebSocket |
| Discord DM for notifications | Native UI notifications |
| External Flask UI | Embedded plugin UI |

---

## Contributing

When adding new processors:

1. Create a new directory in `plugins/`
2. Add `manifest.yaml` with metadata
3. Implement `Processor` subclass in `processor.py`
4. Use `ExecutionContext` for ALL side effects
5. Implement `revert()` for any custom cleanup
6. Add tests in `tests/`

When modifying core:

1. Maintain backward compatibility with existing plugins
2. Update this document
3. Add tests for new functionality
4. Consider impact on reversibility model

