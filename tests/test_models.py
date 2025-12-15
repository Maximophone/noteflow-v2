"""Tests for data models."""

import pytest
from datetime import datetime

from core.models import (
    Job, JobStatus,
    Artifact, ArtifactType, ArtifactStatus,
    StepResult, StepStatus,
)


class TestJob:
    """Tests for the Job model."""
    
    def test_create_job(self):
        """Test creating a new job."""
        job = Job(
            source_type="file",
            source_name="test.mp3",
            source_path="/path/to/test.mp3",
        )
        
        assert job.id is not None
        assert job.source_type == "file"
        assert job.source_name == "test.mp3"
        assert job.status == JobStatus.PENDING
        assert job.created_at is not None
    
    def test_job_state_transitions(self):
        """Test job state transitions."""
        job = Job(source_type="test", source_name="test")
        
        # Start processing
        job.start_processing("step1")
        assert job.status == JobStatus.PROCESSING
        assert job.current_step == "step1"
        assert job.started_at is not None
        
        # Complete
        job.complete()
        assert job.status == JobStatus.COMPLETED
        assert job.completed_at is not None
    
    def test_job_data_management(self):
        """Test job data context."""
        job = Job(source_type="test", source_name="test")
        
        job.set_data("key1", "value1")
        assert job.get_data("key1") == "value1"
        assert job.get_data("missing", "default") == "default"
        
        job.merge_data({"key2": "value2", "key3": "value3"})
        assert job.get_data("key2") == "value2"
    
    def test_job_history(self):
        """Test job history management."""
        job = Job(source_type="test", source_name="test")
        
        result1 = StepResult(job_id=job.id, step_name="step1")
        result1.complete()
        job.add_step_result(result1)
        
        assert len(job.history) == 1
        assert job.has_completed_step("step1")
        assert not job.has_completed_step("step2")
        assert job.get_completed_steps() == ["step1"]


class TestArtifact:
    """Tests for the Artifact model."""
    
    def test_create_artifact(self):
        """Test creating an artifact."""
        artifact = Artifact(
            job_id="job123",
            step_name="step1",
            artifact_type=ArtifactType.FILE_CREATE,
            target="/path/to/file.txt",
            after_state="file content",
        )
        
        assert artifact.id is not None
        assert artifact.job_id == "job123"
        assert artifact.artifact_type == ArtifactType.FILE_CREATE
        assert artifact.status == ArtifactStatus.PENDING
    
    def test_artifact_status_transitions(self):
        """Test artifact status transitions."""
        artifact = Artifact(
            job_id="job123",
            step_name="step1",
            artifact_type=ArtifactType.FILE_CREATE,
            target="/path/to/file.txt",
        )
        
        artifact.mark_created()
        assert artifact.status == ArtifactStatus.CREATED
        assert artifact.can_revert
        
        artifact.mark_reverted()
        assert artifact.status == ArtifactStatus.REVERTED
        assert artifact.reverted_at is not None
    
    def test_irreversible_artifact(self):
        """Test marking an artifact as irreversible."""
        artifact = Artifact(
            job_id="job123",
            step_name="step1",
            artifact_type=ArtifactType.EXTERNAL_API_CREATE,
            target="notion:create_page",
        )
        artifact.mark_created()
        
        artifact.mark_irreversible("Cannot undo Notion page creation")
        
        assert artifact.status == ArtifactStatus.IRREVERSIBLE
        assert not artifact.can_revert


class TestStepResult:
    """Tests for the StepResult model."""
    
    def test_create_step_result(self):
        """Test creating a step result."""
        result = StepResult(job_id="job123", step_name="step1")
        
        assert result.id is not None
        assert result.job_id == "job123"
        assert result.step_name == "step1"
        assert result.status == StepStatus.PENDING
    
    def test_step_lifecycle(self):
        """Test step result lifecycle."""
        result = StepResult(job_id="job123", step_name="step1")
        
        result.start()
        assert result.status == StepStatus.RUNNING
        assert result.started_at is not None
        
        result.complete({"output": "value"})
        assert result.status == StepStatus.COMPLETED
        assert result.completed_at is not None
        assert result.output_data == {"output": "value"}
        assert result.duration_seconds is not None
    
    def test_step_failure(self):
        """Test step failure."""
        result = StepResult(job_id="job123", step_name="step1")
        result.start()
        
        result.fail("Something went wrong", "traceback...")
        
        assert result.status == StepStatus.FAILED
        assert result.error_message == "Something went wrong"
        assert result.error_traceback == "traceback..."
    
    def test_step_awaiting_input(self):
        """Test step waiting for user input."""
        result = StepResult(job_id="job123", step_name="step1")
        result.start()
        
        result.await_input()
        assert result.status == StepStatus.AWAITING_INPUT
        assert result.awaiting_input_since is not None
        
        result.provide_input({"user_choice": "option1"})
        assert result.status == StepStatus.RUNNING
        assert result.user_input == {"user_choice": "option1"}

