"""FastAPI server for UI communication."""

from pathlib import Path
from typing import Optional, Any
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict
import uvicorn
import asyncio
import json

from ..engine.pipeline import Pipeline
from ..models import JobStatus
from ..watchers import WatchConfig, load_watches_from_yaml, save_watches_to_yaml, write_example_config

logger = logging.getLogger(__name__)

# Global pipeline instance
pipeline: Optional[Pipeline] = None


# -------------------------------------------------------------------------
# Request/Response Models
# -------------------------------------------------------------------------

class CreateJobRequest(BaseModel):
    """Request to create a new job."""
    source_type: str
    source_name: str
    source_path: Optional[str] = None
    source_url: Optional[str] = None
    data: Optional[dict] = None
    config: Optional[dict] = None
    tags: Optional[list[str]] = None
    priority: int = 0


class ResumeJobRequest(BaseModel):
    """Request to resume a job with user input."""
    user_input: dict


class RevertJobRequest(BaseModel):
    """Request to revert a job."""
    to_step: Optional[str] = None


class JobResponse(BaseModel):
    """Job response model."""
    id: str
    source_type: str
    source_name: str
    source_path: Optional[str]
    source_url: Optional[str]
    status: str
    current_step: Optional[str]
    data: dict
    history: list[dict]
    tags: list[str]
    priority: int
    error_message: Optional[str]
    created_at: str
    updated_at: str

    model_config = ConfigDict(from_attributes=True)


class StatsResponse(BaseModel):
    """Pipeline statistics response."""
    running: bool
    active_jobs: int
    max_concurrent: int
    processors_loaded: int
    jobs_by_status: dict[str, int]
    watches: int
    watching: bool


class ProcessorInfo(BaseModel):
    """Processor information."""
    name: str
    display_name: str
    description: str
    version: str
    requires: list[str]
    has_ui: bool
    requires_input: str


class WatchResponse(BaseModel):
    """Watch configuration response."""
    name: str
    path: str
    patterns: list[str]
    recursive: bool
    events: list[str]
    source_type: str
    initial_processor: Optional[str]
    debounce_seconds: float
    enabled: bool
    tags: list[str]
    priority: int


class AddWatchRequest(BaseModel):
    """Request to add a new watch."""
    name: str
    path: str
    patterns: list[str] = ["*"]
    recursive: bool = False
    events: list[str] = ["created", "modified"]
    source_type: str = "file"
    initial_processor: Optional[str] = None
    debounce_seconds: float = 1.0
    enabled: bool = True
    tags: list[str] = []
    priority: int = 0
    metadata: dict = {}


# -------------------------------------------------------------------------
# WebSocket Connection Manager
# -------------------------------------------------------------------------

class ConnectionManager:
    """Manages WebSocket connections for real-time updates."""
    
    def __init__(self):
        self.active_connections: list[WebSocket] = []
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket connected. Total connections: {len(self.active_connections)}")
    
    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info(f"WebSocket disconnected. Total connections: {len(self.active_connections)}")
    
    async def broadcast(self, message: dict):
        """Broadcast a message to all connected clients."""
        if not self.active_connections:
            return
        
        message_json = json.dumps(message, default=str)
        
        for connection in self.active_connections.copy():
            try:
                await connection.send_text(message_json)
            except Exception as e:
                logger.warning(f"Error sending WebSocket message: {e}")
                self.disconnect(connection)


manager = ConnectionManager()


