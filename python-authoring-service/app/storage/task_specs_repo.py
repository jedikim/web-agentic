"""File-based storage for task specification samples."""

from __future__ import annotations

import json
import uuid
from pathlib import Path


class TaskSpecsRepo:
    """File-based storage in data/task_specs/ directory.

    Each task spec is stored as a JSON file: data/task_specs/{spec_id}.json
    """

    def __init__(self, base_dir: str | Path | None = None):
        if base_dir is None:
            base_dir = Path("data/task_specs")
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, spec_id: str) -> Path:
        return self.base_dir / f"{spec_id}.json"

    def get_specs(self) -> list[dict]:
        """Load all task spec JSON files."""
        specs = []
        for p in sorted(self.base_dir.glob("*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if "id" not in data:
                    data["id"] = p.stem
                specs.append(data)
            except (json.JSONDecodeError, OSError):
                continue
        return specs

    def add_spec(self, spec: dict) -> str:
        """Save a new spec to file. Returns the spec ID."""
        spec_id = spec.get("id") or str(uuid.uuid4())
        spec["id"] = spec_id
        path = self._path(spec_id)
        path.write_text(json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8")
        return spec_id

    def get_spec(self, spec_id: str) -> dict | None:
        """Get a single spec by ID."""
        path = self._path(spec_id)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def delete_spec(self, spec_id: str) -> bool:
        """Delete a spec. Returns True if deleted."""
        path = self._path(spec_id)
        if path.exists():
            path.unlink()
            return True
        return False
