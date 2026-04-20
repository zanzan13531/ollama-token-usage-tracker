from pydantic import BaseModel


class ModelBreakdown(BaseModel):
    model: str
    requests: int
    input_tokens: int
    output_tokens: int


class StatsResponse(BaseModel):
    total_requests: int
    total_input_tokens: int
    total_output_tokens: int
    avg_latency_ms: float
    models: list[ModelBreakdown]


class TimeBucketStats(BaseModel):
    period: str
    requests: int
    input_tokens: int
    output_tokens: int
    avg_latency_ms: float
    models: list[ModelBreakdown]


class IngestRecord(BaseModel):
    device: str
    endpoint: str
    model: str
    prompt_eval_count: int = 0
    eval_count: int = 0
    total_duration: int = 0
    load_duration: int = 0
    prompt_eval_duration: int = 0
    eval_duration: int = 0
    prompt_length: int = 0
    temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = None
    num_predict: int | None = None
    response_latency_ms: float = 0
    is_streaming: bool = True
    timestamp: str | None = None


class IngestPayload(BaseModel):
    records: list[IngestRecord]


class IngestResponse(BaseModel):
    accepted: int
