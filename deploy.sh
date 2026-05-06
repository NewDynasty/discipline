#!/bin/bash
# deploy.sh — 安全部署 Discipline 到 ECS
# 用法: bash deploy.sh [commit_hash]
#   不带参数 = 部署最新 (origin/main)
#   带参数 = 部署指定 commit

set -euo pipefail

cd /opt/discipline-git
COMMIT="${1:-latest}"

echo "=== Deploy $(date '+%Y-%m-%d %H:%M:%S') ==="

# 1. 保存当前镜像为回滚备份
IMAGE_NAME=$(docker compose images -q discipline 2>/dev/null | head -1)
if [ -n "$IMAGE_NAME" ]; then
    echo "[1/5] 💾 保存回滚镜像..."
    docker tag "$IMAGE_NAME" discipline-rollback:latest 2>/dev/null || true
    echo "  → discipline-rollback:latest 已保存"
else
    echo "[1/5] ⚠️ 未找到当前镜像，跳过回滚备份"
fi

# 2. 拉取代码
echo "[2/5] 📦 拉取代码..."
git fetch origin main 2>&1
if [ "$COMMIT" = "latest" ]; then
    git reset --hard origin/main 2>&1
    echo "  → 已切换到 origin/main"
else
    git reset --hard "$COMMIT" 2>&1
    echo "  → 已切换到 $COMMIT"
fi

echo "  → $(git log --oneline -1)"

# 3. 构建并部署
echo "[3/5] 🔨 构建镜像..."
docker compose up -d --build 2>&1

# 4. 健康检查（等5秒后检查）
echo "[4/5] 🏥 健康检查..."
sleep 5
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8899/portal 2>/dev/null || echo "000")
if [ "$HTTP_CODE" = "200" ]; then
    echo "  ✅ HTTP $HTTP_CODE — 服务正常"
else
    echo "  ❌ HTTP $HTTP_CODE — 服务异常！"
    echo ""
    echo "回滚方法:"
    echo "  docker compose down"
    echo "  docker tag discipline-rollback:latest \$(docker compose images -q discipline)"
    echo "  或者: git reset --hard <上一个commit> && docker compose up -d --build"
    exit 1
fi

# 5. 清理旧镜像（保留 rollback + 当前）
echo "[5/5] 🧹 清理..."
docker image prune -f --filter "label!=discipline-rollback" 2>/dev/null | tail -1

CURRENT_HASH=$(git rev-parse --short HEAD)
echo ""
echo "=== ✅ 部署完成 ==="
echo "  版本: $CURRENT_HASH"
echo "  时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo "  回滚: discipline-rollback:latest 可用"
