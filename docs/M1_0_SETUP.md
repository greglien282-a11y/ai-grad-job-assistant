# M1-0：React + FastAPI 最小工程骨架

> 状态：工程骨架已提交；真实 AI、登录、简历解析与数据库功能尚未实现。

## 快速启动（开发环境）

需要 Node.js 20.19+（推荐 22）、Python 3.11+、npm。

**终端 1 — FastAPI：**

```bash
cd apps/api
python -m venv .venv
# Windows PowerShell: .venv\\Scripts\\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

访问 `http://127.0.0.1:8000/api/v1/health` 应返回 `{"status":"ok"}`。

**终端 2 — React：**

```bash
cd apps/web
npm install
npm run dev
```

打开 `http://localhost:5173`，应看到“连接成功 · API 正常”。前端经 Vite proxy 请求 FastAPI。

**自动化检查：**

```bash
cd apps/api && python -m pytest -q
cd apps/web && npm run test && npm run build
```

请分别在对应目录执行；CI 工作流也会运行上述检查。

## 后续开发的边界

- 不修改 `prototype/`，现有 GitHub Pages 自动部署保持原样。
- `compose.yaml` 中的 PostgreSQL 仅为未来 M1-1 预备，当前启动无需数据库。
- `apps/web/.env.example` 可配置 `VITE_API_BASE_URL`；默认同源 `/api` 由 Vite 代理。
- FastAPI 的 CORS allowlist 默认只允许 localhost/127.0.0.1:5173。
- 真实 API Key 只放后端环境变量；不得提交真实简历、访问令牌、密码、用户数据。
- 正式上线前要补充认证与授权、数据库迁移、数据删除、限流和隐私策略。

## M1-0 验收

- [x] 定义并实现后端健康检查接口
- [x] React 页面使用真实 fetch 调用健康检查
- [x] 添加 pytest / Vitest 测试
- [x] 添加 CI 工作流（运行结果需在 GitHub Actions 检查）
- [x] 保留原始静态原型的独立部署
- [ ] 安装依赖并执行真实构建及测试（以 CI 结果为准）
