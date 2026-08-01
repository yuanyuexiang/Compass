# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

（本文件为中文说明，指导后续 Claude Code 实例在本仓库中工作。）

## 当前状态

**V1 全链路已跑通**：采集（ccgp + 江苏公共资源两源）→ 清洗/附件 → DeepSeek 十二字段提取 → 发布 → 三级漏斗匹配（规则→[向量]→LLM 评分卡+六项风险）→ 订阅通知（站内信实测）→ Next.js 管理后台（9 页面）。已具备**审批制多租户账号体系**（注册申请→平台管理员审批→成员管理，登录限流+停用校验）与 **LLM 用量记账/每日配额**（超额降级）。产品需求见 [prd.md](prd.md)，技术方案见 [tech-design.md](tech-design.md)（架构/选型问题先查它；附录 D–G 是实测记录与遗留项清单，**开工前必读附录 G**）。

LLM 供应商密钥与场景模型统一在平台「模型服务」中管理，不再使用 `DEEPSEEK_API_KEY` 环境变量。`SILICONFLOW_API_KEY` 未配时向量化自动跳过、匹配退化为二级漏斗；`METASO_API_KEY` 供企业画像联网检索，未配则该功能优雅降级。

## 常用命令

后端（`backend/` 下，uv 管理 Python 3.12）：

