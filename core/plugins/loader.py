"""Plugin loader - discovers and loads processor plugins."""

from pathlib import Path
from typing import Optional, Any
import importlib.util
import sys
import yaml
import logging

from .base import Processor
from .registry import ProcessorRegistry

logger = logging.getLogger(__name__)


class PluginLoader:
    """
    Discovers and loads processor plugins from a directory.
    
    Plugin structure:
        plugins/
        ├── my_processor/
        │   ├── manifest.yaml     # Metadata and configuration
        │   ├── processor.py      # Processor implementation
        │   └── ui/               # Optional UI components
        │       └── Panel.tsx
    
    The manifest.yaml should contain:
        name: my_processor
        display_name: My Processor
        description: What this processor does
        version: 1.0.0
        requires:
          - other_processor
        config:
          option_name:
            type: string
            default: value
    """
    
    def __init__(self, plugins_dir: Path | str, registry: ProcessorRegistry):
        self.plugins_dir = Path(plugins_dir)
        self.registry = registry
        self._loaded_modules: dict[str, Any] = {}
    
    async def load_all(self) -> list[str]:
        """
        Load all plugins from the plugins directory.
        
        Returns:
            List of loaded plugin names
        """
        if not self.plugins_dir.exists():
            logger.warning(f"Plugins directory does not exist: {self.plugins_dir}")
            return []
        
        loaded = []
        
        for plugin_path in self.plugins_dir.iterdir():
            if not plugin_path.is_dir():
                continue
            
            if plugin_path.name.startswith("_") or plugin_path.name.startswith("."):
                continue
            
            try:
                processor = await self.load_plugin(plugin_path)
                if processor:
                    self.registry.register(processor)
                    loaded.append(processor.name)
            except Exception as e:
                logger.error(f"Failed to load plugin from {plugin_path}: {e}")
        
        # Validate dependencies after loading all plugins
        errors = self.registry.validate_dependencies()
        if errors:
            for error in errors:
                logger.warning(f"Dependency error: {error}")
        
        logger.info(f"Loaded {len(loaded)} plugins: {loaded}")
        return loaded
    
    async def load_plugin(self, plugin_path: Path) -> Optional[Processor]:
        """
        Load a single plugin from its directory.
        
        Args:
            plugin_path: Path to the plugin directory
        
        Returns:
            The loaded processor, or None if loading failed
        """
        manifest_path = plugin_path / "manifest.yaml"
        processor_path = plugin_path / "processor.py"
        
        # Load manifest
        manifest = self._load_manifest(manifest_path)
        if not manifest:
            # Try to load without manifest (use processor defaults)
            if not processor_path.exists():
                logger.warning(f"No processor.py found in {plugin_path}")
                return None
            manifest = {}
        
        # Load processor module
        if not processor_path.exists():
            logger.warning(f"No processor.py found in {plugin_path}")
            return None
        
        processor_class = self._load_processor_class(processor_path, manifest)
        if not processor_class:
            return None
        
        # Instantiate processor with config from manifest
        config = manifest.get("config", {})
        default_config = {}
        for key, schema in config.items():
            if "default" in schema:
                default_config[key] = schema["default"]
        
        try:
            processor = processor_class(config=default_config)
            
            # Override metadata from manifest if provided
            if "name" in manifest:
                processor.name = manifest["name"]
            if "display_name" in manifest:
                processor.display_name = manifest["display_name"]
            if "description" in manifest:
                processor.description = manifest["description"]
            if "version" in manifest:
                processor.version = manifest["version"]
            if "requires" in manifest:
                processor.requires = manifest["requires"]
            if "config" in manifest:
                processor.config_schema = manifest["config"]
            
            # UI configuration
            ui_config = manifest.get("ui", {})
            if ui_config.get("has_panel"):
                processor.has_ui = True
            if "requires_input" in ui_config:
                processor.requires_input = ui_config["requires_input"]
            
            # Call on_load hook
            await processor.on_load()
            
            logger.info(f"Loaded plugin: {processor.name} v{processor.version}")
            return processor
            
        except Exception as e:
            logger.error(f"Error instantiating processor from {plugin_path}: {e}")
            return None
    
    def _load_manifest(self, manifest_path: Path) -> Optional[dict]:
        """Load and parse the manifest.yaml file."""
        if not manifest_path.exists():
            return None
        
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f)
        except Exception as e:
            logger.error(f"Error loading manifest from {manifest_path}: {e}")
            return None
    
    def _load_processor_class(
        self,
        processor_path: Path,
        manifest: dict,
    ) -> Optional[type[Processor]]:
        """Load the processor class from processor.py."""
        module_name = f"noteflow_plugin_{processor_path.parent.name}"
        
        try:
            # Load module
            spec = importlib.util.spec_from_file_location(module_name, processor_path)
            if spec is None or spec.loader is None:
                logger.error(f"Could not load spec for {processor_path}")
                return None
            
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            
            self._loaded_modules[module_name] = module
            
            # Find the processor class
            processor_class = None
            
            # Look for a class specified in manifest
            class_name = manifest.get("processor_class")
            if class_name and hasattr(module, class_name):
                processor_class = getattr(module, class_name)
            
            # Otherwise, find the first Processor subclass
            if processor_class is None:
                for name in dir(module):
                    obj = getattr(module, name)
                    if (
                        isinstance(obj, type)
                        and issubclass(obj, Processor)
                        and obj is not Processor
                    ):
                        processor_class = obj
                        break
            
            if processor_class is None:
                logger.error(f"No Processor subclass found in {processor_path}")
                return None
            
            return processor_class
            
        except Exception as e:
            logger.error(f"Error loading processor module from {processor_path}: {e}")
            return None
    
    async def unload_plugin(self, name: str) -> bool:
        """
        Unload a plugin.
        
        Args:
            name: Plugin name
        
        Returns:
            True if unloaded successfully
        """
        processor = self.registry.unregister(name)
        if processor:
            try:
                await processor.on_unload()
            except Exception as e:
                logger.error(f"Error calling on_unload for {name}: {e}")
            
            # Clean up module from sys.modules
            module_name = f"noteflow_plugin_{name}"
            if module_name in sys.modules:
                del sys.modules[module_name]
            if module_name in self._loaded_modules:
                del self._loaded_modules[module_name]
            
            logger.info(f"Unloaded plugin: {name}")
            return True
        
        return False
    
    async def reload_plugin(self, name: str) -> Optional[Processor]:
        """
        Reload a plugin (unload and load again).
        
        Args:
            name: Plugin name
        
        Returns:
            The reloaded processor, or None if failed
        """
        # Find plugin path
        plugin_path = self.plugins_dir / name
        if not plugin_path.exists():
            logger.error(f"Plugin directory not found: {plugin_path}")
            return None
        
        # Unload
        await self.unload_plugin(name)
        
        # Load again
        processor = await self.load_plugin(plugin_path)
        if processor:
            self.registry.register(processor)
        
        return processor
    
    def get_plugin_ui_path(self, name: str) -> Optional[Path]:
        """
        Get the UI directory path for a plugin.
        
        Args:
            name: Plugin name
        
        Returns:
            Path to the UI directory, or None if not found
        """
        ui_path = self.plugins_dir / name / "ui"
        if ui_path.exists():
            return ui_path
        return None

