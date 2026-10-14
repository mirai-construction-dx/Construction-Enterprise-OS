"""ERP データモデル — `erp` スキーマ。

モデル定義の本体は `models.py` にある。ここで明示的に再エクスポートするのは、
`Base.metadata` へモデルを登録するためである。

2026-10-14 実測の不具合:
    このファイルが空だったため `import src.models` しても何も登録されず、
    基盤 DDL の生成器（`scripts/db/generate_base_schema.py`）から見て
    「スキーマが一意でない: []」となり、`services/erp/migrations/000_base_schema.sql` が
    **一度も生成されていなかった**。結果として stg に `erp` スキーマ自体が存在せず、
    `GET /api/v1/erp/ledger/summary` が
    `UndefinedTableError: リレーション"erp.project_ledger"は存在しません` で 500 になっていた。
"""

from .models import Budget, CostItem, Invoice, LaborCost, ProjectLedger

__all__ = ["Budget", "CostItem", "Invoice", "LaborCost", "ProjectLedger"]
