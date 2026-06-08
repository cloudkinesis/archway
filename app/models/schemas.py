from pydantic import BaseModel, Field


class CreateSessionRequest(BaseModel):
    initial_use_case: str = Field(min_length=3, max_length=20_000)


class UpdateSessionRequest(BaseModel):
    name: str | None = Field(default=None, max_length=160)


class SynthesisMessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20_000)


class ProceedRequest(BaseModel):
    assume_and_proceed: bool = False
    answers: dict[str, str] = Field(default_factory=dict)


class ArchitectureSpecPatch(BaseModel):
    summary: str | None = Field(default=None, max_length=4000)
    scaling_strategy: str | None = Field(default=None, max_length=3000)
    resilience_strategy: str | None = Field(default=None, max_length=3000)
    cost_optimization_strategy: str | None = Field(default=None, max_length=3000)
    security_controls: list[dict[str, str]] | None = None
    observability_controls: list[dict[str, str]] | None = None


class UpdateArchitectureRequest(BaseModel):
    reason: str = Field(default="User-edited architecture revision", max_length=500)
    specs: dict[str, ArchitectureSpecPatch]
