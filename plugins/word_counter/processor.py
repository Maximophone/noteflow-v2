"""
Word Counter Processor

A processor that:
1. Reads the processed file from the previous step
2. Counts words, lines, and characters
3. Stores statistics in job data
4. Creates a stats file as output
"""

import logging
import re
import json
from pathlib import Path
from datetime import datetime
from collections import Counter
from typing import Optional

from core.plugins.base import Processor
from core.models import Job, StepResult, StepStatus
from core.engine.context import ExecutionContext

logger = logging.getLogger(__name__)


class WordCounterProcessor(Processor):
    """Counts words and generates statistics."""
    
    name = "word_counter"
    display_name = "Word Counter"
    description = "Analyzes text files and counts words, lines, and characters"
    version = "1.0.0"
    
    requires = ["text_echo"]  # Runs after text_echo
    has_ui = False
    requires_input = "never"
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        self.count_unique = self.config.get("count_unique_words", True)
        self.stats_dir = Path("data/stats")
        self.stats_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"WordCounter initialized: count_unique={self.count_unique}")
    
    async def should_process(self, job: Job) -> bool:
        """Process if we have an echo output path."""
        echo_output = job.data.get("echo_output_path")
        if not echo_output:
            logger.debug(f"Job {job.id} has no echo_output_path, skipping")
            return False
        
        if not Path(echo_output).exists():
            logger.warning(f"Echo output file does not exist: {echo_output}")
            return False
        
        return True
    
    async def process(self, job: Job, ctx: ExecutionContext) -> StepResult:
        """Count words and generate statistics."""
        echo_output = Path(job.data["echo_output_path"])
        
        logger.info(f"Counting words in: {echo_output}")
        
        try:
            # Read the file
            content = echo_output.read_text(encoding="utf-8")
            
            # Calculate statistics
            lines = content.split("\n")
            words = re.findall(r'\b\w+\b', content.lower())
            
            stats = {
                "file": str(echo_output),
                "analyzed_at": datetime.now().isoformat(),
                "job_id": job.id,
                "line_count": len(lines),
                "word_count": len(words),
                "char_count": len(content),
                "char_count_no_spaces": len(content.replace(" ", "").replace("\n", "")),
                "avg_word_length": round(sum(len(w) for w in words) / len(words), 2) if words else 0,
                "avg_words_per_line": round(len(words) / len(lines), 2) if lines else 0,
            }
            
            if self.count_unique:
                word_freq = Counter(words)
                stats["unique_word_count"] = len(word_freq)
                stats["top_10_words"] = dict(word_freq.most_common(10))
            
            # Create stats output file
            stats_filename = f"stats_{echo_output.stem}_{job.id[:8]}.json"
            stats_path = self.stats_dir / stats_filename
            
            await ctx.create_file(stats_path, json.dumps(stats, indent=2))
            
            # Store stats in job data
            job.data["word_count_stats"] = stats
            job.data["word_count_stats_path"] = str(stats_path)
            
            logger.info(f"Created stats file: {stats_path}")
            logger.info(f"Stats: {stats['word_count']} words, {stats['line_count']} lines")
            
            return StepResult(
                step_name=self.name,
                status=StepStatus.COMPLETED,
                message=f"Counted {stats['word_count']} words in {stats['line_count']} lines",
                output_data=stats,
            )
            
        except Exception as e:
            logger.error(f"Error counting words: {e}", exc_info=True)
            return StepResult(
                step_name=self.name,
                status=StepStatus.FAILED,
                message=str(e),
            )
    
    async def revert(self, job: Job, result: StepResult, ctx: ExecutionContext) -> bool:
        """Clean up after revert."""
        job.data.pop("word_count_stats", None)
        job.data.pop("word_count_stats_path", None)
        logger.info(f"Reverted word counter for job {job.id}")
        return True

