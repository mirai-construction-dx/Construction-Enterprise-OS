"""現場DX サービス — 日報・進捗・品質管理ロジック"""

import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import DailyReport, ProgressRecord, QualityCheck


def _derive_progress_percent(data: dict) -> None:
    """進捗率が未指定の場合、出来形数量（actual / planned）から算出する。"""
    if data.get("progress_percent") is not None:
        return
    planned = data.get("planned_quantity")
    actual = data.get("actual_quantity")
    if planned is not None and actual is not None and planned != 0:
        data["progress_percent"] = (actual / planned) * 100.0


def _parse_number(value: str | None) -> float | None:
    """自由文字列（例: "21.5 N/mm2"）から先頭の数値を取り出す。"""
    if value is None:
        return None
    match = re.search(r"[-+]?\d+(?:\.\d+)?", value)
    if not match:
        return None
    return float(match.group())


def _derive_conformance(data: dict) -> bool | None:
    """合否はクライアント申告ではなく、測定値と規格値の突合から導出する。"""
    measured = _parse_number(data.get("measured_value"))
    standard = _parse_number(data.get("standard_value"))
    if measured is None or standard is None:
        return None
    return measured >= standard


# ============================================
# 作業日報
# ============================================
async def create_daily_report(
    db: AsyncSession, data: dict
) -> DailyReport:
    report = DailyReport(**data)
    db.add(report)
    await db.flush()
    await db.refresh(report)
    return report


async def get_daily_report(
    db: AsyncSession, report_id: uuid.UUID
) -> DailyReport | None:
    return await db.get(DailyReport, report_id)


