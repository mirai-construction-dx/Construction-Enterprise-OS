"""アナリティクス ビジネスロジック"""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AnalyticsReport, DataPipeline, DataSource


# ============================================
# データソース
# ============================================
async def create_datasource(db: AsyncSession, data: dict) -> DataSource:
    ds = DataSource(**data)
    db.add(ds)
    await db.flush()
    await db.refresh(ds)
    return ds


async def get_datasource(
    db: AsyncSession, datasource_id: UUID, organization_id: UUID | None = None
) -> DataSource | None:
    """Fetch by id; when ``organization_id`` is given, only within that organization."""
    if organization_id is None:
        return await db.get(DataSource, datasource_id)
    stmt = select(DataSource).where(
        DataSource.id == datasource_id, DataSource.organization_id == organization_id
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def list_datasources(
    db: AsyncSession,
    organization_id: UUID | None = None,
    source_type: str | None = None,
    status: str | None = None,
    page: int = 1,
    per_page: int = 20,
) -> tuple[list[DataSource], int]:
    query = select(DataSource)
    count_query = select(func.count(DataSource.id))

    if organization_id is not None:
        query = query.where(DataSource.organization_id == organization_id)
        count_query = count_query.where(DataSource.organization_id == organization_id)
    if source_type:
        query = query.where(DataSource.source_type == source_type)
        count_query = count_query.where(DataSource.source_type == source_type)
    if status:
        query = query.where(DataSource.status == status)
        count_query = count_query.where(DataSource.status == status)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    offset = (page - 1) * per_page
    query = query.order_by(DataSource.created_at.desc()).offset(offset).limit(per_page)
    result = await db.execute(query)
    items = list(result.scalars().all())

    return items, total


async def update_datasource(
    db: AsyncSession, ds: DataSource, data: dict
) -> DataSource:
    for key, value in data.items():
        if value is not None:
            setattr(ds, key, value)
    return ds


async def delete_datasource(db: AsyncSession, ds: DataSource) -> None:
    await db.delete(ds)


async def test_datasource_connection(ds: DataSource) -> dict:
    return {
        "success": True,
        "message": f"Connection to {ds.source_type} source '{ds.name}' simulated successfully",
        "source_type": ds.source_type,
    }


# ============================================
# パイプライン
# ============================================
async def create_pipeline(db: AsyncSession, data: dict) -> DataPipeline:
    pipeline = DataPipeline(**data)
    db.add(pipeline)
    await db.flush()
    await db.refresh(pipeline)
    return pipeline


async def get_pipeline(
    db: AsyncSession, pipeline_id: UUID, organization_id: UUID | None = None
) -> DataPipeline | None:
    """Fetch by id; when ``organization_id`` is given, only within that organization."""
    if organization_id is None:
        return await db.get(DataPipeline, pipeline_id)
    stmt = select(DataPipeline).where(
        DataPipeline.id == pipeline_id, DataPipeline.organization_id == organization_id
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def list_pipelines(
    db: AsyncSession,
    organization_id: UUID | None = None,
    status: str | None = None,
    source_id: UUID | None = None,
    page: int = 1,
    per_page: int = 20,
) -> tuple[list[DataPipeline], int]:
    query = select(DataPipeline)
    count_query = select(func.count(DataPipeline.id))

    if organization_id is not None:
        query = query.where(DataPipeline.organization_id == organization_id)
        count_query = count_query.where(
            DataPipeline.organization_id == organization_id
        )
    if status:
        query = query.where(DataPipeline.status == status)
        count_query = count_query.where(DataPipeline.status == status)
    if source_id:
        query = query.where(DataPipeline.source_id == source_id)
        count_query = count_query.where(DataPipeline.source_id == source_id)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    offset = (page - 1) * per_page
    query = (
        query.order_by(DataPipeline.created_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    result = await db.execute(query)
    items = list(result.scalars().all())

    return items, total


async def update_pipeline(
    db: AsyncSession, pipeline: DataPipeline, data: dict
) -> DataPipeline:
    for key, value in data.items():
        if value is not None:
            setattr(pipeline, key, value)
    return pipeline


async def delete_pipeline(db: AsyncSession, pipeline: DataPipeline) -> None:
    await db.delete(pipeline)


async def trigger_pipeline_run(
    db: AsyncSession, pipeline: DataPipeline
) -> dict:
    now = datetime.now(timezone.utc)
    pipeline.status = "running"
    pipeline.last_run = now
    return {
        "pipeline_id": pipeline.id,
        "status": "running",
        "started_at": now,
        "finished_at": None,
        "message": f"Pipeline '{pipeline.name}' triggered successfully",
    }


# ============================================
# レポート
# ============================================
async def create_report(db: AsyncSession, data: dict) -> AnalyticsReport:
    report = AnalyticsReport(**data)
    db.add(report)
    await db.flush()
    await db.refresh(report)
    return report


async def get_report(
    db: AsyncSession, report_id: UUID, organization_id: UUID | None = None
) -> AnalyticsReport | None:
    """Fetch by id; when ``organization_id`` is given, only within that organization."""
    if organization_id is None:
        return await db.get(AnalyticsReport, report_id)
    stmt = select(AnalyticsReport).where(
        AnalyticsReport.id == report_id, AnalyticsReport.organization_id == organization_id
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def list_reports(
    db: AsyncSession,
    organization_id: UUID | None = None,
    report_type: str | None = None,
    status: str | None = None,
    page: int = 1,
    per_page: int = 20,
) -> tuple[list[AnalyticsReport], int]:
    query = select(AnalyticsReport)
    count_query = select(func.count(AnalyticsReport.id))

    if organization_id is not None:
        query = query.where(AnalyticsReport.organization_id == organization_id)
        count_query = count_query.where(
            AnalyticsReport.organization_id == organization_id
        )
    if report_type:
        query = query.where(AnalyticsReport.report_type == report_type)
        count_query = count_query.where(AnalyticsReport.report_type == report_type)
    if status:
        query = query.where(AnalyticsReport.status == status)
        count_query = count_query.where(AnalyticsReport.status == status)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    offset = (page - 1) * per_page
    query = (
        query.order_by(AnalyticsReport.created_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    result = await db.execute(query)
    items = list(result.scalars().all())

    return items, total


async def update_report(
    db: AsyncSession, report: AnalyticsReport, data: dict
) -> AnalyticsReport:
    for key, value in data.items():
        if value is not None:
            setattr(report, key, value)
    return report


async def delete_report(db: AsyncSession, report: AnalyticsReport) -> None:
    await db.delete(report)


async def generate_report(
    db: AsyncSession, report: AnalyticsReport
) -> dict:
    return {
        "report_id": report.id,
        "generated_at": datetime.now(timezone.utc),
        "data": [
            {"metric": "sample_value_1", "value": 100},
            {"metric": "sample_value_2", "value": 200},
        ],
        "summary": {"total_records": 2, "report_type": report.report_type},
    }


async def export_report(
    db: AsyncSession, report: AnalyticsReport, export_format: str
) -> dict:
    generated = await generate_report(db, report)
    if export_format == "csv":
        content = "metric,value\nsample_value_1,100\nsample_value_2,200\n"
    else:
        content = __import__("json").dumps(generated["data"], default=str)
    return {
        "report_id": report.id,
        "format": export_format,
        "generated_at": generated["generated_at"],
        "content": content,
    }
