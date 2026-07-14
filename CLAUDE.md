# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

（本文件为中文说明，指导后续 Claude Code 实例在本仓库中工作。）

## 当前状态

**V1 全链路已跑通**：采集（ccgp + 江苏公共资源两源）→ 清洗/附件 → DeepSeek 十二字段提取 → 发布 → 三级漏斗匹配（规则→[向量]→LLM 评分卡+六项风险）→ 订阅通知（站内信实测）→ Next.js 管理后台（7 页面）。产品需求见 [prd.md](prd.md)，技术方案见 [tech-design.md](tech-design.md)（架构/选型问题先查它；附录 D–G 是实测记录与遗留项清单，**开工前必读附录 G**）。

密钥在 `backend/.env`（已 gitignore）：DEEPSEEK_API_KEY 已配；SILICONFLOW_API_KEY 未配 → 向量化自动跳过、匹配退化为二级漏斗，配上即恢复三级。METASO_API_KEY（秘塔 AI 搜索）供「AI 生成画像」联网检索，未配则该功能优雅降级（按钮报错、不影响其他）。

## 常用命令

后端（`backend/` 下，uv 管理 Python 3.12）：

```bash
uv sync                                        # 安装依赖
uv run pytest                                  # 全部测试（67 个）
uv run pytest tests/test_matching.py::test_rule_filter_region   # 单个测试
uv run ruff check app tests scripts            # Lint（提交前必须通过）
uv run uvicorn app.api.main:app --port 8300    # API（本机 8000 被占用）
uv run celery -A app.tasks.celery_app worker -l info   # Worker（beat 同理）
uv run python scripts/dev_seed.py              # 种子租户+admin账号（admin/admin123）
uv run python scripts/dev_crawl.py --adapter ccgp --limit 3   # 采集演练（ccgp/jsggzy）
uv run python scripts/dev_extract.py --limit 3 # AI 提取演练
uv run python scripts/dev_match.py             # 发布+匹配+通知演练
```

前端（`frontend/` 下）：`npm install && npm run dev`（端口 3000，`NEXT_PUBLIC_API_BASE` 指后端，默认 http://localhost:8300）；`npm run build` 必须零错误。

基础设施（根目录）：`docker compose up -d postgres redis minio`。建表用 `init_db()`（dev_seed 自动调）；Alembic 迁移是待办。

## CI/CD（GitHub Actions）

- 单一流水线 `.github/workflows/ci.yml`（名 CI/CD）：PR 只跑测试（后端 ruff+pytest、前端 build）；master push 时**测试全绿才**构建镜像推**阿里云 ACR**（registry.cn-hangzhou.aliyuncs.com/yuanyuexiang，在 workflow env 配置）并 SSH 部署（`deploy/deploy.sh`：拉镜像、compose up、幂等建表）。依赖 secrets：DEPLOY_HOST / DEPLOY_USER / DEPLOY_SSH_KEY / REGISTRY_USERNAME / REGISTRY_PASSWORD。
- 服务器侧：部署目录 `/opt/compass`，业务密钥在其 `.env`（首次部署会生成模板并要求填写后重触发）。生产编排见 [deploy/docker-compose.prod.yml](deploy/docker-compose.prod.yml)。
- **入口经 Traefik**（另一 compose 栈，外部网络 `matrix-net`）：域名 `compass.matrix-net.tech` 经 labels 路由到 frontend:3000，TLS 由 Traefik 终止（entrypoint/certresolver 名可在服务器 .env 覆盖）；API 端口仅绑定服务器回环 127.0.0.1:8300（SSH 隧道调试用）。
- **生产前端与 API 同源**：浏览器请求 `/api/*` 由 Next 服务端 rewrites 反代到 `api:8000`（构建参数 `NEXT_PUBLIC_API_BASE=""` + `INTERNAL_API_URL`，见 frontend/Dockerfile）；本地开发仍直连 8300。改 API 契约时注意这条链路。

本机开发注意：采集默认**关闭 SSL 校验**（`crawler_verify_ssl` 默认 `False`，httpx + Playwright 两条链路都生效——政府/公共资源站证书链常年配错，且本机代理会做 HTTPS 中间人/fake-IP 拦截；要强校验则 `.env` 置 `CRAWLER_VERIFY_SSL=true`）；deal.ggzy.gov.cn 与江苏政采域名本机不可达（198.18.x），相关适配器须在生产网络开发。

## 架构要点（改代码前必读）

