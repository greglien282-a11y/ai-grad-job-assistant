# M1-1B-1：经历事实 HTTP API

本阶段只交付后端，基于 main `615b33d`。M1-1B-2 开发 React 工作台，M1-1B-3 做浏览器端到端及体验验收；每阶段单独测试、PR 和审查。无真实 AI、简历生成或静态原型变更。

## 启动与配置

在 `apps/api` 使用已有 Python 3.12 虚拟环境：

```powershell
.venv/Scripts/python.exe -m pip install -r requirements.txt
# 将连接地址放入 apps/api/.env（被 Git 忽略），或导出 DATABASE_URL。
.venv/Scripts/python.exe -m app
```

开发启动器只监听 `127.0.0.1:8000`，加载本目录 `.env`，并关闭 Uvicorn access log，以免拒绝的查询参数也被服务器记入日志。健康检查无需数据库；业务接口需要 DATABASE_URL 和已完成迁移。

迁移和测试显式加载本地配置（测试库必须独立，不能使用真实个人数据）：

```powershell
.venv/Scripts/python.exe -c "from dotenv import load_dotenv; load_dotenv('.env'); from alembic.config import Config; from alembic import command; command.upgrade(Config('alembic.ini'), 'head'); command.check(Config('alembic.ini'))"
.venv/Scripts/python.exe -c "from dotenv import load_dotenv; load_dotenv('.env'); import pytest; raise SystemExit(pytest.main(['-q','-ra']))"
```

本次获用户单独授权后，使用官方 EDB 安装器（通过 winget 元数据核验 SHA-256）安装 PostgreSQL 16.15，仅安装服务及命令行。服务 `postgresql-x64-16`，路径 `C:\Program Files\PostgreSQL\16`，监听 `127.0.0.1:5432`，没有修改系统 PATH 或添加网络防火墙规则。

`pathwise_dev` 和 `pathwise_test` 分别拥有同名数据库，均非超级用户且没有创建角色或数据库的权限。数据库撤销 PUBLIC 连接权限。随机连接密码只在被 Git 忽略的 `apps/api/.env` 中；管理员恢复凭证在 `apps/api/.venv/postgresql-local.json`，两文件均限制为当前 Windows 用户访问。不得复制其内容到聊天、Issue、PR 或日志。

## HTTP 合同

所有路径以 `/api/v1/experience` 开头。OpenAPI 见本地 `/docs`，响应模型不包含数据库凭证摘要。

- `POST /sessions`：`{raw_input}` → 201，返回 session_id、project_id、initial_turn_id、status、access_token。令牌仅此时返回，需妥善暂存。
- `GET /sessions/{id}`：完整当前状态，含 projects、turns、facts、evidence、history。
- `POST /sessions/{id}/turns`：`{content}` → 201，追加原始用户回合。
- `POST /projects/{id}/facts`：`{statement, source_turn_ids}` → 201，新增 pending 事实。来源必须是该会话的用户回合，且无重复。
- `PATCH /facts/{id}`：显式操作及 expected_version，返回更新后的事实。
- `POST /sessions/{id}/end`：结束会话；重复结束返回同一只读状态。
- `GET /sessions/{id}/export`：下载 JSON，含 format_version、exported_at 和完整会话数据。
- `DELETE /sessions/{id}`：204，原始回合、事实、来源、核实依据和历史均事务性级联删除。

除创建会话外，必须使用 `Authorization: Bearer <access_token>`。所有业务接口拒绝查询参数；凭证不得出现在 URL、日志或导出文件。React 阶段仅在开发期 sessionStorage 中保存 ID 与凭证，不在 URL/localStorage 放置它们，不将完整资料存入浏览器持久化存储。

每个写请求一个事务，function-scope 依赖保证提交完成后才发送成功响应；提交失败不会先返回成功。读取/导出也锁定父会话，避免数据在序列化期间变化。结束后可读、导出、删除，不能追加或修改。

## 事实版本与来源

updated_at 保留展示用途，不用于乐观并发识别：应用时钟可能重复或回退，不能保证唯一稳定。第二版 Alembic 迁移增加 NOT NULL 正整数 version，现有事实回填 1；ORM 的 version_id_col 在 UPDATE 条件中比较旧版本并递增。服务获取父会话锁、刷新事实后检查客户端版本，任何修改操作都必须提供 expected_version。

PATCH 的 JSON 操作互斥，不能一次编辑并确认：

```json
{"action":"edit","expected_version":1,"statement":"用户补充的新陈述"}
```

编辑成功返回 version 2、pending 和 user_edit 来源。用户看过该内容后，才可提交：

```json
{"action":"confirm","expected_version":2}
```

另外支持 reject 与 verify_material。后者必须已有用户确认，并额外提供 material_reference、basis。状态、陈述或核实依据的变更都递增事实版本；过期版本返回 409，不新增核实记录或历史。

facts 返回 source_kind、source_turn_ids、source_change_id、original_source_turn_ids，沿用 M1-1A 来源修复。编辑后的当前来源是 FactChange 用户编辑事件，旧回合仅是历史起点。user_confirmed 表示用户确认，不是客观核验。材料记录明确标为“用户提供材料并自行核实”，不表示平台独立认证；尚不上传或认证附件。

快照记录版本；新版编辑事件按版本优先选择当前来源，兼容旧记录没有 version 的情况。时间仅用于展示，不用于最新编辑判定。

## 错误与请求边界

错误统一为 `{error: {code, message}}`，不返回拒绝的原始输入、SQL、异常细节或连接凭证：

- 401 credential_required：无有效 Bearer 头，附 WWW-Authenticate。
- 404 resource_unavailable：资源不存在或令牌不属于它，响应一致。
- 409 version_conflict：过期版本，客户端重新读取并让用户审核后再提交，不能静默重试。
- 409 state_conflict / data_conflict：非法状态或数据约束冲突。
- 422 invalid_request：字段、来源、核实输入不合法。
- 413 body_too_large：实际 body 超过 64 KiB，包括没有/伪造 Content-Length 的分块请求。
- 503 database_unavailable：数据库未配置、不可用或事务失败。
- 500 internal_error：意外错误的安全兜底。

输入字符串不允许纯空白，最长 10000 字符；新增事实最多关联 32 个来源回合。额外字段被拒绝，版本只能为正整数。响应 no-store、nosniff。CORS 仅允许配置的开发来源、实际业务方法及 Authorization/Content-Type/Accept，错误也有正确的 CORS 头。

生产部署必须 HTTPS，设置 REQUIRE_HTTPS=true；由可信反向代理终止 TLS 时，仅将该代理加入 Uvicorn forwarded-allow-ips，禁止信任任意 X-Forwarded-Proto。代理同样不得记录 Authorization、请求体或原始查询字符串。本阶段启动器限本机；公开部署的限流、账户恢复与完整运维策略另行验收。

## 验证

本机 PostgreSQL 16 / Python 3.12：40 项后端测试通过，无跳过。覆盖空库与已有数据迁移、独立连接持久化、实际并行请求、所有写操作版本冲突与回滚、HTTP 来源历史、跨会话授权、导出排除凭证、结束/删除级联、HTTP 输入上限及安全错误。前后端 CI 延用已有 PostgreSQL 服务；PR 记录实际 CI 结果。

另外启动真实 Uvicorn 并经 `127.0.0.1:8000` HTTP 调用创建会话/新增事实/确认/过期版本 409/读取/导出/删除，冒烟检查通过；测试会话已删除，临时 API 进程已停止，数据库服务保留供后续开发。
