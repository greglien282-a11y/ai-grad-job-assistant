# Windows 本机实验库初始化工具（待审查，尚未执行）

基线 main `eb7a5e18cf54776c83886d7d2ad23ef071df1fa7`。本次只开发与离线测试，**未运行真实初始化、未读取现有管理员恢复凭据、未创建角色/数据库/收费授权，真实供应商请求与费用均为 0**。不得将代码交付理解为执行许可；审查后仍须负责人明确批准执行。

## 未来人工启动

使用当前 Windows 用户的普通、可交互 PowerShell，不开转录或调试，不需要以 Windows 管理员运行。在仓库根目录执行：

```powershell
& .\apps\api\.venv\Scripts\python.exe .\scripts\initialize_probe_database.py
```

工具显示唯一三个目标并进行只读预检，只有完整输入以下短语才允许保存新凭据及创建对象：

```text
CREATE pathwise_probe AND TWO RESTRICTED ROLES
```

不支持 `--yes`、自定义目标、密码参数、重定向输入、环境启用开关、自动重试、自动迁移或数据库删除。连接目标固定 `127.0.0.1:5432`；管理连接仅 `postgres`，创建完成后仅以 owner/runner 连接新 `pathwise_probe`。不连接或读取 `pathwise_dev`。

## 密码和 SecretRef

每个密码独立调用 `secrets.token_urlsafe(32)`，使用 32 个操作系统安全随机字节（256 bit 随机熵）；两值相同时立即失败。密码不显示、不进参数/JSON/SQL/日志，仅保存为当前 Windows 用户的 Generic Credential，Persist=LOCAL_MACHINE（表示同一用户后续登录可用，不是所有用户可读）：

- owner：`Pathwise/PostgreSQL/127.0.0.1:5432/pathwise_probe/pathwise_probe_owner`
- runner：`Pathwise/PostgreSQL/127.0.0.1:5432/pathwise_probe/pathwise_probe_runner`

只对这两个固定目标执行 CredReadW/CredWriteW，不枚举其他条目、不读取 DeepSeek 凭据。现有目标（即使绑定不符）一律停止，不覆盖。新凭据保存并按目标、用户名、revision 读回核验，两个均成功后才创建 SQL 对象。原有受保护 `apps/api/.venv/postgresql-local.json` 只为管理连接临时读取，保持 ACL、位置及内容；不会复制到新文件。仅接受既有 `admin_user=postgres`、整数端口 5432、非空 admin_password 结构，其他值不用于连接目标。拒绝链接/重解析点及权限不合格的恢复文件。

凭据本机读取后只在短时进程及连接内使用；原生 buffer 擦除并 CredFree，关闭所有连接、释放 Python 引用。**Python/libpq/Windows 内部副本无法保证全部清零**。同一 Windows 用户的恶意程序及本机/数据库管理员仍属于信任边界；这不是独立企业 Secret broker。

## SCRAM 与日志保护的证据

使用 psycopg 的 `connection.pgconn.encrypt_password(..., b'scram-sha-256')`，它封装官方 libpq **PQencryptPasswordConn**。不实现自己的 SCRAM、盐或哈希协议。仅把生成的 `SCRAM-SHA-256$...` verifier 作为安全转义的 SQL Literal 发送；明文不进入 CREATE ROLE SQL。连接要求 libpq `require_auth=scram-sha-256`，拒绝转为明文/MD5/免密认证。项目现有 psycopg binary 提供此能力，缺少能力时失败，不降级。

官方依据（2026-10-16 核对）：

