import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from .bridge import (
    apply_helper_state,
    build_import_plan,
    current_platforms,
    forward_control,
    mapping_from_plan_row,
    scan_home_assistant,
    write_package_and_reload,
)
from .ha_client import HomeAssistantClient, HomeAssistantError
from .settings import DATA_PATH, HA_CONFIG_PATH, AppOptions, load_options
from .store import JsonStore, utc_now


options: AppOptions = load_options()
store = JsonStore(DATA_PATH)
sync_task: asyncio.Task | None = None


class InstancePayload(BaseModel):
    id: str | None = None
    name: str = Field(min_length=1, max_length=80)
    url: str = Field(min_length=3, max_length=300)
    token: str | None = Field(default=None, max_length=4096)
    verify_ssl: bool = True
    enabled: bool = True
    sync_enabled: bool = True

    @field_validator("url")
    @classmethod
    def url_must_be_usable(cls, value: str) -> str:
        cleaned = normalize_url(value)
        if cleaned.startswith(("http://", "https://")):
            return cleaned
        raise ValueError("URL must use http or https")


class PlanPayload(BaseModel):
    instance_ids: list[str] = Field(min_length=1)
    entity_ids: list[str] | None = None
    entity_refs: list[str] | None = None
    prefix: str = "forge"
    conflict_policy: Literal["rename", "skip"] = "rename"

    @field_validator("prefix")
    @classmethod
    def prefix_is_short_slug(cls, value: str) -> str:
        cleaned = value.strip() or "forge"
        if len(cleaned) > 32:
            raise ValueError("Prefix must be 32 characters or fewer")
        return cleaned


class ImportPayload(PlanPayload):
    dry_run: bool = False


class ControlPayload(BaseModel):
    value: Any


def normalize_url(url: str) -> str:
    cleaned = url.strip().rstrip("/")
    if "://" not in cleaned:
        cleaned = f"http://{cleaned}"
    return cleaned


def public_dashboard() -> dict[str, Any]:
    return {
        "options": {
            "poll_interval": options.poll_interval,
            "allow_config_writes": options.allow_config_writes,
            "package_name": options.package_name,
            "max_entities_per_import": options.max_entities_per_import,
        },
        "instances": store.instances_public(),
        "entity_maps": store.data.get("entity_maps", []),
        "jobs": store.data.get("jobs", []),
        "events": store.data.get("events", []),
        "snapshots": {
            instance_id: {
                "scanned_at": snapshot.get("scanned_at"),
                "counts": snapshot.get("counts"),
                "platforms": snapshot.get("platforms", []),
                "entities": snapshot.get("entities", []),
            }
            for instance_id, snapshot in store.data.get("snapshots", {}).items()
        },
    }


def current_client() -> HomeAssistantClient:
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        raise HTTPException(status_code=503, detail="SUPERVISOR_TOKEN is not available inside this runtime")
    return HomeAssistantClient.current(token)


def source_client(instance: dict[str, Any]) -> HomeAssistantClient:
    token = instance.get("token")
    if not token:
        raise HTTPException(status_code=400, detail="This source instance has no token configured")
    return HomeAssistantClient(
        normalize_url(instance.get("url", "")),
        token,
        verify_ssl=bool(instance.get("verify_ssl", True)),
    )


