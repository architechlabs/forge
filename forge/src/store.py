import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JsonStore:
    def __init__(self, data_path: Path) -> None:
        self.path = data_path / "forge_store.json"
        self.data: dict[str, Any] = {
            "instances": [],
            "entity_maps": [],
            "jobs": [],
            "snapshots": {},
            "events": [],
        }
        self.load()

    def load(self) -> None:
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self.data.update(loaded)
            except Exception:
                backup = self.path.with_suffix(".corrupt.json")
                self.path.replace(backup)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)

    def add_event(self, level: str, message: str, detail: dict[str, Any] | None = None) -> None:
        events = self.data.setdefault("events", [])
        events.insert(
            0,
            {
                "id": secrets.token_hex(8),
                "level": level,
                "message": message,
                "detail": detail or {},
                "created_at": utc_now(),
            },
        )
        del events[100:]
        self.save()

    def public_instance(self, instance: dict[str, Any]) -> dict[str, Any]:
        cleaned = dict(instance)
        cleaned.pop("token", None)
        cleaned["token_configured"] = bool(instance.get("token"))
        return cleaned

    def instances_public(self) -> list[dict[str, Any]]:
        return [self.public_instance(item) for item in self.data.get("instances", [])]

    def get_instance(self, instance_id: str) -> dict[str, Any] | None:
        for item in self.data.get("instances", []):
            if item.get("id") == instance_id:
                return item
        return None

    def upsert_instance(self, payload: dict[str, Any]) -> dict[str, Any]:
        instance_id = payload.get("id") or secrets.token_hex(8)
        now = utc_now()
        current = self.get_instance(instance_id)
        if current is None:
            current = {
                "id": instance_id,
                "created_at": now,
                "enabled": True,
                "verify_ssl": True,
                "sync_enabled": True,
            }
            self.data.setdefault("instances", []).append(current)
        token = payload.get("token")
        for key in ("name", "url", "verify_ssl", "enabled", "sync_enabled"):
            if key in payload:
                current[key] = payload[key]
        if token:
            current["token"] = token
        current["updated_at"] = now
        for mapping in self.data.get("entity_maps", []):
            if mapping.get("source_instance_id") == instance_id:
                mapping["source_instance_name"] = current.get("name")
        self.save()
        return current

    def remove_instance(self, instance_id: str) -> bool:
        before = len(self.data.get("instances", []))
        self.data["instances"] = [
            item for item in self.data.get("instances", []) if item.get("id") != instance_id
        ]
        self.data["entity_maps"] = [
            item
            for item in self.data.get("entity_maps", [])
            if item.get("source_instance_id") != instance_id
        ]
        self.data.get("snapshots", {}).pop(instance_id, None)
        changed = before != len(self.data.get("instances", []))
        if changed:
            self.save()
        return changed

    def put_snapshot(self, instance_id: str, snapshot: dict[str, Any]) -> None:
        self.data.setdefault("snapshots", {})[instance_id] = snapshot
        instance = self.get_instance(instance_id)
        if instance:
            instance["last_scan_at"] = utc_now()
            instance["last_scan_count"] = len(snapshot.get("entities", []))
            instance["last_scan_error"] = None
        self.save()

    def record_scan_error(self, instance_id: str, message: str) -> None:
        instance = self.get_instance(instance_id)
        if instance:
            instance["last_scan_error"] = message
            instance["last_scan_at"] = utc_now()
        self.save()

    def upsert_entity_map(self, mapping: dict[str, Any]) -> dict[str, Any]:
        existing = self.find_map(mapping["source_instance_id"], mapping["source_entity_id"])
        if existing:
            existing.update(mapping)
            existing["updated_at"] = utc_now()
            self.save()
            return existing
        mapping.setdefault("id", secrets.token_hex(10))
        mapping.setdefault("created_at", utc_now())
        mapping.setdefault("sync_enabled", True)
        self.data.setdefault("entity_maps", []).append(mapping)
        self.save()
        return mapping

    def find_map(self, instance_id: str, entity_id: str) -> dict[str, Any] | None:
        for item in self.data.get("entity_maps", []):
            if item.get("source_instance_id") == instance_id and item.get("source_entity_id") == entity_id:
                return item
        return None

    def remove_map(self, map_id: str) -> bool:
        before = len(self.data.get("entity_maps", []))
        self.data["entity_maps"] = [
            item for item in self.data.get("entity_maps", []) if item.get("id") != map_id
        ]
        changed = before != len(self.data.get("entity_maps", []))
        if changed:
            self.save()
        return changed

    def create_job(self, kind: str, total: int) -> dict[str, Any]:
        job = {
            "id": secrets.token_hex(8),
            "kind": kind,
            "status": "running",
            "total": total,
            "done": 0,
            "errors": [],
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
        self.data.setdefault("jobs", []).insert(0, job)
        del self.data["jobs"][30:]
        self.save()
        return job

    def update_job(self, job: dict[str, Any], **changes: Any) -> None:
        job.update(changes)
        job["updated_at"] = utc_now()
        self.save()
