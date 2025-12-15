"""Plugin system for NoteFlow v2."""

from .base import Processor
from .loader import PluginLoader
from .registry import ProcessorRegistry

__all__ = ["Processor", "PluginLoader", "ProcessorRegistry"]

