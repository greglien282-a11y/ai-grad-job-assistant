# M1-1A：经历事实库持久化基础

本阶段对应 Issue #1 的数据基础部分。使用 PostgreSQL、SQLAlchemy 2、Alembic；服务函数可在事务中调用，HTTP 业务接口和 React 工作台留到 M1-1B。没有接入 LLM，也不生成简历文案。

## 表与约束

- `experience_sessions`：UUID、随机会话凭证的 SHA-256 摘要、active/ended 状态、创建及更新时间。凭证原文只在创建时返回。
- `experience_projects`：所属会话、原始自述 `raw_input`、可选标题。编辑事实不会覆盖原始输入。
- `conversation_turns`：会话、user/assistant 角色、原始内容、创建时间。
- `experience_facts`：所属项目及会话、陈述、四种确认状态、当前材料核实记录、时间。
- `fact_sources`：事实与来源回合的多对多关联。复合外键保证事实、项目和回合属于同一会话；服务仅接受用户回合作为事实来源。
- `fact_evidence`：材料引用、用户核实依据、核实角色与时间。编辑事实后解除当前引用，旧记录保留供历史追溯；本阶段不上传或验证附件本身。
- `fact_changes`：创建、编辑、状态变更的前后 JSONB 快照、来源回合 ID、材料核实 ID、操作角色及时间。服务只追加历史，不覆盖。

UUID 与时区时间由应用产生。表不依赖当前运行模型自动建表；首版迁移是独立冻结的 DDL。删除会话时相关数据级联删除。历史表是应用级追加记录，不是数据库管理员不可篡改的审计日志。

## 状态规则与事务

新事实总为 `pending`。允许 pending → user_confirmed/rejected、user_confirmed → evidence_supported/rejected、evidence_supported → rejected。被拒绝的事实不能直接确认，须先修改，再确认。修改任何状态的陈述都会回到 pending，编辑与确认不能同一次调用完成。

材料核实必须先有用户确认，再由持有会话凭证的用户提供非空材料引用和核实依据。`evidence_supported` 有数据库非空约束与同事实外键，模型声明不能成为核实入口；它仍不代表独立第三方认证。

`app/facts.py` 提供最小创建、读取授权、追加用户回合、新增/修改/确认/拒绝事实、结束会话以及可引用事实查询。调用者必须使用 `with db.begin():`，负责提交/回滚。写入时锁父会话，串行化服务内写操作；结束后只读。业务 HTTP 请求模型、凭证传输和错误映射在 M1-1B 实现。

## 本地环境

优先 Python 3.12 独立虚拟环境，与 CI 保持一致。开发机器存在应用附带的 Python 3.12.14，未修改系统 Python 3.14：

```powershell
# 在仓库根目录，用你可用的 Python 3.12 路径创建虚拟环境
py -3.12 -m venv apps/api/.venv
cd apps/api
.venv/Scripts/python.exe -m pip install -r requirements.txt
```

若 `py -3.12` 找不到解释器，使用已有 3.12 的绝对路径；不要默默改用其他版本。

本机检查未发现 Docker 或 PostgreSQL 命令。本阶段用 GitHub Actions PostgreSQL 16 服务完成真实持久化验收，无需安装系统软件。日常开发任选：已有 Docker Desktop 可运行根目录 `docker compose up -d db`；已有本机 PostgreSQL 可创建开发和测试数据库。Docker Desktop 安装成本包括容器运行环境；本机 PostgreSQL 安装需要服务和账户配置。安装任一路径均需用户先确认。

有数据库后，在 `apps/api` 执行（示例凭证仅供本机合成数据）：

```powershell
$env:DATABASE_URL='postgresql+psycopg://pathwise_dev:change-me-for-local-development@127.0.0.1:5432/pathwise_dev'
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m alembic check
# 单独创建空的 pathwise_test 数据库；不要指向真实业务数据。
$env:TEST_DATABASE_URL='postgresql+psycopg://pathwise_dev:change-me-for-local-development@127.0.0.1:5432/pathwise_test'
.venv/Scripts/python.exe -m pytest -q -ra
```

环境变量由 shell 显式提供，不自动加载根目录 `.env`。缺少 DATABASE_URL 不影响原健康检查；连接数据库时会明确报错。不得将连接凭证、会话令牌或真实用户资料提交到仓库。

## 验证方式

PostgreSQL 测试为每例创建随机 schema，并在结束时仅删除该 schema。会测试空库迁移、降级/重建、模型迁移一致性、提交后重新读取、确认和编辑历史、证据保留、拒绝与非法转换、越权和跨会话来源、数据库约束、级联删除及事务回滚。全部使用合成课程项目数据。

本地无 TEST_DATABASE_URL 时集成用例明确跳过；CI 缺少它则失败，不能以跳过冒充通过。CI 先在空库运行 upgrade head 和 alembic check，再执行全部 Pytest，并保留既有前端测试/构建。实际测试结果以 PR 的 CI 和交付记录为准。
