class TaskSpecsRepo:
    """Stub storage for task specification samples."""

    async def get_specs(self) -> list[dict]:
        return []

    async def add_spec(self, spec: dict) -> None:
        pass
