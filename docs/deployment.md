# 部署与配置

## Docker Compose（推荐）

环境要求：Docker 24+、2 核 4GB 内存。**建议部署在家庭网络 / NAS 或使用住宅代理**，机房 IP 更容易触发闲鱼风控。

```bash
git clone https://github.com/ln2146/XianyuHub.git
cd XianyuHub/deploy
cp .env.example .env
# 必填：APP_SECRET_KEY、CREDENTIAL_MASTER_KEY、ADMIN_PASSWORD、POSTGRES_PASSWORD（生成命令见 .env 注释）
vim .env
docker compose up -d --build
```

浏览器访问 `http://127.0.0.1:8080`，用 `.env` 中的管理员账号登录。

- 默认只监听本机。局域网访问把 `WEB_BIND` 改为 `0.0.0.0`；公网访问填写 `SITE_ADDRESS=你的域名`，Caddy 会自动申请 HTTPS 证书
- 国内拉取 Docker Hub 镜像不稳定时，可以配置镜像加速或重试

## 本地开发运行

```bash
# 后端（http://127.0.0.1:8000，接口文档 /docs）
cd backend
uv sync --all-extras
cp .env.example .env          # 设置 ADMIN_PASSWORD 等
uv run python -m app

# 前端（http://localhost:5173，已代理 /api 到 8000；后端换端口时用 VITE_API_TARGET 指定）
cd frontend
pnpm install
pnpm dev
```

本地默认使用 SQLite（`backend/data/`），不需要 PostgreSQL 和 Redis。

## API 与 Worker 分离部署（可选）

默认单进程已能满足个人和小团队。需要把接口服务和后台任务分开时：

```bash
cd deploy
docker compose -f docker-compose.yml -f docker-compose.split.yml up -d --build
```

- `backend` 以 `PROCESS_ROLE=api` 运行，只提供接口；`worker` 以 `PROCESS_ROLE=worker` 运行调度器、IM 长连接和订单处理
- 两者通过 Redis 同步领域事件和实时推送；需要 IM 长连接的操作（如发送消息）由 Worker 执行
- IM 长连接只能由一个 Worker 持有，**worker 保持 1 个副本**；API 可以按需扩容

## 组件

| 组件 | 说明 |
|---|---|
| `backend` | FastAPI 应用。默认单进程：同一进程内运行调度器和 IM 网关 |
| `worker`（可选） | 分离部署时运行调度器、IM 长连接和订单处理，通过 Redis 与 API 进程同步 |
| `web` | Caddy：托管前端静态资源，反向代理 `/api` 与 WebSocket，配置域名后自动 HTTPS |
| `postgres` / `redis` | 业务数据；限流令牌桶（Lua 原子脚本） |

## 配置项

完整配置见 [`deploy/.env.example`](../deploy/.env.example)（Docker）和 [`backend/.env.example`](../backend/.env.example)（本地）。

| 配置 | 默认 | 说明 |
|---|---|---|
| `APP_SECRET_KEY` | — | JWT 签名密钥，生产环境必须设置且不少于 32 位 |
| `CREDENTIAL_MASTER_KEY` | — | 32 字节 base64，加密 Cookie / 卡密，**丢失后无法解密，请备份** |
| `ADMIN_PASSWORD` | — | 首次启动创建管理员；生产环境不提供默认密码 |
| `DATABASE_URL` | SQLite | 生产建议 PostgreSQL |
| `REDIS_URL` | 空 | 为空时使用进程内限流 |
| `PROCESS_ROLE` | `all` | `all` 单进程；`api` / `worker` 分离部署（需要 Redis） |
| `LLM_DEFAULT_PROVIDER` / `LLM_API_KEY` / `LLM_BASE_URL` | — | 兜底的大模型配置：管理台「模型配置」里没有启用的配置时才生效 |
| `LLM_DAILY_TOKEN_BUDGET` | `0` | 每日 token 上限，超出后自动降级为仅规则 |
| `GUARD_RATE_MULTIPLIER` | `1.0` | 全局限流倍率，小于 1 更保守 |
| `GUARD_SEARCH_PER_MIN` / `GUARD_MESSAGE_PER_MIN` / `GUARD_PUBLISH_PER_5MIN` | 6 / 20 / 1 | 每账号的搜索、发消息、发布速率 |
| `GUARD_COOLDOWN_BASE_SECONDS` | `1800` | 风控熔断后的基础冷却时长（按次数指数增长，最长 6 小时） |
| `BROWSER_ENABLED` | `false` | 启用 Playwright 浏览器通道（Docker 构建时设置 `WITH_BROWSER=true`） |

账号级开关（自动回复、AI 模式、接管时长、工作时段、发货模式、自动评价、自动擦亮等）在管理台「账号配置 → 设置」修改，即时生效。