async def sync_once(map_ids: set[str] | None = None) -> dict[str, Any]:
    current = current_client()
    current_states = {item["entity_id"]: item for item in await current.get_states()}
    updated = 0
    forwarded = 0
    skipped = 0
    errors: list[str] = []
    instances = {item["id"]: item for item in store.data.get("instances", [])}
    source_state_cache: dict[str, dict[str, dict[str, Any]]] = {}

    eligible_maps = []
    for mapping in list(store.data.get("entity_maps", [])):
        if map_ids and mapping.get("id") not in map_ids:
            continue
        if not mapping.get("sync_enabled", True):
            skipped += 1
            continue
        instance = instances.get(mapping["source_instance_id"])
        if not instance or not instance.get("enabled", True) or not instance.get("sync_enabled", True):
            skipped += 1
            continue
        eligible_maps.append((mapping, instance))

    for instance_id, instance in instances.items():
        if not instance.get("enabled", True) or not instance.get("sync_enabled", True):
            continue
        if not any(mapping["source_instance_id"] == instance_id for mapping, _ in eligible_maps):
            continue
        try:
            source = source_client(instance)
            source_state_cache[instance_id] = {item["entity_id"]: item for item in await source.get_states()}
        except Exception as exc:
            errors.append(f"{instance.get('name') or instance_id}: {exc}")

    for mapping, instance in eligible_maps:
        try:
            source_states = source_state_cache.get(mapping["source_instance_id"], {})
            source_entity = source_states.get(mapping["source_entity_id"])
            local_entity = current_states.get(mapping["local_entity_id"])
            if not source_entity:
                skipped += 1
                mapping["last_error"] = "Source entity was not found during sync"
                continue

            local_state = (local_entity or {}).get("state")
            last_local_state = mapping.get("last_local_state")
            did_forward = False
            if (
                mapping.get("writable")
                and local_entity
                and last_local_state is not None
                and str(local_state) != str(last_local_state)
                and str(local_state) != str(mapping.get("last_source_state"))
            ):
                try:
                    await forward_control(
                        source_client(instance),
                        mapping["source_domain"],
                        mapping["source_entity_id"],
                        local_state,
                    )
                    forwarded += 1
                    did_forward = True
                except Exception as exc:
                    errors.append(f"{mapping['local_entity_id']} control: {exc}")

            source_state = source_entity.get("state")
            if did_forward:
                source_state = local_state
            if str(source_state) != str(local_state):
                try:
                    await apply_helper_state(current, mapping, source_state)
                    updated += 1
                except Exception as exc:
                    errors.append(f"{mapping['local_entity_id']} sync: {exc}")

            mapping["last_source_state"] = source_state
            mapping["last_local_state"] = source_state
            mapping["last_sync_at"] = utc_now()
            mapping["last_error"] = None
        except Exception as exc:
            mapping["last_error"] = str(exc)
            errors.append(f"{mapping.get('source_entity_id')}: {exc}")

    if updated or forwarded or skipped or errors:
        store.save()
    if errors:
        store.add_event("warning", "Sync completed with warnings", {"errors": errors[:10]})
    return {"updated": updated, "forwarded": forwarded, "skipped": skipped, "errors": errors}


async def sync_forever() -> None:
    while True:
        try:
            await sync_once()
        except HTTPException:
            pass
        except Exception as exc:
            store.add_event("warning", "Background sync failed", {"error": str(exc)})
        await asyncio.sleep(options.poll_interval)


@asynccontextmanager
async def lifespan(_: FastAPI):
    global sync_task
    sync_task = asyncio.create_task(sync_forever())
    yield
    if sync_task:
        sync_task.cancel()


app = FastAPI(title="Forge", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
UI_PATH = Path(__file__).resolve().parents[1] / "ui"


@app.middleware("http")
async def normalize_ingress_slashes(request, call_next):
    path = request.scope.get("path", "")
    if "//" in path:
        while "//" in path:
            path = path.replace("//", "/")
        request.scope["path"] = path or "/"
    return await call_next(request)


app.mount("/static", StaticFiles(directory=str(UI_PATH)), name="static")


@app.get("/")
@app.get("//")
async def index() -> FileResponse:
    return FileResponse(str(UI_PATH / "index.html"))


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "time": utc_now()}


@app.get("/api/dashboard")
async def dashboard() -> dict[str, Any]:
    return public_dashboard()


@app.post("/api/instances")
async def save_instance(payload: InstancePayload) -> dict[str, Any]:
    data = payload.model_dump()
    instance = store.upsert_instance(data)
    store.add_event("info", f"Saved source instance {instance.get('name')}")
    return store.public_instance(instance)


@app.delete("/api/instances/{instance_id}")
async def delete_instance(instance_id: str) -> dict[str, Any]:
    if not store.remove_instance(instance_id):
        raise HTTPException(status_code=404, detail="Instance not found")
    reload_result = await write_package_and_reload(store, current_client(), options, HA_CONFIG_PATH)
    return {"ok": True, "reload": reload_result}


