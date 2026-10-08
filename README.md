<div align="center">

# 🐟 XianyuHub · 鱼塘管家

**闲鱼买卖双端智能助手 —— 买家淘好货，卖家省心卖**

AI 选品雷达 · 统一收件箱 · 带底价护栏的 AI 客服 · 虚拟商品自动发货 · 风控内建

![status](https://img.shields.io/badge/status-规划中-orange)
![python](https://img.shields.io/badge/python-3.12-blue)
![fastapi](https://img.shields.io/badge/FastAPI-async-009688)
![vue](https://img.shields.io/badge/Vue-3-42b883)
![deploy](https://img.shields.io/badge/deploy-Docker%20Compose-2496ED)

</div>

> [!WARNING]
> 本项目处于**设计与开发早期**，下文的部署命令、配置项和接口描述的是**目标形态**，会随开发进度调整。
> 设计文档见上级目录：[调研报告](../01_开源项目调研报告.md) · [功能规划](../02_产品功能规划.md) · [架构设计](../03_系统架构设计.md) · [流程图](../04_核心业务流程图.md) · [风险与路线](../05_风险合规与实施路线.md)

---

## 目录

- [它能做什么](#它能做什么)
- [设计亮点](#设计亮点)
- [系统架构](#系统架构)
- [技术栈](#技术栈)
- [快速开始](#快速开始)
- [配置说明](#配置说明)
- [使用指南](#使用指南)
- [目录结构](#目录结构)
- [开发指南](#开发指南)
- [路线图](#路线图)
- [安全与合规](#安全与合规)
- [致谢](#致谢)
- [免责声明](#免责声明)

---

## 它能做什么

### 🛒 买家端：选品雷达

| 功能 | 说明 |
|---|---|
| **监控任务** | 支持多个关键词，可按价格区间、省市、发布天数、个人闲置、包邮筛选，用 cron 定时运行 |
| **一句话建任务** | 输入“想要 M1 Air，电池 90 以上，3500 以内，别要贩子”，AI 自动生成筛选条件和判定标准 |
| **多模态 AI 判定** | AI 结合图片和文字判断成色、型号是否匹配、有没有翻新或拆修，给出 `推荐 / 有条件推荐 / 不推荐`，附理由和风险标签 |
| **卖家画像** | 综合卖家在售和已售商品、评价、信用、账龄，识别“个人玩家”还是“贩子” |
| **价格情报** | 计算同款市场价分位数和性价比评分（0–100），记录历史价格，降价时提醒 |
| **实时推送** | 只推送值得看的商品，附主图、价格、推荐理由和手机端链接 |
| **买家助手** | 针对“需要确认”的点（如电池、维修情况）生成咨询话术，并给出议价建议（不会自动发送） |

### 🏪 卖家端：店铺中枢

| 功能 | 说明 |
|---|---|
| **商品中心** | 同步和查询多账号下的商品；AI 根据图片生成标题和描述；参考市场价给出三档定价建议；发布、编辑、上下架、擦亮 |
| **统一收件箱** | 多个账号的会话集中在一处，实时推送，网页端可直接回复 |
| **自动回复** | 关键词规则分商品级、账号级、全局三层，按优先级匹配；AI 客服会先识别意图，再基于商品知识库回答 |
| **议价护栏** | 底价、每轮让价幅度和最大轮次由**代码计算**，AI 只负责措辞；回复里的金额低于底价时会被拦截 |
| **人工接管** | 卖家亲自回复后，该会话的 AI 自动暂停；接管状态持久化保存 |
| **自动发货** | 识别买家付款后，按规格分配卡券（固定文本 / 卡密池 / 图片 / API 取货），发送后自动确认发货 |
| **发货前风控** | 检查买家信用阈值、同一买家重复下单、跨账号重复下单、黑名单，防止被薅 |
| **售后运营** | 失败补发、超时告警、退款冻结、自动评价 |

### 🧱 平台底座

扫码登录 · 会话自动续期 · 账号健康度 · 一账号一固定 IP · 令牌桶限流 · 风控熔断 · 多渠道通知（企业微信 / 飞书 / 钉钉 / Telegram / Bark / ntfy / Webhook）· 角色权限 · 操作审计 · 开放 API / MCP Server

---

## 设计亮点

1. **一个适配层管住所有闲鱼交互**
   业务代码只调用 `search_items`、`send_message`、`consign_virtual` 这类能力接口，底层有三条通道，可以自动降级：
   - **协议通道**：直连 mtop 接口和 IM WebSocket，速度快
   - **浏览器通道**：用 Playwright 拦截页面请求的响应，更稳
   - **官方通道**：对接闲管家开放平台，合规
2. **风控是一等公民**
   账号互斥锁、按动作区分的令牌桶、随机抖动、熔断和指数退避冷却都在调用链上统一处理。识别到 `FAIL_SYS_USER_VALIDATE` / `RGV587` / `punish` 这类风控信号时**立即停止并通知人工**，不尝试自动破解。
3. **AI 有护栏**
   AI 负责理解和表达，规则负责决定价格、发货和是否可以发送。所有 AI 输出都经过 JSON Schema 校验，并检查金额、禁用词和站外联系方式。
4. **买卖数据打通**
   选品雷达积累的市场价数据，同时供卖家定价和竞品监控使用。
5. **安全基线**
   所有接口强制鉴权；Cookie、密码和卡密用 AES-GCM 加密存储；默认只监听内网；凭证不会发给任何第三方服务。

---

## 系统架构

```mermaid
flowchart TB
  UI["Web 管理台 / 移动端 PWA / 推送通道 / MCP"] --> APP["应用服务 · FastAPI<br/>买家域 · 商品域 · 消息域 · 订单域 · 账号域 · 系统域"]
  APP <--> AI["智能层<br/>LLM 网关 · Agent 编排 · 规则引擎 · 价格引擎 · 知识库"]
  APP --> WK["执行层<br/>调度器 · 采集 Worker · IM 网关 · 业务 Job"]
  WK --> GW["闲鱼适配层<br/>风控守卫 → 协议通道 / 浏览器通道 / 官方通道"]
  APP --> GW
  GW --> XY["闲鱼"]
  APP & WK --> DB[("PostgreSQL + pgvector · Redis · 对象存储")]
```

| 服务 | 职责 |
|---|---|
| `api` | REST 和 WebSocket 接口、业务编排、鉴权 |
| `im-gateway` | 每个闲鱼账号维持一条 IM 长连接，负责收发消息、心跳和 token 刷新 |
| `crawler` | 搜索、详情、卖家画像采集（内置 Chromium） |
| `worker` | 定时任务和异步任务：发货、同步、擦亮、通知 |
| `frontend` | Vue 3 管理台和 PWA |
| `postgres` / `redis` | 业务数据与向量；队列、锁、限流、事件流 |

服务之间通过 Redis Streams 传递领域事件（`chat.message.received`、`order.paid`、`market.item.found`、`account.risk.detected` 等）。完整设计见 [架构设计](../03_系统架构设计.md)。

---

## 技术栈

| 层 | 选型 |
|---|---|
| 后端 | Python 3.12 · FastAPI · Pydantic v2 · SQLAlchemy 2.0 (async) · Alembic |
| 异步任务 | APScheduler · Redis Streams / arq |
| 闲鱼对接 | httpx（mtop）· websockets（LWP）· Playwright / patchright |
| 智能 | 多模型 LLM 网关（Claude / Qwen / DeepSeek / 任意 OpenAI 兼容接口 / 本地模型）· pgvector |
| 存储 | PostgreSQL 16（单机轻量模式可用 SQLite）· Redis 7 · MinIO（可选） |
| 前端 | Vue 3 · Vite · TypeScript · Tailwind · shadcn-vue · ECharts · PWA |
| 部署 | Docker Compose · Caddy（HTTPS） |
| 可观测 | Loguru 结构化日志 · Prometheus 指标 · Sentry（可选） |

---

## 快速开始

> 以下是目标部署方式，功能完成后可用。

### 环境要求

- Docker 24+ 与 Docker Compose v2
- 2 核 4GB 内存（启用浏览器通道建议 4 核 8GB）
- **推荐部署在家庭网络、NAS，或使用住宅代理**（机房 IP 更容易触发风控）
- 一个大模型 API Key（也可以只用本地模型）

### Docker 一键部署

```bash
git clone <your-repo-url> XianyuHub
cd XianyuHub/deploy

cp .env.example .env
# 必填：APP_SECRET_KEY、CREDENTIAL_MASTER_KEY、ADMIN_PASSWORD、LLM 相关配置
vim .env

docker compose up -d
```

浏览器访问 `http://<服务器IP>:8080`，用 `.env` 中设置的管理员账号登录。

### 首次使用三步走

1. **添加闲鱼账号**：进入「账号中心」→「扫码添加」，用闲鱼 App 扫码确认（也可以通过浏览器扩展导入登录态）
2. **配置通知渠道**：进入「通知中心」，添加企业微信、飞书、Telegram 等渠道并发一条测试消息
3. **按需开启功能**：
   - 买家：在「选品雷达」中新建监控任务
   - 卖家：在「消息中心」开启自动回复（建议先用**建议模式**），在「商品中心」为商品设置底价和知识库，在「发货中心」导入卡密并绑定商品

---

## 配置说明

`.env` 主要配置项：

```ini
# ---------- 基础 ----------
APP_ENV=production
APP_PORT=8080
APP_SECRET_KEY=change-me                 # JWT 签名密钥，必须修改
CREDENTIAL_MASTER_KEY=                   # 32 字节 base64，用于加密 Cookie/卡密，丢失后无法解密
ADMIN_USERNAME=admin
ADMIN_PASSWORD=                          # 首次启动必填，不提供默认密码
BIND_HOST=127.0.0.1                      # 默认只监听本机；对外访问请通过 Caddy 反代 + HTTPS

# ---------- 存储 ----------
DATABASE_URL=postgresql+asyncpg://xianyu:xianyu@postgres:5432/xianyuhub
REDIS_URL=redis://redis:6379/0

# ---------- 大模型 ----------
LLM_DEFAULT_PROVIDER=anthropic           # anthropic / openai_compatible / dashscope / ollama
LLM_API_KEY=
LLM_BASE_URL=
LLM_MODEL_VISION=claude-sonnet-5-5       # 多模态判定、商品文案
LLM_MODEL_CHAT=                          # 客服回复
LLM_MODEL_FAST=                          # 意图分类、粗筛（建议用低成本模型）
LLM_MONTHLY_BUDGET=200                   # 月度预算上限（元），超出后降级为仅规则

# ---------- 风控（保守默认值，按需调整） ----------
GUARD_SEARCH_PER_MIN=6
GUARD_MESSAGE_PER_MIN=20
GUARD_PUBLISH_PER_5MIN=1
GUARD_COOLDOWN_BASE_SECONDS=1800         # 熔断后基础冷却时长，指数退避
GUARD_JITTER_MS=500-3000

# ---------- 浏览器通道 ----------
BROWSER_ENABLED=true
BROWSER_HEADLESS=true
```

更细的配置（议价策略、回复规则、发货模板、通知模板等）都可以在管理台中在线修改，修改后即时生效。

---

## 使用指南

<details>
<summary><b>选品雷达：写好判定标准</b></summary>

判定标准（criteria）分三层组合：

```
基础模板（输出格式、通用风险）
  + 品类标准（如“二手 MacBook”：型号、电池、维修史、是否监管机）
  + 个人偏好（如“只要个人卖家、同城优先、不接受磕碰”）
```

建议做法：

- **一票否决项**写清楚（例如“非 M1 芯片直接不推荐”）
- **信息缺失**时选“有条件推荐”而不是直接拒绝，系统会生成需要向卖家确认的问题
- 对推送结果点「不感兴趣」并选原因，系统会把它沉淀到个人偏好中

</details>

<details>
<summary><b>AI 客服：议价策略怎么配</b></summary>

每个商品可以配置：

| 字段 | 示例 | 说明 |
|---|---|---|
| 标价 | 1000 | 当前挂牌价 |
| 底价 | 850 | **任何情况下都不会低于这个价格** |
| 最大轮次 | 3 | 超过后报最终价，不再让 |
| 让价阶梯 | 40% / 30% / 20% / 10% | 每轮让出 (标价 − 底价) 的比例 |
| 可送赠品 | 手机壳、贴膜 | 用赠品代替降价 |

商品热度高（想要人数多）时会自动收紧让价幅度。AI 只拿到“本轮可报价”这个结果，然后组织语言。

</details>

<details>
<summary><b>自动发货：卡券类型</b></summary>

| 类型 | 适用场景 | 说明 |
|---|---|---|
| 固定文本 | 教程链接、网盘资源 | 每单发送相同内容 |
| 卡密池 | 激活码、兑换码 | 一卡一用，原子出库，库存不足时预警 |
| 图片 | 二维码、凭证图 | 最多 3 张 |
| API 取货 | 对接自有系统或第三方货源 | 支持 `{order_id}`、`{buyer_id}`、`{spec}` 等变量，失败自动重试 |

发货模板支持变量：`{buyer_name}`、`{order_id}`、`{item_title}`、`{content}`。

</details>

<details>
<summary><b>遇到风控怎么办</b></summary>

当账号状态变为 `CIRCUIT_OPEN` 时，系统已经自动暂停该账号的写操作，并发送了通知：

1. 打开通知里的验证链接，或在管理台点「去验证」打开远程浏览器
2. 手动完成滑块或身份验证
3. 等待冷却结束，系统探活成功后会自动恢复

**不要**频繁重启服务，也不要短时间内反复重试，这会延长风控时间。

</details>

---

## 目录结构

```
XianyuHub/
├── backend/
│   ├── app/
│   │   ├── api/                 # 路由（v1），全部挂鉴权依赖
│   │   ├── core/                # 配置、安全、加密、日志、事件总线
│   │   ├── domains/             # account / buyer / goods / message / order / system
│   │   ├── intelligence/        # llm_gateway / agents / guardrails / rules / pricing
│   │   └── goofish/             # ★ 闲鱼适配层（唯一出入口）
│   │       ├── capabilities.py  #   能力接口定义
│   │       ├── guard/           #   令牌桶、熔断、账号锁、冷却
│   │       ├── protocol/        #   mtop 签名与客户端、LWP、MessagePack、扫码登录
│   │       ├── browser/         #   浏览器上下文池、XHR 拦截
│   │       ├── official/        #   闲管家开放平台
│   │       └── parsers/         #   响应 → 统一 DTO
│   ├── workers/                 # im_gateway / crawler / jobs / scheduler
│   ├── prompts/                 # 判定标准、客服、文案 Prompt 模板
│   ├── migrations/              # Alembic
│   └── tests/                   # 含录制的响应样本，用于协议解析回归测试
├── frontend/                    # Vue 3 管理台 + PWA
├── extension/                   # 浏览器扩展：导出登录态
├── deploy/                      # docker-compose.yml、.env.example、Caddyfile
└── docs/
```

---

## 开发指南

```bash
# 后端
cd backend
uv sync                                  # 或 pip install -e ".[dev]"
playwright install chromium
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload --port 8000

# 各 Worker（分别开终端）
python -m workers.im_gateway
python -m workers.crawler
python -m workers.jobs

# 前端
cd frontend
pnpm install
pnpm dev                                 # http://localhost:5173

# 测试与检查
pytest
ruff check . && mypy app
```

**开发约定**

- 与闲鱼交互的代码**只能**放在 `app/goofish/` 下，业务层禁止直接发 HTTP 或 WebSocket 请求
- 新增闲鱼接口时，需要同时提交：能力定义、解析器、脱敏后的响应样本、对应的解析测试
- 所有写操作必须声明限流键，并写入审计日志
- AI 输出必须定义 Pydantic 模型并做校验，涉及价格或发货的决策必须由规则层给出
- 提交前请确认没有提交任何真实 Cookie、Token、手机号或卡密

---

## 路线图

- [ ] **阶段 0 · 技术验证**：mtop 签名与搜索、扫码登录、IM 收发、风控阈值摸底
- [ ] **MVP-1 · 买家雷达**：监控任务、双通道采集、规则 + AI 判定、价格情报、看板与推送
- [ ] **MVP-2 · 卖家客服**：统一收件箱、关键词回复、AI 客服、议价护栏、人工接管
- [ ] **MVP-3 · 自动发货**：订单同步、卡密库存、自动发货与确认、发货前风控
- [ ] **V1.0**：多账号与健康度、代理绑定、权限、AI 发布与智能定价、数据看板
- [ ] **V2.0**：开放 API、MCP Server、贩子识别、降价追踪、闲管家官方通道

详见 [风险合规与实施路线](../05_风险合规与实施路线.md)。

---

## 安全与合规

- 本项目定位为**个人或小团队管理自己账号的私有化效率工具**，不提供公共 SaaS 抓取服务
- 所有自动写操作（自动回复、发货、发布、评价）**默认关闭**，需要手动开启；建议先用“建议模式”观察一段时间
- 不内置任何验证码自动破解能力；遇到风控时由人工处理
- 卖家画像等数据只做短期缓存，供本人决策参考，**禁止导出、转售或公开**
- 请勿在回复中引导站外交易，系统会默认拦截此类内容
- 发现安全问题请通过私密渠道报告，不要公开提交 Issue

---

## 致谢

本项目的设计参考了以下开源项目的思路（**净室实现，未复制其代码**）：

- [Usagi-org/ai-goofish-monitor](https://github.com/Usagi-org/ai-goofish-monitor)：多模态 AI 选品、判定标准体系、卖家画像
- [cv-cat/XianYuApis](https://github.com/cv-cat/XianYuApis)：闲鱼协议与 IM 通信研究
- [zhinianboke/xianyu-auto-reply](https://github.com/zhinianboke/xianyu-auto-reply)：自动回复与自动发货的业务设计
- [shaxiu/XianyuAutoAgent](https://github.com/shaxiu/XianyuAutoAgent)：多 Agent 客服与人工接管
- [superboyyy/xianyu_spider](https://github.com/superboyyy/xianyu_spider)：HTTP 直连搜索与筛选参数
- [fancyboi999/goofish-cli](https://github.com/fancyboi999/goofish-cli)：写操作限流、熔断与 Agent 化设计

---

## 免责声明

本项目仅供学习与研究使用。使用本项目访问闲鱼平台可能违反其用户协议，并可能导致账号受限或封禁，**由此产生的一切后果由使用者自行承担**。请遵守《中华人民共和国网络安全法》《个人信息保护法》《数据安全法》等法律法规及平台规则，不得将本项目用于任何违法违规用途。本项目与闲鱼、阿里巴巴集团无任何关联。

## License

待定。
