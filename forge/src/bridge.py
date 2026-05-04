import hashlib
import re
from pathlib import Path
from typing import Any

import yaml

from .ha_client import HomeAssistantClient, HomeAssistantError
from .settings import AppOptions
from .store import JsonStore, utc_now


UNKNOWN_STATES = {"unknown", "unavailable", None, ""}
BOOLEAN_DOMAINS = {
    "automation",
    "binary_sensor",
    "fan",
    "humidifier",
    "input_boolean",
    "light",
    "lock",
    "remote",
    "siren",
    "switch",
}
NUMERIC_DOMAINS = {"number", "input_number"}
SELECT_DOMAINS = {"select", "input_select"}
TEXT_DOMAINS = {"sensor", "text", "input_text"}
BUTTON_DOMAINS = {"button", "input_button"}
IGNORED_DOMAINS = {"zone", "sun", "weather", "camera", "update", "conversation"}
SAFE_ATTRIBUTE_KEYS = {
    "device_class",
    "friendly_name",
    "icon",
    "max",
    "min",
    "mode",
    "options",
    "state_class",
    "step",
    "unit_of_measurement",
}
WRITABLE_DOMAINS = {
    "automation",
    "cover",
    "fan",
    "humidifier",
    "input_boolean",
    "input_number",
    "input_select",
    "light",
    "lock",
    "number",
    "remote",
    "select",
    "siren",
    "switch",
}

INTEGRATION_LABELS = {
    "knx": "KNX",
    "wiz": "WiZ",
    "zha": "Zigbee Home Automation",
    "zwave_js": "Z-Wave JS",
    "mqtt": "MQTT",
    "hue": "Philips Hue",
    "esphome": "ESPHome",
    "shelly": "Shelly",
    "matter": "Matter",
    "tuya": "Tuya",
    "homekit_controller": "HomeKit Controller",
    "mobile_app": "Mobile App",
    "template": "Template",
    "group": "Group",
    "input_boolean": "Input Boolean",
    "input_number": "Input Number",
    "input_text": "Input Text",
    "input_select": "Input Select",
    "input_button": "Input Button",
}


def slugify(value: str, max_len: int = 64) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9_]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    if not value:
        value = "entity"
    return value[:max_len].rstrip("_") or "entity"


def friendly_name(entity: dict[str, Any]) -> str:
    attrs = entity.get("attributes") or {}
    return str(attrs.get("friendly_name") or entity.get("entity_id") or "Imported entity")


