# NoteFlow v2 - Testing Guide

This guide explains how to test the file watcher and pipeline with the included test plugins.

## Quick Start

### 1. Install Dependencies

```bash
cd noteflow-v2
pip install -e .
```

### 2. Start the Server

```bash
python -m core.api.server
```

You should see output like:
```
INFO - Starting NoteFlow API server...
INFO - Loaded plugin: text_echo v1.0.0
INFO - Loaded plugin: word_counter v1.0.0
INFO - Loaded 2 watch configurations
INFO - Started file watching with 1 watches
INFO - NoteFlow API server started
INFO - Uvicorn running on http://127.0.0.1:8000
```

### 3. Start the UI (Optional)

In another terminal:
```bash
cd ui
npm install
npm run dev
```

Open http://localhost:5173 in your browser.

### 4. Test the Pipeline

**Option A: Drop a file in the input directory**

```bash
echo "Hello, this is a test file for NoteFlow v2.
It contains some text that will be processed.
The pipeline will add a metadata header and count words." > data/input/test1.txt
```

Watch the terminal - you should see:
```
INFO - File event: created data/input/test1.txt (watch: Test Input)
INFO - Created job from file event: abc123 (test1.txt)
INFO - Processing text file: data/input/test1.txt
INFO - Created processed file: data/processed/processed_test1.txt
INFO - Counting words in: data/processed/processed_test1.txt
INFO - Created stats file: data/stats/stats_processed_test1_abc123.json
INFO - Stats: 45 words, 12 lines
```

**Option B: Use the API**

```bash
# Create a job manually
curl -X POST http://127.0.0.1:8000/api/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "source_type": "text",
    "source_name": "manual_test.txt",
    "source_path": "data/input/manual_test.txt"
  }'

# List jobs
curl http://127.0.0.1:8000/api/jobs

# Get pipeline stats
curl http://127.0.0.1:8000/api/stats

# Check watch status
curl http://127.0.0.1:8000/api/watches/status
```

**Option C: Use the UI**

1. Open http://localhost:5173
2. Click the "+" button in the sidebar to create a test job
3. Watch the job appear and progress through the pipeline

## What Gets Created

When you drop a file like `test1.txt` in `data/input/`:

1. **Job** - Created in the database with status tracking

2. **Processed file** - `data/processed/processed_test1.txt`
   ```
   ============================================================
   PROCESSED BY: NoteFlow v2 - TextEcho
   ORIGINAL FILE: test1.txt
   ORIGINAL PATH: data/input/test1.txt
   PROCESSED AT: 2025-12-15T23:45:00.123456
   JOB ID: abc12345-...
   SOURCE TYPE: text
   ============================================================

   Hello, this is a test file...
   ```

3. **Stats file** - `data/stats/stats_processed_test1_abc12345.json`
   ```json
   {
     "file": "data/processed/processed_test1.txt",
     "analyzed_at": "2025-12-15T23:45:01.234567",
     "job_id": "abc12345-...",
     "line_count": 12,
     "word_count": 45,
     "char_count": 289,
     "unique_word_count": 38,
     "top_10_words": {"the": 3, "a": 2, ...}
   }
   ```

## Testing Revert

The pipeline tracks all file creations as artifacts. You can revert a job:

```bash
# Revert a job (removes created files)
curl -X POST http://127.0.0.1:8000/api/jobs/{job_id}/revert

# Delete a job (reverts first, then removes from DB)
curl -X DELETE http://127.0.0.1:8000/api/jobs/{job_id}
```

After revert, the processed file and stats file will be deleted.

## Testing Watch Management

```bash
# List watches
curl http://127.0.0.1:8000/api/watches

# Get watch status
curl http://127.0.0.1:8000/api/watches/status

# Stop watching
curl -X POST http://127.0.0.1:8000/api/watches/stop

# Start watching again
curl -X POST http://127.0.0.1:8000/api/watches/start

# Scan existing files (creates jobs for files already in input/)
curl -X POST http://127.0.0.1:8000/api/watches/scan
```

## Plugin Chain

The test setup demonstrates processor chaining:

```
text_echo (no requirements)
    │
    └──► word_counter (requires: text_echo)
```

When a file is processed:
1. `text_echo` runs first (creates processed file)
2. `word_counter` runs after (uses output from text_echo)

## Troubleshooting

### "No module named 'core'"
Make sure you installed with `pip install -e .`

### Watch not detecting files
- Check the path in `config/watches.yaml`
- Verify the patterns match your file extension
- Check watch status: `curl http://127.0.0.1:8000/api/watches/status`

### Jobs created but not processing
- Check the server logs for errors
- Verify the processor plugins loaded: `curl http://127.0.0.1:8000/api/processors`

### WebSocket not connecting (UI shows "No jobs yet")
- Install websockets: `pip install websockets`
- Check browser console for connection errors

## Directory Structure

```
noteflow-v2/
├── config/
│   └── watches.yaml        # Watch configuration (auto-loaded)
├── data/
│   ├── input/              # ← DROP FILES HERE
│   ├── processed/          # Processed files appear here
│   ├── stats/              # Statistics files appear here
│   └── noteflow.db         # SQLite database
├── plugins/
│   ├── text_echo/          # First processor in chain
│   └── word_counter/       # Second processor (requires text_echo)
└── ui/                     # React frontend
```

