"""File-based storage for authoring profiles."""

from __future__ import annotations

import json
import shutil
from pathlib import Path


class ProfilesRepo:
    """File-based storage in data/profiles/ directory.

    Each profile is stored as a JSON file: data/profiles/{profile_id}.json
    Promoted versions are stored as: data/profiles/{profile_id}_v{version}.json
    """

    def __init__(self, base_dir: str | Path | None = None):
        if base_dir is None:
            base_dir = Path("data/profiles")
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, profile_id: str) -> Path:
        return self.base_dir / f"{profile_id}.json"

    def get(self, profile_id: str) -> dict | None:
        """Load profile JSON from file. Returns None if not found."""
        path = self._path(profile_id)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def save(self, profile_id: str, data: dict) -> None:
        """Save profile JSON to file."""
        path = self._path(profile_id)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def list(self) -> list[str]:
        """List all profile IDs (excluding promoted versions)."""
        profiles = []
        for p in sorted(self.base_dir.glob("*.json")):
            name = p.stem
            # Exclude promoted version files (pattern: name_vN)
            if "_v" in name:
                # Check if suffix after last _v is a number
                parts = name.rsplit("_v", 1)
                if len(parts) == 2 and parts[1].isdigit():
                    continue
            profiles.append(name)
        return profiles

    def delete(self, profile_id: str) -> bool:
        """Delete a profile. Returns True if deleted, False if not found."""
        path = self._path(profile_id)
        if path.exists():
            path.unlink()
            return True
        return False

    def promote(self, profile_id: str, version: int) -> str:
        """Copy current profile to a promoted version.

        Returns the promoted profile ID (e.g., 'profile-1_v3').
        """
        source = self._path(profile_id)
        if not source.exists():
            raise FileNotFoundError(f"Profile {profile_id} not found")

        promoted_id = f"{profile_id}_v{version}"
        dest = self._path(promoted_id)
        shutil.copy2(str(source), str(dest))

        # Update the version field inside the promoted file
        data = json.loads(dest.read_text(encoding="utf-8"))
        data["version"] = version
        data["promoted"] = True
        dest.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

        return promoted_id

    def list_versions(self, profile_id: str) -> list[int]:
        """List all promoted versions for a profile."""
        versions = []
        prefix = f"{profile_id}_v"
        for p in sorted(self.base_dir.glob(f"{prefix}*.json")):
            name = p.stem
            suffix = name[len(prefix):]
            if suffix.isdigit():
                versions.append(int(suffix))
        return sorted(versions)