# -------------------------------------------------------------------------
# App Lifecycle
# -------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global pipeline
    
    # Startup
    logger.info("Starting NoteFlow API server...")
    
    # Get paths from environment or use defaults
    import os
    db_path = os.environ.get("NOTEFLOW_DB_PATH", "data/noteflow.db")
    plugins_dir = os.environ.get("NOTEFLOW_PLUGINS_DIR", "plugins")
    
    pipeline = Pipeline(db_path=db_path, plugins_dir=plugins_dir)
    await pipeline.start()
    
    # Register callbacks for WebSocket broadcasts
    pipeline.on("job_created", on_job_created)
    pipeline.on("job_started", on_job_started)
    pipeline.on("job_completed", on_job_completed)
    pipeline.on("job_failed", on_job_failed)
    pipeline.on("step_completed", on_step_completed)
    pipeline.on("step_awaiting_input", on_step_awaiting_input)
    pipeline.on("file_detected", on_file_detected)
    
    # Load watches from config file if it exists
    watches_config_path = Path(os.environ.get("NOTEFLOW_WATCHES_CONFIG", "config/watches.yaml"))
    if watches_config_path.exists():
        watches = load_watches_from_yaml(watches_config_path)
        for watch in watches:
            pipeline.add_watch(watch)
        logger.info(f"Loaded {len(watches)} watch configurations")
        
        # Start file watching
        await pipeline.start_watching()
    
    # Start background worker
    await pipeline.start_background_worker()
    
    logger.info("NoteFlow API server started")
    
    yield
    
    # Shutdown
    logger.info("Shutting down NoteFlow API server...")
    await pipeline.stop()
    logger.info("NoteFlow API server stopped")


# -------------------------------------------------------------------------
# Event Callbacks (for WebSocket)
# -------------------------------------------------------------------------

async def on_job_created(job):
    await manager.broadcast({"event": "job_created", "job_id": job.id, "job": job.model_dump()})

async def on_job_started(job):
    await manager.broadcast({"event": "job_started", "job_id": job.id})

async def on_job_completed(job):
    await manager.broadcast({"event": "job_completed", "job_id": job.id})

async def on_job_failed(job):
    await manager.broadcast({"event": "job_failed", "job_id": job.id, "error": job.error_message})

async def on_step_completed(job, result):
    await manager.broadcast({
        "event": "step_completed",
        "job_id": job.id,
        "step_name": result.step_name,
        "status": result.status,
    })

async def on_step_awaiting_input(job, step_name):
    await manager.broadcast({
        "event": "step_awaiting_input",
        "job_id": job.id,
        "step_name": step_name,
    })

async def on_file_detected(event):
    await manager.broadcast({
        "event": "file_detected",
        "path": str(event.path),
        "watch_name": event.watch_config.name,
        "event_type": event.event_type.value,
    })


# -------------------------------------------------------------------------
# App Factory
# -------------------------------------------------------------------------

