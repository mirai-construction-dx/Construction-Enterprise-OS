# RBAC ロールモデル（確定版）

ADR-0004（テナント分離）で `organization_id` の境界は確定したが、**どの操作に
どのロールを要求するか**は未確定だった（Step 9 の blocker）。本書で確定する。

## 1. ロール（auth サービス `DEFAULT_ROLES` を正典とする）

| ロール | 意味 | テナント境界 |
|---|---|---|
| `admin` | システム管理者 | **全組織横断**（ADR-0004: `is_cross_org_admin`） |
| `site_manager` | 現場所長 | 自組織のみ |
| `site_supervisor` | 現場監督（日次管理と承認） | 自組織のみ |
| `site_worker` | 現場作業員（閲覧・報告） | 自組織のみ |
| `inspector` | 検査官（品質・安全の監査） | 自組織のみ |
| `accountant` | 経理担当（ERP・経営データ） | 自組織のみ |
| `readonly` | 閲覧専用 | 自組織のみ |

- **横断（cross-org）は `admin` のみ**。他ロールは JWT の `org` に束縛される。
- `roles` が空（`[]`/`null`）のトークンは**ロール必須操作を実行できない**（fail-closed）。

## 2. 操作カテゴリと必要ロール

| カテゴリ | 例 | 必要ロール |
|---|---|---|
| 参照（read） | 一覧・詳細・サマリー | 任意の有効トークン（自組織） |
| 作成・更新（write） | 日報・出来形・品質記録の作成 | 任意の有効ロール（自組織） |
| **承認（approve）** | 施工計画書・日報・文書ステータス・原価 | `admin` / `site_manager` / `site_supervisor` |
| **否認（reject）** | 同上 | 承認と同一 |
| **削除（delete）** | 文書・マスタの削除 | `admin` / `site_manager`（＋対象ドメインの管理ロール） |
| **財務（finance）** | 原価承認・請求確定・台帳更新 | `admin` / `accountant` |
| **検査（inspect）** | 品質・安全の合否確定 | `admin` / `inspector` |
| 組織横断（cross-org） | 全社サマリー・組織跨ぎ参照 | `admin` のみ |

## 3. 実装パターン（サービス共通）

各サービスは `middleware/tenant.py`（ADR-0004）に加えて、次の小さなヘルパーを
持つ。ドメイン固有ロールは各サービスの定数として定義する。

```python
# middleware/auth.py（サービス共通の形）
APPROVAL_ROLES = frozenset({"admin", "site_manager", "site_supervisor"})
MANAGEMENT_ROLES = frozenset({"admin", "site_manager"})

def require_any_role(user: TokenData, allowed: frozenset[str]) -> None:
    if not (set(user.roles or []) & allowed):
        raise HTTPException(403, {"code": "FORBIDDEN", "message": "..."})
```

- 実行者・承認者の同定は必ずトークン `sub`（`UUID(user.sub)`）から行う（ボディ・クエリは信用しない）。
- 組織は `scope_org`/`token_org`/`create_org`（ADR-0004）のみで決める。

## 4. 現状の適用状況

| サービス | 適用済み |
|---|---|
| `document` | 承認（approved/rejected）＝承認ロール、削除＝ロール必須 |
| `erp` | 原価承認＝財務ロール（`admin`/`accountant`） |
| `construction` | 施工計画書の承認＝承認ロール、承認者＝トークン sub |
| `safety` | 行為者同定（報告者・調査者・検査者＝トークン sub） |
| `auth` | `require_role(role_name)`（既存） |
| その他 | 参照/作成のみ（ロール検査は未適用） |

## 5. 展開方針（次段階）

機微度の高い順に適用する。各適用は当該サービスのテストで担保し、既存の
「現状挙動」テストは必要に応じて ADR-0004 / RBAC セマンティクスへ追随させる。

1. **承認・否認**（workflow / iot アラート / partner 契約 / safety 是正）
2. **削除**（各サービスの DELETE 系）
3. **財務**（erp の請求・予算確定）
4. **検査**（safety / vision / field-dx の合否確定）

## 6. 未確定事項

- 組織階層（会社→事業部→現場）に応じた**スコープ付きロール**（例: 特定現場のみの所長）は未定義。
  現状は組織単位のロールのみ。必要になった時点で別 ADR とする。
- `auth` の `Permission` / `RolePermission`（DB 43 権限）と本ロールモデルの**突き合わせ**は
  サービス横断の課題として残る（auth は DB 権限、各サービスはロール文字列で判定している）。
