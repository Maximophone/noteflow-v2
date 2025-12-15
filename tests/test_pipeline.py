"""Tests for the pipeline engine."""

import pytest
import asyncio
import tempfile
from pathlib import Path

from core.models import Job, JobStatus, StepResult, StepStatus
from core.storage import Database, JobStore, ArtifactStore
from core.plugins import Processor, ProcessorRegistry
from core.engine import ExecutionContext, Router, JobExecutor, Pipeline


# -------------------------------------------------------------------------
# Test Fixtures
# -------------------------------------------------------------------------

@pytest.fixture
async def temp_db():
    """Create a temporary database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = Database(db_path)
        await db.connect()
        yield db
        await db.close()


@pytest.fixture
async def stores(temp_db):
    """Create job and artifact stores."""
    job_store = JobStore(temp_db)
    artifact_store = ArtifactStore(temp_db)
    return job_store, artifact_store


# -------------------------------------------------------------------------
# Test Processors
# -------------------------------------------------------------------------

class TestProcessor1(Processor):
    """A simple test processor."""
    
    name = "test_step1"
    display_name = "Test Step 1"
    requires = []
    
    async def should_process(self, job: Job) -> bool:
        return True
    
    async def process(self, job: Job, ctx: ExecutionContext) -> StepResult:
        result = StepResult(job_id=job.id, step_name=self.name)
        result.complete({"step1_done": True})
        return result
    
    async def revert(self, job: Job, step_result: StepResult, ctx: ExecutionContext) -> bool:
        return True


class TestProcessor2(Processor):
    """A processor that depends on TestProcessor1."""
    
    name = "test_step2"
    display_name = "Test Step 2"
    requires = ["test_step1"]
    
    async def should_process(self, job: Job) -> bool:
        return True
    
    async def process(self, job: Job, ctx: ExecutionContext) -> StepResult:
        result = StepResult(job_id=job.id, step_name=self.name)
        result.complete({"step2_done": True})
        return result
    
    async def revert(self, job: Job, step_result: StepResult, ctx: ExecutionContext) -> bool:
        return True


class HumanInLoopProcessor(Processor):
    """A processor that requires user input."""
    
    name = "human_step"
    display_name = "Human Step"
    requires = []
    requires_input = "always"
    
    async def should_process(self, job: Job) -> bool:
        return job.get_data("needs_human", False)
    
    async def process(self, job: Job, ctx: ExecutionContext) -> StepResult:
        result = StepResult(job_id=job.id, step_name=self.name)
        user_input = job.get_data("user_input")
        if user_input:
            result.complete({"human_input": user_input})
        else:
            result.await_input()
        return result
    
    async def revert(self, job: Job, step_result: StepResult, ctx: ExecutionContext) -> bool:
        return True


# -------------------------------------------------------------------------
# Tests
# -------------------------------------------------------------------------

class TestProcessorRegistry:
    """Tests for the processor registry."""
    
    def test_register_processor(self):
        """Test registering a processor."""
        registry = ProcessorRegistry()
        processor = TestProcessor1()
        
        registry.register(processor)
        
        assert registry.has("test_step1")
        assert registry.get("test_step1") is processor
    
    def test_dependency_order(self):
        """Test getting execution order based on dependencies."""
        registry = ProcessorRegistry()
        registry.register(TestProcessor1())
        registry.register(TestProcessor2())
        
        order = registry.get_execution_order(["test_step1", "test_step2"])
        
        assert order == ["test_step1", "test_step2"]
    
    def test_circular_dependency_detection(self):
        """Test that circular dependencies are detected."""
        # Create processors with circular dependency
        class CircularA(Processor):
            name = "circular_a"
            requires = ["circular_b"]
            async def should_process(self, job): return True
            async def process(self, job, ctx): pass
            async def revert(self, job, result, ctx): return True
        
        class CircularB(Processor):
            name = "circular_b"
            requires = ["circular_a"]
            async def should_process(self, job): return True
            async def process(self, job, ctx): pass
            async def revert(self, job, result, ctx): return True
        
        registry = ProcessorRegistry()
        registry.register(CircularA())
        registry.register(CircularB())
        
        with pytest.raises(ValueError, match="Circular dependency"):
            registry.get_execution_order(["circular_a", "circular_b"])


class TestRouter:
    """Tests for the pipeline router."""
    
    @pytest.fixture
    def registry(self):
        reg = ProcessorRegistry()
        reg.register(TestProcessor1())
        reg.register(TestProcessor2())
        return reg
    
    @pytest.mark.asyncio
    async def test_get_next_step(self, registry):
        """Test getting the next step for a job."""
        router = Router(registry)
        job = Job(source_type="test", source_name="test")
        
        # First step should be test_step1 (no dependencies)
        next_step = await router.get_next_step(job)
        assert next_step == "test_step1"
    
    @pytest.mark.asyncio
    async def test_respects_dependencies(self, registry):
        """Test that router respects dependencies."""
        router = Router(registry)
        job = Job(source_type="test", source_name="test")
        
        # Manually mark step1 as complete
        result = StepResult(job_id=job.id, step_name="test_step1")
        result.complete()
        job.add_step_result(result)
        
        # Next step should be test_step2
        next_step = await router.get_next_step(job)
        assert next_step == "test_step2"


class TestJobStore:
    """Tests for the job store."""
    
    @pytest.mark.asyncio
    async def test_save_and_get(self, stores):
        """Test saving and retrieving a job."""
        job_store, _ = stores
        
        job = Job(source_type="test", source_name="test job")
        await job_store.save(job)
        
        retrieved = await job_store.get(job.id)
        assert retrieved is not None
        assert retrieved.id == job.id
        assert retrieved.source_name == "test job"
    
    @pytest.mark.asyncio
    async def test_list_pending(self, stores):
        """Test listing pending jobs."""
        job_store, _ = stores
        
        job1 = Job(source_type="test", source_name="job1", priority=1)
        job2 = Job(source_type="test", source_name="job2", priority=2)
        await job_store.save(job1)
        await job_store.save(job2)
        
        pending = await job_store.list_pending()
        
        assert len(pending) == 2
        # Higher priority should come first
        assert pending[0].source_name == "job2"


class TestExecutionContext:
    """Tests for the execution context."""
    
    @pytest.mark.asyncio
    async def test_create_file(self, stores):
        """Test creating a file through the context."""
        _, artifact_store = stores
        job = Job(source_type="test", source_name="test")
        
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.txt"
            
            ctx = ExecutionContext(job, "test_step", artifact_store)
            artifact = await ctx.create_file(file_path, "Hello, World!")
            await ctx.commit()
            
            assert file_path.exists()
            assert file_path.read_text() == "Hello, World!"
            assert artifact.target == str(file_path)
    
    @pytest.mark.asyncio
    async def test_rollback_on_error(self, stores):
        """Test that context rolls back on error."""
        _, artifact_store = stores
        job = Job(source_type="test", source_name="test")
        
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.txt"
            
            try:
                async with ExecutionContext(job, "test_step", artifact_store) as ctx:
                    await ctx.create_file(file_path, "Hello, World!")
                    raise ValueError("Simulated error")
            except ValueError:
                pass
            
            # File should be deleted on rollback
            assert not file_path.exists()