def safe_attributes(attributes: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in attributes.items():
        if key not in SAFE_ATTRIBUTE_KEYS:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            cleaned[key] = value
        elif isinstance(value, list):
            cleaned[key] = [str(item)[:255] for item in value[:200]]
    return cleaned


def domain_of(entity_id: str) -> str:
    return entity_id.split(".", 1)[0] if "." in entity_id else "unknown"


def is_numeric_state(entity: dict[str, Any]) -> bool:
    state = entity.get("state")
    if state in UNKNOWN_STATES:
        return False
    try:
        float(state)
        return True
    except (TypeError, ValueError):
        return False


def helper_domain_for(entity: dict[str, Any]) -> str:
    domain = domain_of(entity.get("entity_id", ""))
    if domain in BUTTON_DOMAINS:
        return "input_button"
    if domain in SELECT_DOMAINS:
        return "input_select"
    if domain in NUMERIC_DOMAINS or (domain == "sensor" and is_numeric_state(entity)):
        return "input_number"
    if domain in BOOLEAN_DOMAINS:
        return "input_boolean"
    return "input_text"


def infer_platform(entity_id: str, registry: dict[str, Any] | None) -> str:
    if registry and registry.get("platform"):
        return str(registry["platform"])
    domain = domain_of(entity_id)
    if domain.startswith("input_"):
        return domain
    return domain


def integration_label(platform: str) -> str:
    return INTEGRATION_LABELS.get(platform, platform.replace("_", " ").title())


def build_capability_note(domain: str, helper_domain: str, platform: str) -> str:
    if platform in {"input_boolean", "input_number", "input_text", "input_select", "input_button"}:
        return "Can be recreated as a matching Home Assistant helper."
    if domain in {"switch", "light", "fan", "lock", "cover", "number", "select"}:
        return "Imported as a managed proxy helper; native behavior needs the source integration configured on this instance."
    if domain == "sensor":
        return "Imported as a managed mirror helper; native sensor history and device metadata need the source integration."
    if helper_domain == "input_text":
        return "Imported as a text mirror; complex device behavior remains on the source instance."
    return "Imported as a managed helper entity."


async def scan_home_assistant(client: HomeAssistantClient) -> dict[str, Any]:
    states = await client.get_states()
    registries: dict[str, Any] = {"entities": {}, "devices": {}, "areas": {}}
    for command, key in (
        ("config/entity_registry/list", "entities"),
        ("config/device_registry/list", "devices"),
        ("config/area_registry/list", "areas"),
    ):
        try:
            result = await client.websocket_command(command)
        except Exception:
            result = []
        if key == "entities":
            registries[key] = {item.get("entity_id"): item for item in result or []}
        else:
            registries[key] = {item.get("id"): item for item in result or []}

    enriched = []
    for entity in states:
        entity_id = entity.get("entity_id", "")
        domain = domain_of(entity_id)
        registry = registries["entities"].get(entity_id)
        platform = infer_platform(entity_id, registry)
        helper_domain = helper_domain_for(entity)
        device = registries["devices"].get((registry or {}).get("device_id"))
        area_id = (registry or {}).get("area_id") or (device or {}).get("area_id")
        area = registries["areas"].get(area_id)
        enriched.append(
            {
                "entity_id": entity_id,
                "domain": domain,
                "state": entity.get("state"),
                "attributes": safe_attributes(entity.get("attributes") or {}),
                "name": friendly_name(entity),
                "platform": platform,
                "integration_label": integration_label(platform),
                "helper_domain": helper_domain,
                "device_id": (registry or {}).get("device_id"),
                "device_name": (device or {}).get("name_by_user")
                or (device or {}).get("name")
                or (device or {}).get("model"),
                "area_id": area_id,
                "area_name": (area or {}).get("name"),
                "disabled_by": (registry or {}).get("disabled_by"),
                "hidden_by": (registry or {}).get("hidden_by"),
                "capability_note": build_capability_note(domain, helper_domain, platform),
                "native_required": platform not in {"input_boolean", "input_number", "input_text", "input_select", "input_button"},
            }
        )
    platforms = sorted({item["platform"] for item in enriched if item.get("platform")})
    return {
        "scanned_at": utc_now(),
        "entities": enriched,
        "platforms": platforms,
        "counts": {
            "entities": len(enriched),
            "platforms": len(platforms),
        },
    }


async def current_platforms(current: HomeAssistantClient) -> set[str]:
    platforms: set[str] = set()
    for command, key in (
        ("config/entity_registry/list", "platform"),
        ("config/config_entries/list", "domain"),
    ):
        try:
            result = await current.websocket_command(command)
        except Exception:
            continue
        platforms.update(str(item.get(key)) for item in result or [] if item.get(key))
    return platforms


def build_import_plan(
    store: JsonStore,
    current_states: list[dict[str, Any]],
    instance_ids: list[str],
    entity_ids: list[str] | None,
    entity_refs: list[str] | None,
    prefix: str,
    conflict_policy: str,
    target_platforms: set[str] | None = None,
) -> dict[str, Any]:
    existing_entity_ids = {item.get("entity_id") for item in current_states}
    existing_object_ids = {item.split(".", 1)[1] for item in existing_entity_ids if isinstance(item, str) and "." in item}
    current_platforms_snapshot = target_platforms or set()
    current_platforms_snapshot.update({"input_boolean", "input_number", "input_text", "input_select", "input_button"})
    rows = []
    native_requirements: dict[str, int] = {}
    selected = set(entity_ids or [])
    selected_refs = set(entity_refs or [])

    for instance_id in instance_ids:
        instance = store.get_instance(instance_id)
        snapshot = store.data.get("snapshots", {}).get(instance_id) or {}
        if not instance or not snapshot:
            continue
        instance_slug = slugify(instance.get("name") or instance.get("url") or instance_id, 24)
        for entity in snapshot.get("entities", []):
            entity_ref = f"{instance_id}::{entity['entity_id']}"
            if selected_refs and entity_ref not in selected_refs:
                continue
            if selected and not selected_refs and entity["entity_id"] not in selected:
                continue
            if entity["domain"] in IGNORED_DOMAINS:
                continue
            helper_domain = entity["helper_domain"]
            base = slugify(f"{prefix}_{instance_slug}_{entity['entity_id'].replace('.', '_')}", 56)
            object_id = base
            conflict = None
            if f"{helper_domain}.{object_id}" in existing_entity_ids or object_id in existing_object_ids:
                existing_map = store.find_map(instance_id, entity["entity_id"])
                if existing_map:
                    object_id = existing_map["object_id"]
                    conflict = "update"
                elif conflict_policy == "skip":
                    conflict = "skip"
                else:
                    suffix = 2
                    while f"{helper_domain}.{object_id}_{suffix}" in existing_entity_ids or f"{object_id}_{suffix}" in existing_object_ids:
                        suffix += 1
                    object_id = f"{object_id}_{suffix}"
                    conflict = "rename"
            platform = entity.get("platform") or entity["domain"]
            if entity.get("native_required", True):
                native_requirements[platform] = native_requirements.get(platform, 0) + 1
            rows.append(
                {
                    "source_instance_id": instance_id,
                    "source_instance_name": instance.get("name"),
                    "source_entity_id": entity["entity_id"],
                    "source_domain": entity["domain"],
                    "name": entity["name"],
                    "state": entity.get("state"),
                    "helper_domain": helper_domain,
                    "object_id": object_id,
                    "local_entity_id": f"{helper_domain}.{object_id}",
                    "platform": platform,
                    "integration_label": integration_label(platform),
                    "native_required": entity.get("native_required", True),
                    "capability_note": entity.get("capability_note"),
                    "conflict": conflict,
                    "status": "skip" if conflict == "skip" else "ready",
                }
            )
            if conflict != "skip":
                existing_entity_ids.add(f"{helper_domain}.{object_id}")
                existing_object_ids.add(object_id)
    return {
        "created_at": utc_now(),
        "count": len(rows),
        "rows": rows,
        "native_requirements": [
            {
                "platform": platform,
                "name": integration_label(platform),
                "count": count,
                "available_on_target": platform in current_platforms_snapshot,
            }
            for platform, count in sorted(native_requirements.items(), key=lambda item: (-item[1], item[0]))
        ],
    }


def _helper_config(mapping: dict[str, Any]) -> dict[str, Any]:
    attrs = mapping.get("source_attributes") or {}
    config: dict[str, Any] = {
        "name": mapping.get("name") or mapping.get("source_entity_id"),
    }
    icon = attrs.get("icon")
    if icon:
        config["icon"] = icon
    local_domain = mapping["local_domain"]
    if local_domain == "input_number":
        min_value = attrs.get("min", -1000000)
        max_value = attrs.get("max", 1000000)
        step = attrs.get("step", 0.01)
        try:
            min_value = float(min_value)
            max_value = float(max_value)
            step = float(step)
        except (TypeError, ValueError):
            min_value = -1000000
            max_value = 1000000
            step = 0.01
        if min_value >= max_value:
            min_value = -1000000
            max_value = 1000000
        if step <= 0:
            step = 0.01
        config.update(
            {
                "min": min_value,
                "max": max_value,
                "step": step,
                "mode": "box",
            }
        )
        if attrs.get("unit_of_measurement"):
            config["unit_of_measurement"] = str(attrs["unit_of_measurement"])[:32]
    elif local_domain == "input_text":
        config["max"] = 255
    elif local_domain == "input_select":
        options = attrs.get("options")
        if not isinstance(options, list):
            options = []
        state = mapping.get("last_source_state")
        merged = []
        for option in [state, *options, "unavailable"]:
            if option is None:
                continue
            value = str(option)[:255]
            if value and value not in merged:
                merged.append(value)
        config["options"] = merged[:200] or ["unavailable"]
    return config


def render_package(entity_maps: list[dict[str, Any]]) -> str:
    sections: dict[str, dict[str, Any]] = {}
    for mapping in sorted(entity_maps, key=lambda item: item.get("local_entity_id", "")):
        domain = mapping["local_domain"]
        sections.setdefault(domain, {})[mapping["object_id"]] = _helper_config(mapping)
    header = [
        "# Managed by the Forge add-on.",
        "# Edit imports in the add-on UI; manual changes can be overwritten.",
        "",
    ]
    body = yaml.safe_dump(sections or {}, sort_keys=True, allow_unicode=False)
    return "\n".join(header) + body


def ensure_packages_enabled(config_path: Path, package_name: str) -> dict[str, Any]:
    result = {"changed": False, "backup": None, "message": "Packages already enabled"}
    configuration = config_path / "configuration.yaml"
    packages_dir = config_path / "packages"
    packages_dir.mkdir(parents=True, exist_ok=True)
    if not configuration.exists():
        tmp = configuration.with_suffix(".yaml.tmp")
        tmp.write_text("default_config:\n\nhomeassistant:\n  packages: !include_dir_named packages\n", encoding="utf-8")
        tmp.replace(configuration)
        result.update({"changed": True, "message": "Created configuration.yaml with package support"})
        return result

    text = configuration.read_text(encoding="utf-8")
    if "packages:" in text and "include_dir" in text:
        return result

    backup = configuration.with_suffix(f".yaml.{package_name}.bak")
    if not backup.exists():
        backup.write_text(text, encoding="utf-8")
        result["backup"] = str(backup)

    lines = text.splitlines()
    for idx, line in enumerate(lines):
        if re.match(r"^homeassistant:\s*$", line):
            insert_at = idx + 1
            while insert_at < len(lines) and (lines[insert_at].startswith("  ") or not lines[insert_at].strip()):
                insert_at += 1
            lines.insert(idx + 1, "  packages: !include_dir_named packages")
            tmp = configuration.with_suffix(".yaml.tmp")
            tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
            tmp.replace(configuration)
            result.update({"changed": True, "message": "Added package support under homeassistant"})
            return result

    addition = "\n\nhomeassistant:\n  packages: !include_dir_named packages\n"
    tmp = configuration.with_suffix(".yaml.tmp")
    tmp.write_text(text.rstrip() + addition, encoding="utf-8")
    tmp.replace(configuration)
    result.update({"changed": True, "message": "Added homeassistant package support"})
    return result


async def write_package_and_reload(
    store: JsonStore,
    current: HomeAssistantClient,
    options: AppOptions,
    ha_config_path: Path,
) -> dict[str, Any]:
    if not options.allow_config_writes:
        raise HomeAssistantError("Configuration writes are disabled in add-on options")
    ensure_result = ensure_packages_enabled(ha_config_path, options.package_name)
    package_path = ha_config_path / "packages" / f"{options.package_name}.yaml"
    tmp = package_path.with_suffix(".yaml.tmp")
    tmp.write_text(render_package(store.data.get("entity_maps", [])), encoding="utf-8")
    tmp.replace(package_path)
    services = [
        ("homeassistant", "reload_core_config"),
        ("input_boolean", "reload"),
        ("input_number", "reload"),
        ("input_text", "reload"),
        ("input_select", "reload"),
        ("input_button", "reload"),
    ]
    reload_errors = []
    for domain, service in services:
        try:
            await current.call_service(domain, service)
        except Exception as exc:
            reload_errors.append(f"{domain}.{service}: {exc}")
    return {
        "package_path": str(package_path),
        "packages": ensure_result,
        "reload_errors": reload_errors,
        "restart_recommended": bool(ensure_result.get("changed") or reload_errors),
    }


def mapping_from_plan_row(row: dict[str, Any], source_entity: dict[str, Any]) -> dict[str, Any]:
    identity = f"{row['source_instance_id']}::{row['source_entity_id']}"
    unique = hashlib.sha1(identity.encode("utf-8")).hexdigest()
    return {
        "source_instance_id": row["source_instance_id"],
        "source_instance_name": row.get("source_instance_name"),
        "source_entity_id": row["source_entity_id"],
        "source_domain": row["source_domain"],
        "source_unique_id": unique,
        "source_platform": row.get("platform"),
        "local_domain": row["helper_domain"],
        "object_id": row["object_id"],
        "local_entity_id": row["local_entity_id"],
        "name": row.get("name"),
        "source_attributes": source_entity.get("attributes") or {},
        "last_source_state": source_entity.get("state"),
        "last_sync_at": None,
        "writable": row["source_domain"] in WRITABLE_DOMAINS,
    }


async def apply_helper_state(current: HomeAssistantClient, mapping: dict[str, Any], state: Any) -> None:
    local_entity_id = mapping["local_entity_id"]
    domain = mapping["local_domain"]
    if state in UNKNOWN_STATES:
        return
    if domain == "input_boolean":
        service = "turn_on" if str(state).lower() in {"on", "open", "unlocked", "home", "true", "1"} else "turn_off"
        await current.call_service("input_boolean", service, {"entity_id": local_entity_id})
    elif domain == "input_number":
        try:
            value = float(state)
        except (TypeError, ValueError):
            return
        await current.call_service("input_number", "set_value", {"entity_id": local_entity_id, "value": value})
    elif domain == "input_text":
        await current.call_service("input_text", "set_value", {"entity_id": local_entity_id, "value": str(state)[:255]})
    elif domain == "input_select":
        await current.call_service("input_select", "select_option", {"entity_id": local_entity_id, "option": str(state)[:255]})


async def forward_control(source: HomeAssistantClient, source_domain: str, entity_id: str, value: Any) -> str:
    normalized = str(value).lower()
    if source_domain in {"automation", "fan", "humidifier", "input_boolean", "light", "remote", "siren", "switch"}:
        service = "turn_on" if normalized in {"on", "true", "1"} else "turn_off"
        await source.call_service(source_domain, service, {"entity_id": entity_id})
        return f"{source_domain}.{service}"
    if source_domain == "lock":
        service = "unlock" if normalized in {"on", "unlock", "unlocked", "true", "1"} else "lock"
        await source.call_service("lock", service, {"entity_id": entity_id})
        return f"lock.{service}"
    if source_domain == "cover":
        service = "open_cover" if normalized in {"on", "open", "true", "1"} else "close_cover"
        await source.call_service("cover", service, {"entity_id": entity_id})
        return f"cover.{service}"
    if source_domain in {"number", "input_number"}:
        await source.call_service(source_domain, "set_value", {"entity_id": entity_id, "value": float(value)})
        return f"{source_domain}.set_value"
    if source_domain in {"select", "input_select"}:
        await source.call_service(source_domain, "select_option", {"entity_id": entity_id, "option": str(value)})
        return f"{source_domain}.select_option"
    raise HomeAssistantError(f"Control forwarding is not supported for {source_domain}")
