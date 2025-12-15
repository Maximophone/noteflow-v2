"""
Text Echo Processor

A simple processor that:
1. Reads a text file from the job's source_path
2. Adds metadata header
3. Creates a processed copy in the output directory
4. Records the file creation as an artifact (so it can be reverted)
"""

import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

from core.plugins.base import Processor
from core.models import Job, StepResult, StepStatus
from core.engine.context import ExecutionContext

logger = logging.getLogger(__name__)


class TextEchoProcessor(Processor):
    """Echoes text files with added metadata."""
    
    name = "text_echo"
    display_name = "Text Echo"
    description = "Reads text files and creates processed copies with metadata"
    version = "1.0.0"
    
    requires = []
    has_ui = False
    requires_input = "never"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        self.output_dir = Path(self.config.get("output_dir", "data/processed"))
        self.add_timestamp = self.config.get("add_timestamp", True)
        self.prefix = self.config.get("prefix", "processed_")
        
        # Ensure output directory exists
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"TextEcho initialized: output_dir={self.output_dir}")
    
    async def should_process(self, job: Job) -> bool:
        """Process jobs that have a source_path pointing to a text file."""
        if not job.source_path:
            logger.debug(f"Job {job.id} has no source_path, skipping")
            return False
        
        source = Path(job.source_path)
        
        # Check if file exists
        if not source.exists():
            logger.warning(f"Source file does not exist: {source}")
            return False
        
        # Check if it's a text-like file
        valid_extensions = {".txt", ".md", ".text", ".log"}
        if source.suffix.lower() not in valid_extensions:
            logger.debug(f"File {source} is not a text file, skipping")
            return False
        
        return True
    
    async def process(self, job: Job, ctx: ExecutionContext) -> StepResult:
        """Process the text file."""
        source_path = Path(job.source_path)
        
        logger.info(f"Processing text file: {source_path}")
        
        try:
            # Read the source file
            content = source_path.read_text(encoding="utf-8")
            
            # Build metadata header
            header_lines = [
                "=" * 60,
                f"PROCESSED BY: NoteFlow v2 - TextEcho",
                f"ORIGINAL FILE: {source_path.name}",
                f"ORIGINAL PATH: {source_path}",
            ]
            
            if self.add_timestamp:
                header_lines.append(f"PROCESSED AT: {datetime.now().isoformat()}")
            
            header_lines.extend([
                f"JOB ID: {job.id}",
                f"SOURCE TYPE: {job.source_type}",
                "=" * 60,
                "",
            ])
            
            header = "\n".join(header_lines)
            
            # Combine header and content
            processed_content = header + content
            
            # Generate output filename
            output_filename = f"{self.prefix}{source_path.name}"
            output_path = self.output_dir / output_filename
            
            # Write the processed file using context (for artifact tracking)
            await ctx.create_file(output_path, processed_content)
            
            # Store result information in job data
            job.data["echo_output_path"] = str(output_path)
            job.data["echo_original_size"] = len(content)
            job.data["echo_processed_size"] = len(processed_content)
            job.data["echo_lines_added"] = len(header_lines)
            
            logger.info(f"Created processed file: {output_path}")
            
            return StepResult(
                step_name=self.name,
                status=StepStatus.COMPLETED,
                message=f"Created {output_path}",
                output_data={
                    "output_path": str(output_path),
                    "original_size": len(content),
                    "processed_size": len(processed_content),
                },
            )
            
        except Exception as e:
            logger.error(f"Error processing file: {e}", exc_info=True)
            return StepResult(
                step_name=self.name,
                status=StepStatus.FAILED,
                message=str(e),
            )
    
    async def revert(self, job: Job, result: StepResult, ctx: ExecutionContext) -> bool:
        """Clean up after revert (artifacts are auto-reverted by context)."""
        # The file deletion is handled automatically by artifact revert
        # But we can clean up job data
        job.data.pop("echo_output_path", None)
        job.data.pop("echo_original_size", None)
        job.data.pop("echo_processed_size", None)
        job.data.pop("echo_lines_added", None)
        
        logger.info(f"Reverted text echo for job {job.id}")
        return True

