"""HTTP and domain source of truth. IDs refer to internal resources, never paths."""
from enum import StrEnum
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

ID = Annotated[str, Field(pattern=r'^[a-zA-Z0-9_-]{1,100}$')]


class Schema(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class ErrorCode(StrEnum):
    DEVICE_DISCONNECTED = 'DEVICE_DISCONNECTED'
    CAPABILITY_UNVERIFIED = 'CAPABILITY_UNVERIFIED'
    CATALOG_INCOMPLETE = 'CATALOG_INCOMPLETE'
    SCOPE_STALE = 'SCOPE_STALE'
    GROUP_NOT_READY = 'GROUP_NOT_READY'
    DOWNLOAD_INCOMPLETE = 'DOWNLOAD_INCOMPLETE'
    MEDIA_UNSUPPORTED = 'MEDIA_UNSUPPORTED'
    STORAGE_FULL = 'STORAGE_FULL'
    NETWORK_UNAVAILABLE = 'NETWORK_UNAVAILABLE'
    MODEL_TIMEOUT = 'MODEL_TIMEOUT'
    MODEL_OUTPUT_INVALID = 'MODEL_OUTPUT_INVALID'
    STALE_REVISION = 'STALE_REVISION'
    CONFLICT = 'CONFLICT'
    NOT_FOUND = 'NOT_FOUND'
    INVALID_INPUT = 'INVALID_INPUT'


class DomainError(Exception):
    def __init__(self, code: ErrorCode | str, message: str, status: int = 409,
                 action: str = 'retry', retryable: bool = False):
        self.code, self.message, self.status = str(code), message, status
        self.action, self.retryable = action, retryable
        super().__init__(message)


class ErrorDetail(Schema):
    code: ErrorCode
    message: str
    retryable: bool
    action: str
    job_id: ID | None = None


class ErrorResponse(Schema):
    error: ErrorDetail
    request_id: ID


class Criterion(Schema):
    id: ID
    description: str = Field(min_length=1, max_length=500)
    required: bool = True
    continuous: bool = False


class Shot(Schema):
    id: ID
    title: str = Field(min_length=1, max_length=200)
    required: bool = True
    critical: bool = False
    criteria: list[Criterion] = Field(min_length=1, max_length=20)


class CreateProject(Schema):
    goal: str = Field(min_length=1, max_length=2000)
    target_seconds: int = Field(default=45, ge=30, le=60)
    conditions: str = Field(default='', max_length=2000)


class Revision(Schema):
    expected_revision: int = Field(ge=0)


class PlanEdit(Revision):
    shots: list[Shot] = Field(min_length=1, max_length=30)

    @model_validator(mode='after')
    def unique_ids(self):
        ids = [s.id for s in self.shots] + [c.id for s in self.shots for c in s.criteria]
        if len(ids) != len(set(ids)):
            raise ValueError('分镜和标准 ID 必须唯一')
        if not any(s.required and any(c.required for c in s.criteria) for s in self.shots):
            raise ValueError('至少需要一个必要分镜及必要标准')
        if any(s.required and not any(c.required for c in s.criteria) for s in self.shots):
            raise ValueError('必要分镜必须包含必要标准')
        return self


class Evidence(Schema):
    id: ID
    shot_id: ID
    criterion_id: ID
    clip_id: ID
    rendition_id: ID
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    verdict: Literal['supports', 'defect', 'uncertain']
    reason: str = Field(min_length=1, max_length=1000)
    continuous: bool = False

    @model_validator(mode='after')
    def interval(self):
        if self.end <= self.start:
            raise ValueError('证据结束必须晚于开始')
        return self


class Group(Schema):
    id: ID
    revision: ID
    name: str
    storage_epoch: ID = 'card_demo'
    members: list[ID] = Field(min_length=1)
    sizes: list[int] = Field(min_length=1)
    closed: bool = False
    complete: bool = False
    projection: Literal['rectilinear', 'unknown', 'panorama'] = 'unknown'
    # Simulator-only observations; never inferred from filenames.
    scenario: Literal['materials', 'result', 'occluded', 'clear', 'unrelated', 'uncertain'] = 'unrelated'

    @model_validator(mode='after')
    def files(self):
        if len(self.members) != len(self.sizes) or len(set(self.members)) != len(self.members):
            raise ValueError('成员与大小不匹配')
        if any(size <= 0 for size in self.sizes):
            raise ValueError('文件大小必须为正')
        return self


class Catalog(Schema):
    id: ID
    device_id: ID = 'camera_demo'
    complete: bool = True
    completed_at: float
    groups: list[Group]
    next_cursor: str | None = None


class Scope(Revision):
    device_id: ID
    snapshot_id: ID
    selected_group_ids: list[ID]


class ConfirmScope(Revision):
    snapshot_id: ID
    include_group_ids: list[ID]
    exclude_group_ids: list[ID]


class MembershipEdit(Revision):
    membership: Literal['included', 'excluded']
    reason: str = Field(default='', max_length=1000)


class Connect(Schema):
    profile_id: Literal['simulator', 'x5']


class Retry(Schema):
    expected_attempt: int = Field(ge=0)


class Job(Schema):
    id: ID
    project_id: ID | None
    kind: str
    state: Literal['queued', 'running', 'retry_wait', 'succeeded', 'failed', 'cancelled']
    attempt: int
    error: ErrorDetail | None = None
    result: dict | None = None


class Project(Schema):
    id: ID
    goal: str
    target_seconds: int
    conditions: str
    revision: int
    plan_version: int
    confirmed: bool
    shots: list[Shot]
    created_at: float


class Clip(Schema):
    id: ID
    name: str
    group_key: str
    state: Literal['awaiting_ready', 'downloading', 'preparing', 'analyzing', 'analyzed',
                   'failed', 'blocked_format', 'excluded', 'queued']
    active: bool = True
    generation: int = 1
    rendition_id: ID | None = None
    duration: float | None = None
    error: ErrorDetail | None = None
    job_id: ID | None = None


class Session(Schema):
    id: ID
    project_id: ID
    device_id: ID
    state: Literal['watching', 'awaiting_scope', 'paused', 'disconnected', 'error', 'closed']
    snapshot_id: ID
    last_complete_scan_at: float | None = None
    membership: dict[str, Literal['included', 'excluded', 'pending_confirmation']]
    storage_epoch: ID | None = None


class ShotCoverage(Schema):
    id: ID
    title: str
    required: bool
    state: Literal['pending', 'covered', 'reshoot', 'uncertain']
    evidence_ids: list[ID]
    missing: list[str]


class NextAction(Schema):
    project_revision: int
    shot_id: ID
    what: str
    how: str
    why: str


class Snapshot(Schema):
    project: Project
    project_id: ID
    revision: int
    plan_version: int
    camera_mode: Literal['simulator', 'unconfigured']
    model_mode: Literal['simulator', 'unconfigured']
    sync: Session | None
    pending_scope_count: int
    pipeline: dict[str, int]
    clips: list[Clip]
    evidence: list[Evidence]
    shots: list[ShotCoverage]
    coverage_complete: bool
    readiness: Literal['not_ready', 'checking', 'unverified', 'ready']
    checked_at: float | None
    verified_snapshot_id: ID | None
    next_action: NextAction | None
    jobs: list[Job]


class ProjectPage(Schema):
    items: list[Project]
    next_cursor: str | None = None


class ClipPage(Schema):
    items: list[Clip]
    next_cursor: str | None = None


class Health(Schema):
    status: str
    camera_mode: str
    model_mode: str
    worker: str
    database: str


class Device(Schema):
    id: ID
    connection_state: str
    mode: str
    firmware: str
    capabilities: dict[str, Literal['supported', 'unsupported', 'unknown']]
    evidence: str
