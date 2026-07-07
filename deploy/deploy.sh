#!/usr/bin/env bash
# 在部署服务器上执行（由 GitHub Actions 经 ssh 注入环境变量后运行）。
# 需要的环境变量：REGISTRY NAMESPACE TAG REGISTRY_USERNAME REGISTRY_PASSWORD
set -euo pipefail

cd /opt/compass

if [ ! -f .env ]; then
  cp .env.production.example .env
  echo "❌ 首次部署：已生成 /opt/compass/.env 模板，请填写密钥后重新触发部署。"
  exit 1
fi
if grep -q "change-me" .env; then
  echo "❌ /opt/compass/.env 中仍有 change-me 占位值，请填写真实密钥后重新触发部署。"
  exit 1
fi

echo "$REGISTRY_PASSWORD" | docker login "$REGISTRY" -u "$REGISTRY_USERNAME" --password-stdin

export REGISTRY NAMESPACE TAG
docker compose -f docker-compose.prod.yml --env-file .env pull -q
docker compose -f docker-compose.prod.yml --env-file .env up -d --remove-orphans

# 建表（幂等；schema 迁移改用 Alembic 后替换此行）
docker compose -f docker-compose.prod.yml --env-file .env run --rm --no-deps api \
  python -c "from app.core.db import init_db; init_db()"

docker image prune -f > /dev/null
echo "✅ 部署完成：TAG=$TAG"
docker compose -f docker-compose.prod.yml ps