@app.post("/api/instances/{instance_id}/test")
async def test_instance(instance_id: str) -> dict[str, Any]:
    instance = store.get_instance(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    try:
        config = await source_client(instance).get_config()
        return {"ok": True, "location_name": config.get("location_name"), "version": config.get("version")}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/instances/{instance_id}/scan")
async def scan_instance(instance_id: str) -> dict[str, Any]:
    instance = store.get_instance(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    try:
        snapshot = await scan_home_assistant(source_client(instance))
        store.put_snapshot(instance_id, snapshot)
        store.add_event("info", f"Scanned {instance.get('name')}", snapshot.get("counts"))
        return snapshot
    except Exception as exc:
        store.record_scan_error(instance_id, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/scan-all")
async def scan_all(background_tasks: BackgroundTasks) -> dict[str, Any]:
    enabled = [item["id"] for item in store.data.get("instances", []) if item.get("enabled", True)]

    async def runner() -> None:
        for instance_id in enabled:
            try:
                await scan_instance(instance_id)
            except Exception:
                continue

    background_tasks.add_task(runner)
    return {"queued": len(enabled)}


@app.post("/api/plan")
async def plan_import(payload: PlanPayload) -> dict[str, Any]:
    current = current_client()
    try:
        states = await current.get_states()
    except Exception:
        states = []
    try:
        platforms = await current_platforms(current)
    except Exception:
        platforms = set()
    return build_import_plan(
        store,
        states,
        payload.instance_ids,
        payload.entity_ids,
        payload.entity_refs,
        payload.prefix,
        payload.conflict_policy,
        platforms,
    )


@app.post("/api/import")
async def import_entities(payload: ImportPayload) -> dict[str, Any]:
    plan = await plan_import(payload)
    rows = [row for row in plan["rows"] if row.get("status") == "ready"]
    if len(rows) > options.max_entities_per_import:
        raise HTTPException(status_code=400, detail=f"Import exceeds limit of {options.max_entities_per_import} entities")
    if payload.dry_run:
        return {"dry_run": True, "plan": plan}

    job = store.create_job("import", len(rows))
    created_ids: set[str] = set()
    previous_maps = [dict(item) for item in store.data.get("entity_maps", [])]
    try:
        for row in rows:
            snapshot = store.data.get("snapshots", {}).get(row["source_instance_id"], {})
            source_entity = next(
                (item for item in snapshot.get("entities", []) if item["entity_id"] == row["source_entity_id"]),
                None,
            )
            if not source_entity:
                job["errors"].append(f"Missing scan data for {row['source_entity_id']}")
                continue
            mapping = store.upsert_entity_map(mapping_from_plan_row(row, source_entity))
            created_ids.add(mapping["id"])
            job["done"] += 1
            store.update_job(job)
        reload_result = await write_package_and_reload(store, current_client(), options, HA_CONFIG_PATH)
        try:
            await sync_once(created_ids)
        except Exception as exc:
            job["errors"].append(f"Initial sync warning: {exc}")
        store.update_job(job, status="complete", reload=reload_result)
        store.add_event("info", f"Imported {job['done']} entities", reload_result)
        return {"job": job, "plan": plan, "reload": reload_result}
    except (HomeAssistantError, HTTPException) as exc:
        store.data["entity_maps"] = previous_maps
        store.save()
        detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
        store.update_job(job, status="failed", errors=[*job["errors"], str(exc)])
        raise HTTPException(status_code=400, detail=detail) from exc
    except Exception as exc:
        store.data["entity_maps"] = previous_maps
        store.save()
        store.update_job(job, status="failed", errors=[*job["errors"], str(exc)])
        raise HTTPException(status_code=500, detail=f"Import failed: {exc}") from exc


@app.post("/api/sync")
async def manual_sync() -> dict[str, Any]:
    return await sync_once()


@app.post("/api/entities/{map_id}/control")
async def control_entity(map_id: str, payload: ControlPayload) -> dict[str, Any]:
    mapping = next((item for item in store.data.get("entity_maps", []) if item.get("id") == map_id), None)
    if not mapping:
        raise HTTPException(status_code=404, detail="Imported entity not found")
    instance = store.get_instance(mapping["source_instance_id"])
    if not instance:
        raise HTTPException(status_code=404, detail="Source instance not found")
    service = await forward_control(
        source_client(instance),
        mapping["source_domain"],
        mapping["source_entity_id"],
        payload.value,
    )
    await apply_helper_state(current_client(), mapping, payload.value)
    mapping["last_local_state"] = str(payload.value)
    mapping["last_sync_at"] = utc_now()
    store.save()
    return {"ok": True, "service": service}


@app.delete("/api/entities/{map_id}")
async def remove_entity(map_id: str) -> dict[str, Any]:
    if not store.remove_map(map_id):
        raise HTTPException(status_code=404, detail="Imported entity not found")
    reload_result = await write_package_and_reload(store, current_client(), options, HA_CONFIG_PATH)
    return {"ok": True, "reload": reload_result}
