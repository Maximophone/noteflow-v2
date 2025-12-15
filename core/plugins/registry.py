"""Processor registry - central registry for all loaded processors."""

from typing import Optional
import logging

from .base import Processor
from ..models import StepDefinition

logger = logging.getLogger(__name__)


class ProcessorRegistry:
    """
    Central registry for all loaded processors.
    
    Provides lookup by name and dependency resolution.
    """
    
    def __init__(self):
        self._processors: dict[str, Processor] = {}
        self._definitions: dict[str, StepDefinition] = {}
    
    def register(self, processor: Processor) -> None:
        """
        Register a processor.
        
        Args:
            processor: The processor to register
        
        Raises:
            ValueError: If a processor with the same name is already registered
        """
        if not processor.name:
            raise ValueError(f"Processor {processor.__class__.__name__} has no name")
        
        if processor.name in self._processors:
            raise ValueError(f"Processor '{processor.name}' is already registered")
        
        self._processors[processor.name] = processor
        self._definitions[processor.name] = processor.to_definition()
        
        logger.info(f"Registered processor: {processor.name}")
    
    def unregister(self, name: str) -> Optional[Processor]:
        """
        Unregister a processor.
        
        Args:
            name: Name of the processor to unregister
        
        Returns:
            The unregistered processor, or None if not found
        """
        processor = self._processors.pop(name, None)
        self._definitions.pop(name, None)
        
        if processor:
            logger.info(f"Unregistered processor: {name}")
        
        return processor
    
    def get(self, name: str) -> Optional[Processor]:
        """
        Get a processor by name.
        
        Args:
            name: Processor name
        
        Returns:
            The processor, or None if not found
        """
        return self._processors.get(name)
    
    def get_definition(self, name: str) -> Optional[StepDefinition]:
        """
        Get a step definition by processor name.
        
        Args:
            name: Processor name
        
        Returns:
            The step definition, or None if not found
        """
        return self._definitions.get(name)
    
    def get_all(self) -> list[Processor]:
        """Get all registered processors."""
        return list(self._processors.values())
    
    def get_all_definitions(self) -> list[StepDefinition]:
        """Get all step definitions."""
        return list(self._definitions.values())
    
    def get_names(self) -> list[str]:
        """Get names of all registered processors."""
        return list(self._processors.keys())
    
    def has(self, name: str) -> bool:
        """Check if a processor is registered."""
        return name in self._processors
    
    def clear(self) -> None:
        """Clear all registered processors."""
        self._processors.clear()
        self._definitions.clear()
        logger.info("Cleared all processors from registry")
    
    # -------------------------------------------------------------------------
    # Dependency resolution
    # -------------------------------------------------------------------------
    
    def get_dependencies(self, name: str) -> list[str]:
        """
        Get direct dependencies of a processor.
        
        Args:
            name: Processor name
        
        Returns:
            List of processor names this processor depends on
        """
        processor = self.get(name)
        if processor:
            return processor.requires.copy()
        return []
    
    def get_all_dependencies(self, name: str) -> list[str]:
        """
        Get all dependencies of a processor (recursive).
        
        Args:
            name: Processor name
        
        Returns:
            Ordered list of all dependencies (topological order)
        """
        visited = set()
        result = []
        
        def visit(n: str):
            if n in visited:
                return
            visited.add(n)
            
            for dep in self.get_dependencies(n):
                visit(dep)
            
            result.append(n)
        
        visit(name)
        
        # Remove the processor itself from the list
        if name in result:
            result.remove(name)
        
        return result
    
    def get_dependents(self, name: str) -> list[str]:
        """
        Get processors that depend on the given processor.
        
        Args:
            name: Processor name
        
        Returns:
            List of processor names that depend on this one
        """
        dependents = []
        for proc_name, processor in self._processors.items():
            if name in processor.requires:
                dependents.append(proc_name)
        return dependents
    
    def get_execution_order(self, processors: list[str]) -> list[str]:
        """
        Get the execution order for a set of processors.
        
        Performs topological sort based on dependencies.
        
        Args:
            processors: List of processor names
        
        Returns:
            Ordered list respecting dependencies
        
        Raises:
            ValueError: If there's a circular dependency
        """
        # Build dependency graph
        in_degree = {p: 0 for p in processors}
        graph = {p: [] for p in processors}
        
        for proc in processors:
            for dep in self.get_dependencies(proc):
                if dep in processors:
                    graph[dep].append(proc)
                    in_degree[proc] += 1
        
        # Kahn's algorithm
        queue = [p for p in processors if in_degree[p] == 0]
        result = []
        
        while queue:
            node = queue.pop(0)
            result.append(node)
            
            for dependent in graph[node]:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)
        
        if len(result) != len(processors):
            # Circular dependency detected
            remaining = [p for p in processors if p not in result]
            raise ValueError(f"Circular dependency detected involving: {remaining}")
        
        return result
    
    def validate_dependencies(self) -> list[str]:
        """
        Validate that all processor dependencies exist.
        
        Returns:
            List of error messages (empty if all valid)
        """
        errors = []
        
        for name, processor in self._processors.items():
            for dep in processor.requires:
                if dep not in self._processors:
                    errors.append(
                        f"Processor '{name}' depends on '{dep}' which is not registered"
                    )
        
        return errors
    
    def __len__(self) -> int:
        return len(self._processors)
    
    def __contains__(self, name: str) -> bool:
        return name in self._processors
    
    def __iter__(self):
        return iter(self._processors.values())

