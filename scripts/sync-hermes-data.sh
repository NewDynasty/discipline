#!/bin/bash
# sync-hermes-data.sh — 同步本地 Hermes 数据到 ECS
# 用途：让 ECS 上的 knowledge API 能读取 skills/knowledge 数据
#
# 同步内容:
#   ~/.hermes/skills/     → /opt/hermes-data/skills/
#   ~/.hermes/knowledge/  → /opt/hermes-data/knowledge/
#   ~/Documents/Obsidian Vault/ → 已通过 docker-compose volumes 挂载

set -euo pipefail

ECS_HOST="${ECS_HOST:-root@47.108.143.237}"
ECS_DATA_DIR="/opt/hermes-data"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"

# 确保远程目录存在
ssh -o ConnectTimeout=10 "$ECS_HOST" "mkdir -p $ECS_DATA_DIR/skills $ECS_DATA_DIR/knowledge"

# 同步 skills
echo "📦 同步 skills..."
rsync -az --delete --exclude '__pycache__' --exclude '*.pyc' --exclude '.git' \
  "$HERMES_HOME/skills/" "$ECS_HOST:$ECS_DATA_DIR/skills/"

# 同步 knowledge
echo "📦 同步 knowledge..."
rsync -az --delete \
  "$HERMES_HOME/knowledge/" "$ECS_HOST:$ECS_DATA_DIR/knowledge/"

# 同步 memories（knowledge index 依赖）
if [ -d "$HERMES_HOME/memories" ]; then
  echo "📦 同步 memories..."
  rsync -az --delete --exclude '__pycache__' \
    "$HERMES_HOME/memories/" "$ECS_HOST:$ECS_DATA_DIR/memories/"
fi

echo "✅ 同步完成 $(date '+%Y-%m-%d %H:%M:%S')"