def create_app() -> FastAPI:
    """Create the FastAPI application."""
    app = FastAPI(
        title="NoteFlow v2 API",
        description="API for the NoteFlow document processing pipeline",
        version="2.0.0",
        lifespan=lifespan,
    )
    
    # Add CORS middleware for UI development
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # In production, restrict this
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # -------------------------------------------------------------------------
    # Health Check
    # -------------------------------------------------------------------------
    
    @app.get("/health")
    async def health_check():
        """Health check endpoint."""
        return {"status": "healthy"}
    
    # -------------------------------------------------------------------------
    # Pipeline Stats
    # -------------------------------------------------------------------------
    
    @app.get("/api/stats", response_model=StatsResponse)
    async def get_stats():
        """Get pipeline statistics."""
        return await pipeline.get_stats()
    
    # -------------------------------------------------------------------------
    # Job Endpoints
    # -------------------------------------------------------------------------
    
    @app.get("/api/jobs", response_model=list[JobResponse])
    async def list_jobs(
        status: Optional[str] = Query(None, description="Filter by status"),
        limit: int = Query(100, ge=1, le=1000),
        offset: int = Query(0, ge=0),
    ):
        """List all jobs."""
        status_enum = JobStatus(status) if status else None
        jobs = await pipeline.list_jobs(status=status_enum, limit=limit, offset=offset)
        return [_job_to_response(j) for j in jobs]
    
    @app.post("/api/jobs", response_model=JobResponse, status_code=201)
    async def create_job(request: CreateJobRequest):
        """Create a new job."""
        job = await pipeline.create_job(
            source_type=request.source_type,
            source_name=request.source_name,
            source_path=request.source_path,
            source_url=request.source_url,
            data=request.data,
            config=request.config,
            tags=request.tags,
            priority=request.priority,
        )
        return _job_to_response(job)
    
    @app.get("/api/jobs/{job_id}", response_model=JobResponse)
    async def get_job(job_id: str):
        """Get a job by ID."""
        job = await pipeline.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        return _job_to_response(job)
    
    @app.delete("/api/jobs/{job_id}")
    async def delete_job(job_id: str, revert: bool = Query(True)):
        """Delete a job."""
        success = await pipeline.delete_job(job_id, revert_first=revert)
        if not success:
            raise HTTPException(status_code=404, detail="Job not found")
        return {"deleted": True}
    
    @app.post("/api/jobs/{job_id}/process", response_model=JobResponse)
    async def process_job(job_id: str):
        """Process a job immediately."""
        try:
            job = await pipeline.process_job(job_id)
            return _job_to_response(job)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
    
    @app.post("/api/jobs/{job_id}/resume", response_model=JobResponse)
    async def resume_job(job_id: str, request: ResumeJobRequest):
        """Resume a job with user input."""
        try:
            job = await pipeline.resume_job(job_id, request.user_input)
            return _job_to_response(job)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    
    @app.post("/api/jobs/{job_id}/cancel", response_model=JobResponse)
    async def cancel_job(job_id: str):
        """Cancel a job."""
        try:
            job = await pipeline.cancel_job(job_id)
            return _job_to_response(job)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
    
    @app.post("/api/jobs/{job_id}/revert", response_model=JobResponse)
    async def revert_job(job_id: str, request: RevertJobRequest):
        """Revert a job to a previous state."""
        try:
            job = await pipeline.revert_job(job_id, to_step=request.to_step)
            return _job_to_response(job)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    
    # -------------------------------------------------------------------------
    # Processor Endpoints
    # -------------------------------------------------------------------------
    
    @app.get("/api/processors", response_model=list[ProcessorInfo])
    async def list_processors():
        """List all loaded processors."""
        return pipeline.get_processors()
    
    @app.post("/api/processors/{name}/reload")
    async def reload_processor(name: str):
        """Reload a processor plugin."""
        success = await pipeline.reload_plugin(name)
        if not success:
            raise HTTPException(status_code=404, detail="Processor not found")
        return {"reloaded": True}
    
    # -------------------------------------------------------------------------
    # Artifacts Endpoints
    # -------------------------------------------------------------------------
    
    @app.get("/api/jobs/{job_id}/artifacts")
    async def list_job_artifacts(job_id: str):
        """List all artifacts for a job."""
        artifacts = await pipeline.artifact_store.list_by_job(job_id)
        return [a.model_dump() for a in artifacts]
    
    # -------------------------------------------------------------------------
    # Watch Endpoints
    # -------------------------------------------------------------------------
    
    @app.get("/api/watches", response_model=list[WatchResponse])
    async def list_watches():
        """List all configured file watches."""
        return [_watch_to_response(w) for w in pipeline.list_watches()]
    
    @app.post("/api/watches", response_model=WatchResponse, status_code=201)
    async def add_watch(request: AddWatchRequest):
        """Add a new file watch."""
        from ..watchers import WatchConfig, WatchEvent
        
        config = WatchConfig(
            path=Path(request.path),
            name=request.name,
            patterns=request.patterns,
            recursive=request.recursive,
            events={WatchEvent(e) for e in request.events},
            source_type=request.source_type,
            initial_processor=request.initial_processor,
            debounce_seconds=request.debounce_seconds,
            enabled=request.enabled,
            tags=request.tags,
            priority=request.priority,
            metadata=request.metadata,
        )
        
        pipeline.add_watch(config)
        
        # Restart watcher if it was running
        if pipeline.file_watcher.is_running:
            await pipeline.stop_watching()
            await pipeline.start_watching()
        
        return _watch_to_response(config)
    
    @app.get("/api/watches/{name}", response_model=WatchResponse)
    async def get_watch(name: str):
        """Get a watch configuration by name."""
        watch = pipeline.get_watch(name)
        if not watch:
            raise HTTPException(status_code=404, detail="Watch not found")
        return _watch_to_response(watch)
    
    @app.delete("/api/watches/{name}")
    async def remove_watch(name: str):
        """Remove a watch by name."""
        success = pipeline.remove_watch(name)
        if not success:
            raise HTTPException(status_code=404, detail="Watch not found")
        return {"deleted": True}
    
    @app.post("/api/watches/start")
    async def start_watching():
        """Start file watching."""
        await pipeline.start_watching()
        return {"status": "watching", "watches": len(pipeline.list_watches())}
    
    @app.post("/api/watches/stop")
    async def stop_watching():
        """Stop file watching."""
        await pipeline.stop_watching()
        return {"status": "stopped"}
    
    @app.post("/api/watches/scan")
    async def scan_existing(watch_name: Optional[str] = Query(None)):
        """Scan existing files and create jobs."""
        jobs = await pipeline.scan_existing_files(watch_name)
        return {
            "scanned": True,
            "jobs_created": len(jobs),
            "job_ids": [j.id for j in jobs],
        }
    
    @app.get("/api/watches/status")
    async def watch_status():
        """Get file watching status."""
        return {
            "watching": pipeline.file_watcher.is_running,
            "watches_configured": len(pipeline.list_watches()),
            "watches": [
                {
                    "name": w.name,
                    "enabled": w.enabled,
                    "path": str(w.path),
                    "path_exists": w.path.exists(),
                }
                for w in pipeline.list_watches()
            ],
        }
    
    # -------------------------------------------------------------------------
    # WebSocket
    # -------------------------------------------------------------------------
    
    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        """WebSocket endpoint for real-time updates."""
        await manager.connect(websocket)
        try:
            while True:
                # Just keep the connection alive
                # Client can send messages if needed
                data = await websocket.receive_text()
                # Handle any client messages here if needed
                logger.debug(f"Received WebSocket message: {data}")
        except WebSocketDisconnect:
            manager.disconnect(websocket)
    
    return app


