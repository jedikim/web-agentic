class ProfilesRepo:
    """Stub storage for authoring profiles."""

    async def get(self, profile_id: str) -> dict | None:
        return None

    async def save(self, profile_id: str, data: dict) -> None:
        pass
