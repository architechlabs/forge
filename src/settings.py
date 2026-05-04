import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppOptions:
    log_level: str = "info"
    poll_interval: int = 15
    allow_config_writes: bool = True
    package_name: str = "entity_bridge"
    max_entities_per_import: int = 500


def load_options() -> AppOptions:
    path = Path(os.environ.get("OPTIONS_PATH", "/data/options.json"))
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    return AppOptions(
        log_level=str(data.get("log_level", "info")),
        poll_interval=int(data.get("poll_interval", 15)),
        allow_config_writes=bool(data.get("allow_config_writes", True)),
        package_name=str(data.get("package_name", "entity_bridge")),
        max_entities_per_import=int(data.get("max_entities_per_import", 500)),
    )


DATA_PATH = Path(os.environ.get("DATA_PATH", "/data"))
HA_CONFIG_PATH = Path(os.environ.get("HA_CONFIG_PATH", "/homeassistant"))
ADDON_CONFIG_PATH = Path(os.environ.get("ADDON_CONFIG_PATH", "/config"))