- **公共层/租户层分离**：`models/public.py`（公告只处理一次，全租户共享）vs `models/tenant.py`（画像/匹配/订阅/通知，均含 tenant_id）。租户隔离由 `core/security.py` 的 JWT 依赖注入强制——租户层查询必须过滤 `current.tenant_id`。
- **流水线状态机**：`crawled → cleaned → attachments_parsed → ai_extracted → embedded → published`（+failed），发布后 fan-out 到各租户匹配。业务逻辑写成纯函数 `run_*(session,...)`，Celery 任务只是薄包装（`tasks/pipeline.py`）。
- **可投标闸门**：`app/opportunity.py` 的 `is_biddable(ann_type, title)` 判定公告阶段——中标/成交/废标类不是"寻标"商机，`publish_task` fan-out 前 + `run_match` 内双重拦截，不匹配不推荐不通知（仍入库、商机查询可检索，留给 V3 分析）。规则关键词判定，中标优先于招标。自动采集用 **tick 模式**：Beat 每分钟跑 `crawl_tick`，按 `system_settings` 里管理员配置的间隔（默认 30 分钟，5–720 可调，改动即时生效、无需重启）决定是否派发；数据源经 `/api/sources`（`api/routes/sources.py`）管理，管理员可在后台"采集管理"页增改/启停/手动触发/调整间隔（写操作用 `AdminDep` 权限依赖）。系统级配置读写用 `app/core/kv.py`。
- **新增采集平台**：分三档。①结构规整的静态站用 `generic`（`adapters/generic.py`），后台选「通用网站」，**贴网址点 AI 识别**或手填选择器表单，"测试采集"预览后保存，零代码。②JS 动态渲染站用 `generic_browser`（`adapters/generic_browser.py`，继承 generic，取页面改走 Playwright 渲染，见 `crawler/browser.py`），后台选「通用网站（动态渲染/JS）」，配选择器 + 可选 wait_selector。③带强反爬/验证码的硬骨头才写专用 SourceAdapter 子类（`@register` + `adapters/__init__.py` import，解析逻辑放可离线测试的静态方法 + 真实页面 fixture）。适配器内置限速**不得绕过**；只采官方公开源（合规红线见 tech-design §10.4）。相关接口：`POST /api/sources/smart-suggest`（**智能识别**：贴网址一步到位——域名命中 `DOMAIN_ADAPTERS` 走专用适配器，否则用 httpx 判静/动 [`ai/suggest.py` 的 `looks_dynamic`：可见文本极少或含瑞数式混淆脚本即判动态]，动态走 Playwright 渲染，再 LLM 生成选择器并试采，静态 0 条自动转动态重试；前端「AI 识别」按钮走此端点）、`POST /api/sources/suggest`（旧端点，仅按给定 HTML 出选择器建议，`ai/suggest.py`）、`POST /api/sources/test`（试采不入库）、`scripts/dev_inspect.py <url>`（探路：列出动态站的 XHR/JSON 接口，摸清后常可降级回 httpx）。前端 config 一律走结构化中文表单，不暴露 JSON。
- **Playwright**：`crawler/browser.py` 懒加载共享 chromium（同步 API，Celery worker 用；FastAPI 同步路由经线程池调用，不与事件循环冲突）。`available()` 优雅降级——未装浏览器时渲染类源报错、不影响 httpx 类源。生产镜像已在 `backend/Dockerfile` 装 chromium（约 +400MB，不采动态站可注释该行瘦身）。
- **LLM 约定**：直接用 LiteLLM（入口 `ai/llm_config.py`），模型 `deepseek-v4-flash`（旧模型名已弃用）。Prompt 一律放 `ai/prompts/` 版本化（该目录豁免行长 lint）。**对 LLM 输出做宽容解析**（历史教训：模型会把字符串字段包成 {value,...} 对象且重试不自愈）——见 `ai/schemas.py`、`matching/schemas.py` 的 field_validator。
- **匹配三级漏斗**（`matching/engine.py`）：规则（画像 data.filter）→ 向量（无 embedding 自动跳过）→ LLM 评分卡。评分卡含 match_score/star/advice/reasons/六项风险。
- **自然语言查询**（`ai/nl_search.py`）：商机页搜索框把口语查询交 LLM 解析成结构化 DSL（`POST /api/search/nl`，`api/routes/tenant.py`，前端 opportunities 页），解析失败降级为 `{keyword: 原文}` 关键词搜索，保证有结果。商机查询（普通+NL）默认按画像 `filter.regions` 过滤地区（与推荐口径统一，共享 `matching/profiles.py` 的 `region_filter_clause`），前端有「仅看关注地区」开关可放开。
- **AI 企业画像**（`ai/profile_suggest.py` + `ai/websearch.py`）：画像页输入企业名 → 秘塔 AI 搜索联网检索（`POST /api/v1/search`，滤除天眼查/企查查等聚合平台守合规红线）→ LLM 整理成草稿（`POST /api/profile/suggest`，**不落库**，仅预填表单供人工确认，防幻觉）→ 用户改后走 `PUT /api/profile` 存。只产描述性字段，`filter`（关注地区/最低预算）属经营决策手填。
- **通知**（`notify/`）：站内信必写兜底，外部渠道（email/企微/钉钉/飞书）按 Subscription.channels 配置驱动，单渠道失败不影响其他。

## 产品背景速览

**AI 寻标 Agent**（Project Compass/司南）：中国招投标 AI 商机平台。V1=寻标（当前），V2=投标，V3=商机智能体（prd.md §10）。核心业务要求：AI 语义匹配而非关键词、附件解析（OCR 兜底）、风险分析出参与建议、AI 结论必须附原文 evidence 与置信度、多租户推荐结果各异。界面与数据以中文为主。