def _job_to_response(job) -> dict:
    """Convert a Job to a response dict."""
    return {
        "id": job.id,
        "source_type": job.source_type,
        "source_name": job.source_name,
        "source_path": job.source_path,
        "source_url": job.source_url,
        "status": job.status,
        "current_step": job.current_step,
        "data": job.data,
        "history": [r.model_dump() for r in job.history],
        "tags": job.tags,
        "priority": job.priority,
        "error_message": job.error_message,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }


def _watch_to_response(watch: WatchConfig) -> dict:
    """Convert a WatchConfig to a response dict."""
    return {
        "name": watch.name,
        "path": str(watch.path),
        "patterns": watch.patterns,
        "recursive": watch.recursive,
        "events": [e.value for e in watch.events],
        "source_type": watch.source_type,
        "initial_processor": watch.initial_processor,
        "debounce_seconds": watch.debounce_seconds,
        "enabled": watch.enabled,
        "tags": watch.tags,
        "priority": watch.priority,
    }


# -------------------------------------------------------------------------
# Main Entry Point
# -------------------------------------------------------------------------

def main():
    """Run the API server."""
    import argparse
    
    parser = argparse.ArgumentParser(description="NoteFlow v2 API Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind to")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")
    parser.add_argument("--log-level", default="info", help="Log level")
    args = parser.parse_args()
    
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    
    uvicorn.run(
        "core.api.server:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()