async def list_daily_reports(
    db: AsyncSession,
    organization_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    page: int = 1,
    per_page: int = 20,
) -> tuple[list[DailyReport], int]:
    query = select(DailyReport)
    count_query = select(func.count(DailyReport.id))

    if organization_id:
        query = query.where(DailyReport.organization_id == organization_id)
        count_query = count_query.where(DailyReport.organization_id == organization_id)
    if project_id:
        query = query.where(DailyReport.project_id == project_id)
        count_query = count_query.where(DailyReport.project_id == project_id)
    if status:
        query = query.where(DailyReport.status == status)
        count_query = count_query.where(DailyReport.status == status)
    if date_from:
        query = query.where(DailyReport.report_date >= date_from)
        count_query = count_query.where(DailyReport.report_date >= date_from)
    if date_to:
        query = query.where(DailyReport.report_date <= date_to)
        count_query = count_query.where(DailyReport.report_date <= date_to)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = query.order_by(DailyReport.report_date.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    items = list(result.scalars().all())

    return items, total


async def update_daily_report(
    db: AsyncSession, report: DailyReport, data: dict
) -> DailyReport:
    for key, value in data.items():
        if value is not None:
            setattr(report, key, value)
    report.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(report)
    return report


async def submit_daily_report(
    db: AsyncSession, report: DailyReport
) -> DailyReport:
    if report.status != "draft":
        raise ValueError("下書き以外の日報は提出できません。")
    report.status = "submitted"
    report.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(report)
    return report


async def approve_daily_report(
    db: AsyncSession, report: DailyReport, approved_by: uuid.UUID
) -> DailyReport:
    if report.status != "submitted":
        raise ValueError("提出済みの日報のみ承認できます。")
    report.status = "approved"
    report.approved_by = approved_by
    report.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(report)
    return report


# ============================================
# 出来形・進捗記録
# ============================================
async def create_progress_record(
    db: AsyncSession, data: dict
) -> ProgressRecord:
    _derive_progress_percent(data)
    record = ProgressRecord(**data)
    db.add(record)
    await db.flush()
    await db.refresh(record)
    return record


async def get_progress_record(
    db: AsyncSession, record_id: uuid.UUID
) -> ProgressRecord | None:
    return await db.get(ProgressRecord, record_id)


async def list_progress_records(
    db: AsyncSession,
    organization_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    status: str | None = None,
    page: int = 1,
    per_page: int = 20,
) -> tuple[list[ProgressRecord], int]:
    query = select(ProgressRecord)
    count_query = select(func.count(ProgressRecord.id))

    if organization_id:
        query = query.where(ProgressRecord.organization_id == organization_id)
        count_query = count_query.where(ProgressRecord.organization_id == organization_id)
    if project_id:
        query = query.where(ProgressRecord.project_id == project_id)
        count_query = count_query.where(ProgressRecord.project_id == project_id)
    if status:
        query = query.where(ProgressRecord.status == status)
        count_query = count_query.where(ProgressRecord.status == status)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = query.order_by(ProgressRecord.recorded_at.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    items = list(result.scalars().all())

    return items, total


async def update_progress_record(
    db: AsyncSession, record: ProgressRecord, data: dict
) -> ProgressRecord:
    for key, value in data.items():
        if value is not None:
            setattr(record, key, value)
    record.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(record)
    return record


async def get_progress_summary(
    db: AsyncSession, project_id: uuid.UUID, organization_id: uuid.UUID | None
) -> dict:
    query = select(ProgressRecord).where(ProgressRecord.project_id == project_id)
    if organization_id is not None:
        query = query.where(ProgressRecord.organization_id == organization_id)
    result = await db.execute(query)
    records = list(result.scalars().all())

    total_activities = len(records)
    status_counts = {"completed": 0, "in_progress": 0, "delayed": 0, "pending": 0}
    progress_sum = 0.0

    for r in records:
        if r.status in status_counts:
            status_counts[r.status] += 1
        if r.progress_percent is not None:
            progress_sum += float(r.progress_percent)

    overall_progress = (progress_sum / total_activities) if total_activities > 0 else 0.0

    return {
        "project_id": project_id,
        "total_activities": total_activities,
        "completed": status_counts["completed"],
        "in_progress": status_counts["in_progress"],
        "delayed": status_counts["delayed"],
        "pending": status_counts["pending"],
        "overall_progress": overall_progress,
    }


# ============================================
# 品質管理
# ============================================
async def create_quality_check(
    db: AsyncSession, data: dict
) -> QualityCheck:
    data["is_conforming"] = _derive_conformance(data)
    check = QualityCheck(**data)
    db.add(check)
    await db.flush()
    await db.refresh(check)
    return check


async def get_quality_check(
    db: AsyncSession, check_id: uuid.UUID
) -> QualityCheck | None:
    return await db.get(QualityCheck, check_id)


async def list_quality_checks(
    db: AsyncSession,
    organization_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    check_type: str | None = None,
    status: str | None = None,
    page: int = 1,
    per_page: int = 20,
) -> tuple[list[QualityCheck], int]:
    query = select(QualityCheck)
    count_query = select(func.count(QualityCheck.id))

    if organization_id:
        query = query.where(QualityCheck.organization_id == organization_id)
        count_query = count_query.where(QualityCheck.organization_id == organization_id)
    if project_id:
        query = query.where(QualityCheck.project_id == project_id)
        count_query = count_query.where(QualityCheck.project_id == project_id)
    if check_type:
        query = query.where(QualityCheck.check_type == check_type)
        count_query = count_query.where(QualityCheck.check_type == check_type)
    if status:
        query = query.where(QualityCheck.status == status)
        count_query = count_query.where(QualityCheck.status == status)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = query.order_by(QualityCheck.check_date.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    items = list(result.scalars().all())

    return items, total


async def update_quality_check(
    db: AsyncSession, check: QualityCheck, data: dict
) -> QualityCheck:
    for key, value in data.items():
        if value is not None:
            setattr(check, key, value)
    check.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(check)
    return check


async def get_quality_stats(
    db: AsyncSession, project_id: uuid.UUID, organization_id: uuid.UUID | None
) -> dict:
    query = select(QualityCheck).where(QualityCheck.project_id == project_id)
    if organization_id is not None:
        query = query.where(QualityCheck.organization_id == organization_id)
    result = await db.execute(query)
    checks = list(result.scalars().all())

    total_checks = len(checks)
    status_counts = {"passed": 0, "failed": 0, "pending": 0, "action_required": 0}
    conforming_count = 0
    determined_count = 0

    for c in checks:
        if c.status in status_counts:
            status_counts[c.status] += 1
        if c.is_conforming is not None:
            determined_count += 1
            if c.is_conforming:
                conforming_count += 1

    conformance_rate = (
        (conforming_count / determined_count) * 100 if determined_count > 0 else 0.0
    )

    return {
        "project_id": project_id,
        "total_checks": total_checks,
        "passed": status_counts["passed"],
        "failed": status_counts["failed"],
        "pending": status_counts["pending"],
        "action_required": status_counts["action_required"],
        "conformance_rate": conformance_rate,
    }
