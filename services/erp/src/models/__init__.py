"""erp データモデル — erp スキーマ

他のサービスと同様に `import src.models` だけで全テーブルが
`Base.metadata` へ登録されるようにする。
DDL 生成 (`scripts/db/generate_base_schema.py`) と Alembic autogenerate は
この import に依存するため、テーブル定義の再輸出を省略しないこと。
"""

from .base import Base
from .models import (
    Budget,
    CostItem,
    Invoice,
    LaborCost,
    ProjectLedger,
)

__all__ = [
    "Base",
    "Budget",
    "CostItem",
    "Invoice",
    "LaborCost",
    "ProjectLedger",
]