- [PostgreSQL 16 libpq 密码预处理](https://www.postgresql.org/docs/16/libpq-misc.html)：建议客户端预处理，避免明文进入 SQL 日志/活动视图。
- [PostgreSQL 16 CREATE ROLE](https://www.postgresql.org/docs/16/sql-createrole.html)：服务端直接存储已有 SCRAM verifier。
- [psycopg PGconn.encrypt_password](https://www.psycopg.org/psycopg3/docs/api/pq.html)：官方绑定接口。
- [CredWriteW](https://learn.microsoft.com/en-us/windows/win32/api/wincred/nf-wincred-credwritew)：原生写入会替换同名条目，因此本工具先检查并拒绝已有条目。
- [CREATE DATABASE](https://www.postgresql.org/docs/16/sql-createdatabase.html)：该命令在 autocommit 中执行，不能放入普通事务块。

专用工具全程禁用 Python logging，清除进程内 libpq PG* 环境覆盖并显式绑定 host/hostaddr/port/database/user，忽略密码文件。管理员会话在建角色前关闭核心 SQL statement/error/duration/sample 日志；**仅会话设置，不改全局配置、认证或服务**。需要 postgres SUPERUSER 执行这些会话保护，只有 CREATEDB/CREATEROLE 而没有 SUPERUSER 时本工具拒绝，不扩大角色权限。发现任意 preload library（可能有审计/日志钩子）则停止，待单独审查。verifier 本身同样敏感；核心保护无法约束恶意 DBA、外部抓包/调试器或所有第三方审计，应在可信本机使用。

## 执行顺序及权限

1. Windows + stdin/stdout 均为 TTY；取得本机命名 mutex，不读其他凭据。读取恢复文件并连接维护库，事务内 SET TRANSACTION READ ONLY。
2. 核验当前数据库/账号、PostgreSQL 16、SUPERUSER/CREATEDB/CREATEROLE、三目标均不存在，两个凭据目标均不存在；不满足则停止。
3. 明确人工确认后，取得维护库 session advisory lock，重新核对对象/权限/凭据；人工确认前不生成密码或写入。
4. 配置会话日志保护，生成并保存两份密码，读回确认。角色逐个事务创建，属性均为 LOGIN、NOSUPERUSER、NOCREATEDB、NOCREATEROLE、NOREPLICATION、NOBYPASSRLS、NOINHERIT；不授予角色成员关系。
5. autocommit 从 **template0** 建库，不复制用户资料；owner 固定，`ALLOW_CONNECTIONS false` 防止数据库 ACL 尚未收紧时被 PUBLIC 连接。
6. 事务内 REVOKE ALL ON DATABASE FROM PUBLIC（含 CONNECT/TEMP/CREATE），仅向 owner/runner GRANT CONNECT，然后开启连接。owner 保留数据库所有者权限；runner 没有 CREATE/TEMP。
7. 通过 Credential Manager 重新解析 owner，连接新库撤销 PUBLIC 在 public schema 的 CREATE。owner 自身保留所有者权限。随后只读检查无应用对象（无 Alembic、业务表或账本），并以 runner 实际认证，检查 CONNECT=true、数据库 CREATE/TEMP=false、所有永久 schema CREATE=false。
8. 维护库只读确认所有者、PUBLIC ACL、两个角色全部标志及零 membership。输出安全 JSON，关闭连接；不授业务表 DML 或账本函数 EXECUTE。

本机 mutex 与 PostgreSQL advisory lock 串行化本工具的合作进程。**CredWriteW 没有原子 create-only 参数**；同一用户的外部程序可在检查与写入间竞争，这是明确的本机信任限制。目标名在 CREATE 时再次由 PostgreSQL 唯一约束保护，竞争失败不复用对象。

## SecretRef 兼容（仅独立本机探针）

初始化成功输出 `database_credentials`，包含 role、secret_ref、secret_revision，没有密码。后续 `setup_probe_ledger.py` 可接受非秘密 owner 配置：

```json
{
  "database_credential": {
    "role": "pathwise_probe_owner",
    "secret_ref": "Pathwise/PostgreSQL/127.0.0.1:5432/pathwise_probe/pathwise_probe_owner",
    "secret_revision": 123
  }
}
```

123 只是格式示例，必须用实际输出的 revision。后续经独立授权执行零额度账本初始化后，加入实际 `ledger_id` 即为管理配置。普通 prepare/report/execute 必须使用 **runner** 的对应配置，不得使用 owner。配置读取只接受规定的三个字段，角色和目标绑定、revision 变化立即拒绝。SQLAlchemy URL 不含密码，使用 lazy creator 按需从 Credential Manager 解析；仅 setup 确认完成后才连接。

原有 `database_url` 私有配置保留读取兼容性，**不是新工具的默认保存方案**，本工具不生成明文密码 JSON。正常 Web/API 的 DATABASE_URL 方式完全不变。DB SecretRef 与 DeepSeek SecretRef 分离，没有新增供应商读取/发送路径。

## 失败与恢复

任一异常只输出固定错误码及 `attempted/completed` 步骤，不输出驱动异常/SQL/verifier/密码。不自动 DROP、删除凭据、覆盖、补调或重建。`attempted` 表示提交结果可能未知；不能假定对象不存在。连接断开或 Ctrl+C 均按未知处理，保留可能已创建的对象与凭据。如果 DB 已创建但 ACL 失败，新库可保持 ALLOW_CONNECTIONS=false，先人工核验，不盲目开放。

发生部分初始化后，重新运行创建会因已有对象/凭据而停止，不能作为恢复手段。仅只读获取两个固定引用的元数据，可人工执行：

```powershell
& .\apps\api\.venv\Scripts\python.exe .\scripts\initialize_probe_database.py --credential-status
```

该模式不读取管理员文件、不连接数据库、不生成密码、不写入/删除凭据；只读原生 entry 后擦除 buffer。即使创建进程在输出 revision 前崩溃，也能安全查看现有引用 metadata。不要把“查看 metadata”当作允许绕过已有对象检查。后续恢复动作必须明确审批；不支持自动补齐或密码重置。

## 本轮验证与未实测边界

新增测试均使用 Fake PostgreSQL adapter/Fake Win32 API/临时假配置，无真实管理员凭据、真实建库、真实固定 Credential Manager 写入或迁移。覆盖 256-bit RNG、不同密码、绑定/revision/拒绝覆盖、原生 buffer 清理、libpq SCRAM 调用、只读预检、取消、部分失败、权限验收、固定目标、SecretRef 兼容与日志脱敏。现有后端/React/E2E/迁移/合同/Mock 验收继续由 CI 执行。最终数量与 CI 链接附 Draft PR。

首次真实固定目标写入、真实 SCRAM 建角色、Windows 凭据持久化后的重登录，以及真实 PostgreSQL 权限验收均**尚未执行**，必须在代码审查及下一次用户授权后才进行。既有 PR17 的 DeepSeek 假凭据原生验证不冒充本工具的新密码初始化验证。