```bash
uv sync                                        # 安装依赖
uv run pytest                                  # 全部测试（67 个）
uv run pytest tests/test_matching.py::test_rule_filter_region   # 单个测试
uv run ruff check app tests scripts            # Lint（提交前必须通过）
uv run uvicorn app.api.main:app --port 8300    # API（本机 8000 被占用）
uv run celery -A app.tasks.celery_app worker -l info   # Worker（beat 同理）
uv run python scripts/dev_seed.py              # 种子租户+admin账号（admin/admin123，platform_admin）
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
- **账号体系（审批制）**：`POST /api/auth/register` 创建待审批租户（`Tenant.status=pending, enabled=False`）+ tenant_admin；平台管理员（角色 `platform_admin`，种子 admin 即是）在「租户管理」页（`/api/admin`，`PlatformAdminDep`）审批/启停；tenant_admin 在「成员管理」页（`/api/tenant/users`）管本租户账号。登录失败 5 次锁 10 分钟（`core/ratelimit.py`，Redis，不可用则放行）；停用即时生效靠 `get_current_user` 里 60 秒 TTL 缓存的查库校验（`account_block_reason`）。密码强度统一走 `validate_password`。schema 变更用 `core/db.py` 的幂等 MIGRATIONS 列表（ADD COLUMN IF NOT EXISTS），Alembic 仍是待办。
- **LLM 成本护栏**：所有 LLM 调用经 `ai/llm_config.extract_completion(scene=, tenant_id=)` 记账到 `llm_usage` 表（平台管理员用量报表 `/api/admin/usage`，商业化计费底账）。每租户每日配额存 `system_settings`（键见 `core/kv.py`，0/负数=不限），超额**降级不报错**：匹配精排跳过（公告仍可检索）、NL 搜索退化关键词（响应带 `degraded:"quota"`）、AI 画像返回 429。计数在 Redis（`quota:{scene}:{tenant}:{北京日}`）。
- **流水线状态机**：`crawled → cleaned → attachments_parsed → ai_extracted → embedded → published`（+failed），发布后 fan-out 到各租户匹配。业务逻辑写成纯函数 `run_*(session,...)`，Celery 任务只是薄包装（`tasks/pipeline.py`）。
- **可投标闸门**：`app/opportunity.py` 的 `is_biddable(ann_type, title)` 判定公告阶段——中标/成交/废标类不是"寻标"商机。判定在采集与发布时落库为 `announcements.biddable`（存量回填 `scripts/backfill_biddable.py`，deploy.sh 自动跑，幂等）；`publish_task` fan-out 前 + `run_match` 内双重拦截，不匹配不推荐不通知。商机查询与 NL 搜索**默认隐藏**结果类公告（`include_results` 参数/前端「包含结果公告」开关放开可查，留给竞争情报与 V3 分析），工作台「可见公告数」同口径。规则关键词判定，中标优先于招标。自动采集用 **tick 模式**：Beat 每分钟跑 `crawl_tick`，按 `system_settings` 里管理员配置的间隔（默认 30 分钟，5–720 可调，改动即时生效、无需重启）决定是否派发；数据源经 `/api/sources`（`api/routes/sources.py`）管理——**采集全局共享、仅平台管理员可管**（全端点 `PlatformAdminDep`，"采集管理"页也只对 platform_admin 显示）；租户侧经 `GET /api/sources/options` 只读源名列表（仅 `status=active`），在「订阅设置」勾选**关注的数据源**（`Subscription.source_ids`，空=全部），商机查询/NL 搜索/匹配 fan-out 统一按它过滤（`matching/profiles.py` 的 `get_watched_source_ids`/`tenant_watches_source`，与地区口径同理）。租户也可在订阅设置页**申请新数据源**（`POST /api/sources/requests` 只填网址+名称+说明 → `Source.status=pending, enabled=False` 不参与采集，每租户限 5 条待审、网址去重；`GET /api/sources/requests/mine` 查进度）；平台管理员在采集管理页「待审批」区**配置并测试**（复用 AI 识别/试采）后 `approve`（转 active 开采，若申请方设过关注源自动补上该源）或 `reject`（必填理由，申请方可见）。采集调度（tick/手动/单源触发）只认 `status=active` 的源。系统级配置读写用 `app/core/kv.py`。
- **新增采集平台**：分三档。①结构规整的静态站用 `generic`（`adapters/generic.py`），后台选「通用网站」，**贴网址点 AI 识别**或手填选择器表单，"测试采集"预览后保存，零代码。②JS 动态渲染站用 `generic_browser`（`adapters/generic_browser.py`，继承 generic，取页面改走 Playwright 渲染，见 `crawler/browser.py`），后台选「通用网站（动态渲染/JS）」，配选择器 + 可选 wait_selector。③带强反爬/验证码的硬骨头才写专用 SourceAdapter 子类（`@register` + `adapters/__init__.py` import，解析逻辑放可离线测试的静态方法 + 真实页面 fixture）。适配器内置限速**不得绕过**；只采官方公开源（合规红线见 tech-design §10.4）。相关接口：`POST /api/sources/smart-suggest`（**智能识别**：贴网址一步到位——域名命中 `DOMAIN_ADAPTERS` 走专用适配器，否则用 httpx 判静/动 [`ai/suggest.py` 的 `looks_dynamic`：可见文本极少或含瑞数式混淆脚本即判动态]，动态走 Playwright 渲染，再 LLM 生成选择器并试采，静态 0 条自动转动态重试；前端「AI 识别」按钮走此端点）、`POST /api/sources/suggest`（旧端点，仅按给定 HTML 出选择器建议，`ai/suggest.py`）、`POST /api/sources/test`（试采不入库）、`scripts/dev_inspect.py <url>`（探路：列出动态站的 XHR/JSON 接口，摸清后常可降级回 httpx）。前端 config 一律走结构化中文表单，不暴露 JSON。
- **Playwright**：`crawler/browser.py` 懒加载共享 chromium（同步 API，Celery worker 用；FastAPI 同步路由经线程池调用，不与事件循环冲突）。`available()` 优雅降级——未装浏览器时渲染类源报错、不影响 httpx 类源。生产镜像已在 `backend/Dockerfile` 装 chromium（约 +400MB，不采动态站可注释该行瘦身）。
- **LLM 约定**：直接用 LiteLLM（入口 `ai/llm_config.py`），模型 `deepseek-v4-flash`（旧模型名已弃用）。Prompt 一律放 `ai/prompts/` 版本化（该目录豁免行长 lint）。**对 LLM 输出做宽容解析**（历史教训：模型会把字符串字段包成 {value,...} 对象且重试不自愈）——见 `ai/schemas.py`、`matching/schemas.py` 的 field_validator。
- **匹配链路**（`matching/engine.py`）：规则硬过滤 → 向量软信号（只记录/排序，不按固定阈值淘汰）→ LLM 分维判断；代码按主体业务35/案例20/产品服务15/资质15/地区5/经营偏好10确定性汇总并应用能力、合作模式和明确缺资质封顶。分维证据与向量相似度存 `match_results.score_details`。**画像变更重评估**：画像页查看态/编辑态分离（保存是显式动作，确认弹窗列关键变更），保存有实质变更时异步跑 `rematch_tenant_task`（近 7 天已发布可投标且在关注源内的公告，`run_match(force=True)` 更新评分**保留 follow_status**、新规则排除时删除未跟进的旧结果；10 分钟冷却防抖，受每日精排配额封顶，不发即时通知）。
- **自然语言查询**（`ai/nl_search.py`）：商机页搜索框把口语查询交 LLM 解析成结构化 DSL（`POST /api/search/nl`，`api/routes/tenant.py`，前端 opportunities 页），解析失败降级为 `{keyword: 原文}` 关键词搜索，保证有结果。商机查询（普通+NL）默认按画像 `filter.regions` 过滤地区（与推荐口径统一，共享 `matching/profiles.py` 的 `region_filter_clause`），前端有「仅看关注地区」开关可放开。
- **AI 企业画像**：联网草稿仍走 `ai/profile_suggest.py` + `ai/websearch.py`（屏蔽商业企业聚合站，仅预填、用户保存才生效）。企业材料链路走 `ai/profile_materials.py`：租户上传 PDF/DOCX/TXT 中标材料 → MinIO 原件 + 本地解析文本 → Celery 抽取 `profile_facts` 与逐字可定位的 `profile_evidence` → 用户逐条确认 → 投影到 `company_profiles` 兼容快照并重评估；未经确认的事实不得参与匹配。经营过滤条件始终由用户填写。
- **通知**（`notify/`）：站内信必写兜底，外部渠道（email/企微/钉钉/飞书）按 Subscription.channels 配置驱动，单渠道失败不影响其他。

## 产品背景速览

**AI 寻标 Agent**（Project Compass/司南）：中国招投标 AI 商机平台。V1=寻标（当前），V2=投标，V3=商机智能体（prd.md §10）。核心业务要求：AI 语义匹配而非关键词、附件解析（OCR 兜底）、风险分析出参与建议、AI 结论必须附原文 evidence 与置信度、多租户推荐结果各异。界面与数据以中文为主。
