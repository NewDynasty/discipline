#!/bin/bash
# deploy.sh — ECS 部署脚本，由 GitHub Actions SSH 调用
# 也可以手动执行：bash deploy/deploy.sh
set -euo pipefail

DEPLOY_DIR="/opt/discipline-git"
cd "$DEPLOY_DIR"

echo "=== Deploy Start $(date '+%Y-%m-%d %H:%M:%S') ==="

# 1. 拉取最新代码
echo "[1/4] git pull..."
git fetch origin
git reset --hard origin/main

# 2. 加载环境变量
if [ -f deploy/ecs/.env ]; then
  set -a
  source deploy/ecs/.env
  set +a
  echo "[2/4] .env loaded"
else
  echo "[ERROR] deploy/ecs/.env not found!"
  exit 1
fi

# 3. 重建容器
echo "[3/4] docker compose build + up..."
docker compose build --no-cache
docker compose up -d --force-recreate

# 4. 健康检查（最多等 15 秒）
echo "[4/4] health check..."
HEALTH_URL="http://localhost:${DISCIPLINE_PORT:-8898}/api/checkin/today"
for i in $(seq 1 5); do
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$HEALTH_URL" 2>/dev/null || echo "000")
  if [ "$STATUS" = "401" ] || [ "$STATUS" = "200" ]; then
    echo "Health check passed (HTTP $STATUS)"
    echo "=== Deploy Complete ==="
    exit 0
  fi
  echo "  attempt $i: HTTP $STATUS, retrying..."
  sleep 3
done

echo "[ERROR] Health check failed after 5 attempts"
echo "=== Deploy FAILED ==="
exit 1
