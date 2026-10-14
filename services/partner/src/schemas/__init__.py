"""API リクエスト/レスポンス スキーマ"""

from datetime import date, datetime
from uuid import UUID

from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, Field


# ============================================
# 共通
# ============================================
T = TypeVar("T")


class APIResponse(BaseModel, Generic[T]):
    success: bool = True
    data: T | None = None
    error: dict | None = None
    meta: dict | None = None


class TokenData(BaseModel):
    sub: str
    type: str = "user"
    org: str | None = None
    roles: list[str] = Field(default_factory=list)
    scopes: list[str] = Field(default_factory=list)

    model_config = {"from_attributes": True}


# ============================================
# 協力会社 (Partner)
# ============================================
# 語彙（許可リスト）: 協力会社の種別と取引状態。未定義値は 422 で拒否する。
CompanyType = Literal[
    "subcontractor", "supplier", "consultant", "designer", "surveyor",
    "equipment_rental", "material_supplier", "transportation", "other",
]
PartnerStatus = Literal["active", "inactive", "blacklisted", "pending_review"]


class PartnerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    name_kana: str | None = None
    company_type: CompanyType
    tax_id: str | None = None
    address: str | None = None
    phone: str | None = None
    email: str | None = None
    website: str | None = None
    representative_name: str | None = None
    employee_count: int | None = None
    established_year: int | None = None
    specializations: list[str] | None = None
    license_info: dict | None = None
    insurance_info: dict | None = None
    status: PartnerStatus = "active"


class PartnerUpdate(BaseModel):
    name: str | None = None
    name_kana: str | None = None
    company_type: CompanyType | None = None
    tax_id: str | None = None
    address: str | None = None
    phone: str | None = None
    email: str | None = None
    website: str | None = None
    representative_name: str | None = None
    employee_count: int | None = None
    established_year: int | None = None
    specializations: list[str] | None = None
    license_info: dict | None = None
    insurance_info: dict | None = None
    status: PartnerStatus | None = None


class PartnerContactCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    title: str | None = None
    department: str | None = None
    email: str = Field(min_length=1, max_length=255)
    phone: str | None = None
    is_primary: bool = False


class PartnerContactResponse(BaseModel):
    id: UUID
    partner_id: UUID
    name: str
    title: str | None
    department: str | None
    email: str
    phone: str | None
    is_primary: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class PartnerResponse(BaseModel):
    id: UUID
    organization_id: UUID
    name: str
    name_kana: str | None
    company_type: str
    tax_id: str | None
    address: str | None
    phone: str | None
    email: str | None
    website: str | None
    representative_name: str | None
    employee_count: int | None
    established_year: int | None
    specializations: list[str] | None
    license_info: dict | None
    insurance_info: dict | None
    status: str
    rating: float | None
    registered_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PartnerDetailResponse(PartnerResponse):
    contacts: list[PartnerContactResponse] = []
    contracts_summary: list[dict] = []


# ============================================
# 契約 (Contract)
# ============================================
CONTRACT_TYPES = [
    "main_contract", "subcontract", "supply", "service", "lease", "consulting", "other",
]
CONTRACT_STATUSES = ["draft", "pending_approval", "active", "completed", "terminated"]


class ContractCreate(BaseModel):
    partner_id: UUID
    project_id: UUID | None = None
    contract_number: str | None = None
    title: str = Field(min_length=1, max_length=500)
    contract_type: str
    amount: float = Field(gt=0)
    currency: str = "JPY"
    start_date: date
    end_date: date | None = None
    terms: str | None = None


class ContractUpdate(BaseModel):
    partner_id: UUID | None = None
    project_id: UUID | None = None
    contract_number: str | None = None
    title: str | None = None
    contract_type: str | None = None
    # 作成時(ContractCreate)と同じく正値のみ許可する。
    # 無検証だと更新経由で 0/負値の契約金額を登録できてしまう。
    amount: float | None = Field(default=None, gt=0)
    currency: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    status: str | None = None
    terms: str | None = None


class ContractSignRequest(BaseModel):
    signed_by_our: UUID
    signed_by_partner: str = Field(min_length=1, max_length=255)


class ContractResponse(BaseModel):
    id: UUID
    organization_id: UUID
    partner_id: UUID | None
    project_id: UUID | None
    contract_number: str | None
    title: str
    contract_type: str
    amount: float
    currency: str
    start_date: date
    end_date: date | None
    status: str
    terms: str | None
    signed_by_our: UUID | None
    signed_by_partner: str | None
    signed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ============================================
# 評価 (Evaluation)
# ============================================
class EvaluationCreate(BaseModel):
    partner_id: UUID
    project_id: UUID | None = None
    overall_score: float = Field(ge=1.0, le=5.0)
    quality_score: float | None = Field(default=None, ge=1.0, le=5.0)
    safety_score: float | None = Field(default=None, ge=1.0, le=5.0)
    schedule_score: float | None = Field(default=None, ge=1.0, le=5.0)
    cost_score: float | None = Field(default=None, ge=1.0, le=5.0)
    communication_score: float | None = Field(default=None, ge=1.0, le=5.0)
    comment: str | None = None
    evaluation_period_start: date | None = None
    evaluation_period_end: date | None = None


class EvaluationResponse(BaseModel):
    id: UUID
    organization_id: UUID
    partner_id: UUID | None
    project_id: UUID | None
    evaluator_id: UUID
    overall_score: float
    quality_score: float | None
    safety_score: float | None
    schedule_score: float | None
    cost_score: float | None
    communication_score: float | None
    comment: str | None
    evaluation_period_start: date | None
    evaluation_period_end: date | None
    created_at: datetime

    model_config = {"from_attributes": True}


class PartnerRatingResponse(BaseModel):
    partner_id: UUID
    average_rating: float
    evaluation_count: int


# ============================================
# プロジェクトアサイン (ProjectAssignment)
# ============================================
ASSIGNMENT_STATUSES = ["planned", "active", "completed", "terminated"]


class AssignmentCreate(BaseModel):
    partner_id: UUID
    project_id: UUID
    contract_id: UUID | None = None
    role: str = Field(min_length=1, max_length=100)
    scope_of_work: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    status: str = "active"


class AssignmentResponse(BaseModel):
    id: UUID
    organization_id: UUID
    partner_id: UUID | None
    project_id: UUID
    contract_id: UUID | None
    role: str
    scope_of_work: str | None
    start_date: date | None
    end_date: date | None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}
