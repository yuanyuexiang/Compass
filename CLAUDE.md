# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

（本文件为中文说明，指导后续 Claude Code 实例在本仓库中工作。）

## 当前状态

**V1 全链路已跑通**：采集（ccgp + 江苏公共资源两源）→ 清洗/附件 → DeepSeek 十二字段提取 → 发布 → 三级漏斗匹配（规则→[向量]→LLM 评分卡+六项风险）→ 订阅通知（站内信实测）→ Next.js 管理后台（7 页面）。产品需求见 [prd.md](prd.md)，技术方案见 [tech-design.md](tech-design.md)（架构/选型问题先查它；附录 D–G 是实测记录与遗留项清单，**开工前必读附录 G**）。

密钥在 `backend/.env`（已 gitignore）：DEEPSEEK_API_KEY 已配；SILICONFLOW_API_KEY 未配 → 向量化自动跳过、匹配退化为二级漏斗，配上即恢复三级。

## 常用命令

后端（`backend/` 下，uv 管理 Python 3.12）：

```bash
uv sync                                        # 安装依赖
uv run pytest                                  # 全部测试（29 个）
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

本机开发注意：这台机器的代理会对部分站点做 HTTPS 中间人/fake-IP 拦截——采集报 `CERTIFICATE_VERIFY_FAILED` 时用 `CRAWLER_VERIFY_SSL=false`（仅本机）；deal.ggzy.gov.cn 与江苏政采域名本机不可达（198.18.x），相关适配器须在生产网络开发。

## 架构要点（改代码前必读）

- **公共层/租户层分离**：`models/public.py`（公告只处理一次，全租户共享）vs `models/tenant.py`（画像/匹配/订阅/通知，均含 tenant_id）。租户隔离由 `core/security.py` 的 JWT 依赖注入强制——租户层查询必须过滤 `current.tenant_id`。
- **流水线状态机**：`crawled → cleaned → attachments_parsed → ai_extracted → embedded → published`（+failed），发布后 fan-out 到各租户匹配。业务逻辑写成纯函数 `run_*(session,...)`，Celery 任务只是薄包装（`tasks/pipeline.py`）。
- **新增采集平台**：`crawler/adapters/` 写 SourceAdapter 子类 + `@register` + 在 `adapters/__init__.py` import；解析逻辑放可离线测试的静态方法，用真实页面 fixture 写测试。适配器内置限速，**不得绕过**；只采官方公开源（合规红线见 tech-design §10.4）。
- **LLM 约定**：直接用 LiteLLM（入口 `ai/llm_config.py`），模型 `deepseek-v4-flash`（旧模型名已弃用）。Prompt 一律放 `ai/prompts/` 版本化（该目录豁免行长 lint）。**对 LLM 输出做宽容解析**（历史教训：模型会把字符串字段包成 {value,...} 对象且重试不自愈）——见 `ai/schemas.py`、`matching/schemas.py` 的 field_validator。
- **匹配三级漏斗**（`matching/engine.py`）：规则（画像 data.filter）→ 向量（无 embedding 自动跳过）→ LLM 评分卡。评分卡含 match_score/star/advice/reasons/六项风险。
- **通知**（`notify/`）：站内信必写兜底，外部渠道（email/企微/钉钉/飞书）按 Subscription.channels 配置驱动，单渠道失败不影响其他。

## 产品背景速览

**AI 寻标 Agent**（Project Compass/司南）：中国招投标 AI 商机平台。V1=寻标（当前），V2=投标，V3=商机智能体（prd.md §10）。核心业务要求：AI 语义匹配而非关键词、附件解析（OCR 兜底）、风险分析出参与建议、AI 结论必须附原文 evidence 与置信度、多租户推荐结果各异。界面与数据以中文为主。
