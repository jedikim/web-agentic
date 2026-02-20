from app.schemas.recipe_schema import Policy, PolicyCondition


async def compile_intent_to_policy(
    goal: str,
    constraints: dict | None = None,
) -> dict[str, Policy]:
    """
    Phase 1 stub: Returns a minimal default policy.
    Phase 3 will replace with DSPy program + GEPA optimization.
    """
    default_policy = Policy(
        hard=[],
        score=[],
        tie_break=["label_asc"],
        pick="first",
    )
    return {"default_policy": default_policy}
