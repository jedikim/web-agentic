from fastapi import APIRouter, HTTPException

from app.storage.profiles_repo import ProfilesRepo

router = APIRouter()

_profiles_repo = ProfilesRepo()


@router.get("")
async def list_profiles():
    profile_ids = _profiles_repo.list()
    return {"profiles": profile_ids}


@router.get("/{profile_id}")
async def get_profile(profile_id: str):
    data = _profiles_repo.get(profile_id)
    if data is None:
        raise HTTPException(status_code=404, detail=f"Profile {profile_id} not found")
    return data


@router.get("/{profile_id}/versions")
async def list_profile_versions(profile_id: str):
    versions = _profiles_repo.list_versions(profile_id)
    return {"profile_id": profile_id, "versions": versions}
