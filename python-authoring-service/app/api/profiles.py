from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/{profile_id}")
async def get_profile(profile_id: str):
    # TODO: Load from storage
    raise HTTPException(status_code=404, detail=f"Profile {profile_id} not found")
