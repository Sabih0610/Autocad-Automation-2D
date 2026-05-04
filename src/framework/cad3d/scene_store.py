"""In-memory and JSON-backed CAD3D scene state store."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from src.framework.cad3d.scene_schema import validate_cad3d_scene


class CAD3DSceneStoreError(Exception):
    """Raised when CAD3D scene state cannot be stored or retrieved."""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _validate_status(status: str) -> str:
    if status not in {"generated", "approved", "failed"}:
        raise CAD3DSceneStoreError(f"Unsupported CAD3D scene status: {status}")
    return status


def _scene_validation_errors(scene: dict) -> list[str]:
    if not isinstance(scene, dict):
        return ["root: scene must be a dict"]
    return validate_cad3d_scene(scene)


def _validate_scene_or_raise(scene: dict) -> None:
    errors = _scene_validation_errors(scene)
    if errors:
        joined_errors = "\n".join(f"- {error}" for error in errors)
        raise CAD3DSceneStoreError(f"Invalid CAD3D scene:\n{joined_errors}")


def extract_scene_component_summary(scene: dict) -> dict:
    """Return component ids, component types, and counts for a CAD3D scene."""
    components = scene.get("components", []) if isinstance(scene, dict) else []
    component_ids = [
        str(component.get("id"))
        for component in components
        if component.get("id") is not None
    ]
    component_types = sorted(
        {
            str(component.get("component_type"))
            for component in components
            if component.get("component_type") is not None
        }
    )
    type_counts: dict[str, int] = {}
    for component in components:
        component_type = component.get("component_type")
        if component_type is None:
            continue
        clean_type = str(component_type)
        type_counts[clean_type] = type_counts.get(clean_type, 0) + 1

    return {
        "component_count": len(components),
        "component_ids": component_ids,
        "component_types": component_types,
        "type_counts": dict(sorted(type_counts.items())),
    }


@dataclass
class CAD3DSceneRecord:
    token: str
    prompt: str
    drawing_style: str | None
    scene: dict
    component_ids: list[str]
    component_types: list[str]
    created_at: str
    updated_at: str
    status: str
    document_name: str | None = None
    approval_result: dict | None = None
    generation_metadata: dict | None = None
    expanded_scene: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "CAD3DSceneRecord":
        if not isinstance(data, dict):
            raise CAD3DSceneStoreError("CAD3D scene record data must be a dict")

        required = {
            "token",
            "prompt",
            "drawing_style",
            "scene",
            "component_ids",
            "component_types",
            "created_at",
            "updated_at",
            "status",
        }
        missing = sorted(required - set(data))
        if missing:
            raise CAD3DSceneStoreError(
                f"CAD3D scene record is missing required fields: {', '.join(missing)}"
            )

        _validate_scene_or_raise(data["scene"])
        if data.get("expanded_scene") is not None:
            _validate_scene_or_raise(data["expanded_scene"])

        return cls(
            token=str(data["token"]),
            prompt=str(data.get("prompt") or ""),
            drawing_style=data.get("drawing_style"),
            scene=deepcopy(data["scene"]),
            component_ids=[str(component_id) for component_id in data.get("component_ids", [])],
            component_types=[str(component_type) for component_type in data.get("component_types", [])],
            created_at=str(data["created_at"]),
            updated_at=str(data["updated_at"]),
            status=_validate_status(str(data["status"])),
            document_name=data.get("document_name"),
            approval_result=deepcopy(data.get("approval_result")),
            generation_metadata=deepcopy(data.get("generation_metadata")),
            expanded_scene=deepcopy(data.get("expanded_scene")),
        )


class CAD3DSceneStore:
    def __init__(self, persist_dir: str | Path | None = None):
        self._records: dict[str, CAD3DSceneRecord] = {}
        self._latest_token: str | None = None
        self.persist_dir = Path(persist_dir) if persist_dir is not None else None

    def put_generated_scene(
        self,
        token: str,
        prompt: str,
        scene: dict,
        drawing_style: str | None = None,
        generation_metadata: dict | None = None,
    ) -> CAD3DSceneRecord:
        clean_token = self._clean_token(token)
        _validate_scene_or_raise(scene)
        summary = extract_scene_component_summary(scene)
        now = _utc_now_iso()
        record = CAD3DSceneRecord(
            token=clean_token,
            prompt=str(prompt or ""),
            drawing_style=drawing_style,
            scene=deepcopy(scene),
            component_ids=summary["component_ids"],
            component_types=summary["component_types"],
            created_at=now,
            updated_at=now,
            status="generated",
            generation_metadata=deepcopy(generation_metadata) if generation_metadata is not None else None,
        )
        self._records[clean_token] = record
        self._latest_token = clean_token
        self._persist_record(record)
        return record

    def mark_approved(
        self,
        token: str,
        approval_result: dict,
        expanded_scene: dict | None = None,
    ) -> CAD3DSceneRecord:
        record = self.get(token)
        if not isinstance(approval_result, dict):
            raise CAD3DSceneStoreError("approval_result must be a dict")

        if expanded_scene is not None:
            _validate_scene_or_raise(expanded_scene)

        record.status = "approved" if approval_result.get("ok") else "failed"
        record.approval_result = deepcopy(approval_result)
        record.document_name = approval_result.get("document_name")
        record.expanded_scene = deepcopy(expanded_scene) if expanded_scene is not None else None
        record.updated_at = _utc_now_iso()
        self._records[record.token] = record
        self._latest_token = record.token
        self._persist_record(record)
        return record

    def get(self, token: str) -> CAD3DSceneRecord:
        clean_token = self._clean_token(token)
        record = self._records.get(clean_token)
        if record is not None:
            return record

        record = self._load_record_from_disk(clean_token)
        self._records[clean_token] = record
        self._latest_token = clean_token
        return record

    def get_latest(self) -> CAD3DSceneRecord:
        if self._latest_token is not None:
            return self.get(self._latest_token)

        self._load_all_records_from_disk()
        if self._latest_token is None:
            raise CAD3DSceneStoreError("No CAD3D scene records are available")

        return self.get(self._latest_token)

    def list_records(self, limit: int = 20) -> list[CAD3DSceneRecord]:
        if isinstance(limit, bool) or int(limit) <= 0:
            raise CAD3DSceneStoreError("limit must be positive")

        self._load_all_records_from_disk()
        records = sorted(
            self._records.values(),
            key=lambda record: record.updated_at,
            reverse=True,
        )
        return records[: int(limit)]

    def delete(self, token: str) -> bool:
        clean_token = self._clean_token(token)
        existed = clean_token in self._records
        self._records.pop(clean_token, None)

        deleted_disk = False
        if self.persist_dir is not None:
            path = self._record_path(clean_token)
            if path.exists():
                path.unlink()
                deleted_disk = True

        if self._latest_token == clean_token:
            if self._records:
                self._latest_token = max(
                    self._records.values(),
                    key=lambda record: record.updated_at,
                ).token
            else:
                self._latest_token = None

        return existed or deleted_disk

    def clear(self) -> None:
        self._records.clear()
        self._latest_token = None

    def _persist_record(self, record: CAD3DSceneRecord) -> None:
        if self.persist_dir is None:
            return

        try:
            self.persist_dir.mkdir(parents=True, exist_ok=True)
            path = self._record_path(record.token)
            tmp_path = path.with_name(f"{path.name}.tmp")
            tmp_path.write_text(
                json.dumps(record.to_dict(), indent=2, sort_keys=True),
                encoding="utf-8",
            )
            tmp_path.replace(path)
        except OSError as exc:
            raise CAD3DSceneStoreError(f"Failed to persist CAD3D scene record: {exc}") from exc

    def _load_record_from_disk(self, token: str) -> CAD3DSceneRecord:
        if self.persist_dir is None:
            raise CAD3DSceneStoreError(f"CAD3D scene token not found: {token}")

        path = self._record_path(token)
        if not path.exists():
            raise CAD3DSceneStoreError(f"CAD3D scene token not found: {token}")

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CAD3DSceneStoreError(f"Failed to load CAD3D scene record {token}: {exc}") from exc

        return CAD3DSceneRecord.from_dict(data)

    def _load_all_records_from_disk(self) -> None:
        if self.persist_dir is None or not self.persist_dir.exists():
            return

        for path in self.persist_dir.glob("*.json"):
            token = path.stem
            if token in self._records:
                continue
            try:
                record = self._load_record_from_disk(token)
            except CAD3DSceneStoreError:
                continue
            self._records[token] = record

        if self._records and self._latest_token is None:
            self._latest_token = max(
                self._records.values(),
                key=lambda record: record.updated_at,
            ).token

    def _record_path(self, token: str) -> Path:
        if self.persist_dir is None:
            raise CAD3DSceneStoreError("CAD3D scene persistence directory is not configured")
        clean_token = self._clean_token(token)
        return self.persist_dir / f"{clean_token}.json"

    @staticmethod
    def _clean_token(token: str) -> str:
        clean_token = str(token or "").strip()
        if not clean_token:
            raise CAD3DSceneStoreError("CAD3D scene token cannot be empty")
        if any(separator in clean_token for separator in ("/", "\\", "..")):
            raise CAD3DSceneStoreError("CAD3D scene token contains invalid path characters")
        return clean_token


_DEFAULT_CAD3D_SCENE_STORE = CAD3DSceneStore(
    persist_dir=Path("outputs") / "cad3d" / "scenes"
)


def get_default_cad3d_scene_store() -> CAD3DSceneStore:
    return _DEFAULT_CAD3D_SCENE_STORE
