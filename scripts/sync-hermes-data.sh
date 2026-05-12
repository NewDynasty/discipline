#!/bin/bash
# sync-hermes-data.sh — 同步本地 Hermes 数据到 ECS
#
# 同步内容:
#   ~/.hermes/skills/     → /opt/hermes-data/skills/     (知识库 skills 索引)
#   ~/.hermes/knowledge/  → /opt/hermes-data/knowledge/  (知识库 decisions/experts/blackboard)
#   ~/.hermes/memories/   → /opt/hermes-data/memories/   (知识库 MEMORY.md + rollout_summaries)
#   ~/.hermes/usage/      → /opt/hermes-data/usage/      (models 页面用量数据)

set -euo pipefail

ECS_HOST="${ECS_HOST:-root@47.108.143.237}"
ECS_DATA_DIR="/opt/hermes-data"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"

# 确保远程目录存在
ssh -o ConnectTimeout=10 "$ECS_HOST" "mkdir -p $ECS_DATA_DIR/{skills,knowledge,memories,usage}"

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

# 同步 usage（models 页面用量数据，只同步 calibration 和统计文件）
if [ -d "$HERMES_HOME/usage" ]; then
  echo "📦 同步 usage..."
  rsync -az --delete \
    --include='*.json' --include='*/' --exclude='*' \
    "$HERMES_HOME/usage/" "$ECS_HOST:$ECS_DATA_DIR/usage/"
fi

echo "✅ 同步完成 $(date '+%Y-%m-%d %H:%M:%S')"
