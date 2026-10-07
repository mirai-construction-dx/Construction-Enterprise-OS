"""Prompt Template CRUD サービス"""

import logging
from uuid import UUID

from jinja2 import TemplateError
from jinja2.sandbox import SandboxedEnvironment
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import PromptTemplate

logger = logging.getLogger(__name__)

# 利用者が保存したテンプレート本文を描画するための環境。
# 非サンドボックスの jinja2.Template は任意の Python 式（属性・クラス階層の走査）を
# 評価でき、SSTI 経由の RCE に至るため使用しない（Jinja2 公式の推奨に従う）。
_TEMPLATE_ENV = SandboxedEnvironment(autoescape=False)


def render_user_template(template_text: str, variables: dict | None = None) -> str:
    """テンプレート本文をサンドボックス内で描画する。

    禁止された式（属性アクセス等）は ValueError として返し、呼び出し側が 4xx に変換する。
    """
    try:
        return _TEMPLATE_ENV.from_string(template_text).render(**(variables or {}))
    except TemplateError as exc:  # SecurityError を含む
        raise ValueError(f"プロンプトテンプレートを評価できません: {exc}") from exc

DEFAULT_TEMPLATES = [
    {
        "name": "safety_report_assistant",
        "description": "安全報告書作成支援",
        "category": "safety_report",
        "system_prompt": "あなたは建設現場の安全管理の専門家です。提供された情報に基づいて、安全報告書の作成を支援します。",
        "user_prompt_template": "以下の現場情報をもとに安全報告書を作成してください。\n現場名: {{ site_name }}\n期間: {{ period }}\n作業内容: {{ work_description }}\n特記事項: {{ notes }}",
        "model": "gpt-4",
        "temperature": 0.3,
        "max_tokens": 3000,
    },
    {
        "name": "construction_qa",
        "description": "建設技術Q&A",
        "category": "construction_qa",
        "system_prompt": "あなたは建設工学の専門家です。建設技術、工法、材料、規格に関する質問に正確に回答してください。",
        "user_prompt_template": "質問: {{ question }}\n\n専門的な観点から回答してください。",
        "model": "gpt-4",
        "temperature": 0.5,
        "max_tokens": 2000,
    },
    {
        "name": "document_summarizer",
        "description": "文書要約",
        "category": "document_summary",
        "system_prompt": "あなたは建設文書の要約専門家です。与えられた文書を構造化して要約してください。",
        "user_prompt_template": "以下の文書を要約してください。\n文書タイトル: {{ title }}\n\n{{ content }}\n\n要約形式: {{ format }}",
        "model": "gpt-4",
        "temperature": 0.2,
        "max_tokens": 1500,
    },
    {
        "name": "specification_checker",
        "description": "仕様書チェック",
        "category": "specification_check",
        "system_prompt": "あなたは建設仕様書のレビュー専門家です。仕様書の不整合、不足項目、改善点を指摘してください。",
        "user_prompt_template": "以下の仕様書をレビューしてください。\nプロジェクト: {{ project_name }}\n\n仕様書内容:\n{{ specification_content }}\n\nチェック観点: {{ check_points }}",
        "model": "gpt-4",
        "temperature": 0.3,
        "max_tokens": 2500,
    },
    {
        "name": "hazard_predictor",
        "description": "危険予知アシスタント",
        "category": "risk_assessment",
        "system_prompt": "あなたは建設現場の安全管理専門家です。作業内容から潜在的な危険を予測し、対策を提案してください。",
        "user_prompt_template": "以下の作業内容について危険予知活動（KY）を実施してください。\n現場条件: {{ site_conditions }}\n作業内容: {{ work_description }}\n使用機械: {{ equipment }}\n作業員数: {{ worker_count }}名",
        "model": "gpt-4",
        "temperature": 0.4,
        "max_tokens": 2000,
    },
]


class PromptService:
    @staticmethod
    async def seed_templates(
        db: AsyncSession, organization_id: UUID, created_by: UUID | None = None
    ):
        existing = await db.execute(
            select(func.count(PromptTemplate.id)).where(
                PromptTemplate.organization_id == organization_id
            )
        )
        if (existing.scalar() or 0) > 0:
            return

        for tmpl in DEFAULT_TEMPLATES:
            template = PromptTemplate(
                organization_id=organization_id,
                created_by=created_by,
                **tmpl,
            )
            db.add(template)
        await db.flush()
        logger.info(
            f"Seeded {len(DEFAULT_TEMPLATES)} prompt templates for org {organization_id}"
        )

    @staticmethod
    async def create_template(
        db: AsyncSession,
        organization_id: UUID,
        data: dict,
        created_by: UUID | None = None,
    ) -> PromptTemplate:
        template = PromptTemplate(
            organization_id=organization_id,
            created_by=created_by,
            **data,
        )
        db.add(template)
        await db.flush()
        return template

    @staticmethod
    async def list_templates(
        db: AsyncSession,
        organization_id: UUID,
        page: int = 1,
        per_page: int = 20,
        category: str | None = None,
        is_active: bool | None = None,
    ) -> tuple[list[PromptTemplate], dict]:
        stmt = select(PromptTemplate).where(
            PromptTemplate.organization_id == organization_id
        )
        if category:
            stmt = stmt.where(PromptTemplate.category == category)
        if is_active is not None:
            stmt = stmt.where(PromptTemplate.is_active == is_active)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await db.execute(count_stmt)).scalar() or 0

        stmt = stmt.order_by(PromptTemplate.created_at.desc())
        stmt = stmt.offset((page - 1) * per_page).limit(per_page)
        result = await db.execute(stmt)
        templates = list(result.scalars().all())

        from math import ceil

        pagination = {
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": max(1, ceil(total / per_page)),
        }
        return templates, pagination

    @staticmethod
    async def get_template(
        db: AsyncSession,
        template_id: UUID,
        organization_id: UUID,
    ) -> PromptTemplate | None:
        stmt = select(PromptTemplate).where(
            PromptTemplate.id == template_id,
            PromptTemplate.organization_id == organization_id,
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def update_template(
        db: AsyncSession,
        template_id: UUID,
        organization_id: UUID,
        data: dict,
    ) -> PromptTemplate | None:
        template = await PromptService.get_template(db, template_id, organization_id)
        if not template:
            return None
        for key, value in data.items():
            if value is not None:
                setattr(template, key, value)
        await db.flush()
        return template

    @staticmethod
    async def delete_template(
        db: AsyncSession,
        template_id: UUID,
        organization_id: UUID,
    ) -> bool:
        template = await PromptService.get_template(db, template_id, organization_id)
        if not template:
            return False
        await db.delete(template)
        await db.flush()
        return True
