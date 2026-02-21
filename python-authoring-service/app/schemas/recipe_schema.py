from pydantic import BaseModel, Field


class Expectation(BaseModel):
    kind: str  # url_contains | selector_visible | text_contains | title_contains
    value: str


class WorkflowStep(BaseModel):
    id: str
    op: str  # goto | act_cached | act_template | extract | choose | checkpoint | wait
    target_key: str | None = Field(None, alias="targetKey")
    args: dict | None = None
    expect: list[Expectation] | None = None
    on_fail: str | None = Field(None, alias="onFail")

    model_config = {"populate_by_name": True}


class Workflow(BaseModel):
    id: str
    version: str | None = None
    vars: dict | None = None
    steps: list[WorkflowStep]


class ActionRef(BaseModel):
    selector: str
    description: str
    method: str
    arguments: list[str] | None = None


class ActionEntry(BaseModel):
    instruction: str
    preferred: ActionRef
    observed_at: str = Field(alias="observedAt")

    model_config = {"populate_by_name": True}


class PolicyCondition(BaseModel):
    field: str
    op: str
    value: object


class PolicyScoreRule(BaseModel):
    when: PolicyCondition
    add: float


class Policy(BaseModel):
    hard: list[PolicyCondition]
    score: list[PolicyScoreRule]
    tie_break: list[str]
    pick: str  # argmax | argmin | first


class SelectorEntry(BaseModel):
    primary: str
    fallbacks: list[str]
    strategy: str


class Fingerprint(BaseModel):
    must_text: list[str] | None = Field(None, alias="mustText")
    must_selectors: list[str] | None = Field(None, alias="mustSelectors")
    url_contains: str | None = Field(None, alias="urlContains")

    model_config = {"populate_by_name": True}


class ChatMessage(BaseModel):
    role: str  # user | assistant
    content: str


class CompileIntentRequest(BaseModel):
    request_id: str = Field(alias="requestId")
    goal: str
    procedure: str | None = None
    domain: str | None = None
    context: dict | None = None
    history: list[ChatMessage] | None = None

    model_config = {"populate_by_name": True}


class CompileIntentResponse(BaseModel):
    request_id: str = Field(alias="requestId")
    workflow: Workflow
    actions: dict[str, ActionEntry]
    selectors: dict[str, SelectorEntry]
    policies: dict[str, Policy]
    fingerprints: dict[str, Fingerprint]

    model_config = {"populate_by_name": True}
