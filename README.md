# 数据安全计算与隐私保护平台

面向数据脱敏、差分隐私、安全聚合与访问审计的数据安全计算与隐私保护平台。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/WorkbenchView.vue|tsx  全部模块共享工作台
│   ├── src/data/modules.ts              18个业务模块配置
│   ├── src/api/              统一请求封装
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/resource.py  通用查询/导出/登记/动作接口
│   ├── app/services/<key>.py    每个模块独立领域逻辑
│   ├── app/services/base.py     共享服务骨架
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm ci
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 脱敏规则 | `mask_rule` | 脱敏规则 | 规则编号、目标字段、脱敏算法 |
| 隐私预算 | `privacy_budget` | 隐私预算 | 预算编号、数据集名称、总预算Epsilon |
| 噪声引擎 | `noise_engine` | 噪声配置 | 配置编号、噪声机制、Epsilon值 |
| 安全聚合 | `secure_agg` | 聚合任务 | 任务编号、数据源列表、聚合函数 |
| 访问审计 | `access_audit` | 审计记录 | 记录编号、访问主体、目标资源 |
| 授权审批 | `grant_approval` | 授权申请 | 申请编号、申请人、目标数据 |
| 分级分类 | `classify_tag` | 分级标签 | 标签编号、数据资源、安全等级 |
| 联邦训练 | `federated_train` | 训练任务 | 任务编号、参与节点、模型类型 |
| 梯度加密 | `gradient_encrypt` | 加密配置 | 配置编号、加密方案、密钥长度 |
| 假名化 | `pseudonym` | 假名映射 | 映射编号、原始标识、假名标识 |
| K匿名检查 | `k_anonymity` | 匿名检查 | 检查编号、数据集名称、准标识符列 |
| 差分查询 | `differential_sql` | 查询记录 | 查询编号、查询语句、查询用户 |
| 密文索引 | `encrypt_index` | 索引条目 | 条目编号、加密域、索引类型 |
| 数据水印 | `watermark` | 水印记录 | 水印编号、目标数据集、水印算法 |
| 同意登记 | `consent_registry` | 同意记录 | 记录编号、数据主体、处理目的 |
| 风险扫描 | `risk_scan` | 扫描任务 | 任务编号、扫描范围、扫描规则 |
| 策略下发 | `deploy_policy` | 策略分发 | 分发编号、策略内容、目标节点 |
| 异常检测 | `anomaly_detect` | 异常规则 | 规则编号、检测维度、检测算法 |

## 约定

- 全部模块共享`frontend/src/views/WorkbenchView.vue|tsx`和一套资源路由。
- 每个模块仍保留独立`backend/app/services/<模块>.py`；纯前端保留
  `frontend/src/domain/<模块>.ts`，用于承载真实业务差异并维持36题位容量。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

## 结果复核包（差分查询复核）

噪声引擎只维护参数配置，结果复核包负责把差分查询**一次实际执行**的结果、参数、费用
三联绑定重拿为证据，入口在「差分查询」页头部与侧边栏「结果复核包」（路由
`/review_package`，后端服务 `app/services/review_package.py`）。

核对规则：

- 三联核对：原输入/结果（已执行、有注入与返回行）、费用（消耗Epsilon + 费用回执 +
  预算剩余）、参数（执行声明版本，由直接配置引用或原执行参数证据印证）全部通过才可复核。
- 复核包锁定执行时刻的参数版本；参数轮换后当前新配置不得写为旧结果的输入。
- 旧执行丢失直接配置引用时，只接受指纹与台账规范指纹一致、且版本与执行声明相符的
  原执行参数证据；错版/篡改证据只留痕、不采信。
- 迟到的有效补证自动归入该执行**已打开的复核申请**（待补证→待提交），不产生新待办。
- 重新执行签发新复核包，原执行回执置为「已替代」并保留可查。
- 提交时重新做三联核对，无法补证的记录保持「待补证」并写明不可复核原因，不会被签成旧结果。

接口前缀 `/api/review`：`GET /param-versions`、`POST /packages`（`reexecute=true`
表示重新执行）、`GET /packages/{id}`（刷新即重算资格）、`POST /evidence`、
`POST /requests`、`POST /requests/{id}/submit`。复核包/申请/证据为内部台账
（`store.INTERNAL_TABLES`），不出现在运营概览，也不走通用 `/api/{module}` 资源路由。

种子数据：`noise_engine` 含 v1.0–v3.0（v3.0 当前生效、v2.0 已轮换停用）；
`differential_sql` 的 DIFF-0004/0005 是两笔缺直接配置引用的旧执行，分别用于演示
"迟到的 v2 原执行回执补证成功"与"仅有新 v3 配置、不可复核"。

领域：数据工程
子方向：数据分析与数据应用
