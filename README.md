# Discipline · Command Center

个人效率门户 — 早起打卡、文档浏览、知识库、热点追踪、模型管理、部署管控。

## 架构

```
┌─ 开发 :8898 ──────────────────┐  ┌─ 局域网部署 :8899 (Docker) ─────────┐
│ LaunchAgent 源码直跑           │  │                                     │
│ 修改代码即时生效               │  │  cc-discipline ←→ cc-datasette      │
│ localhost only                │  │       │              (cc-network)   │
└───────────────────────────────┘  │       ├── discipline-data (vol rw)  │
                                   │       ├── Obsidian Vault (ro)      │
                                   │       ├── ~/.hermes (ro)           │
                                   │       └── hotspot.db (ro)          │
                                   └─────────────────────────────────────┘
```

**开发环境**（端口 8898）：LaunchAgent 管理源码直跑，改代码即时生效，仅 localhost 可访问。

**局域网部署**（端口 8899）：Docker Compose 编排，mac.lan / Windows 可访问。加子系统只需在 `docker-compose.local.yml` 加 service + 加入 `cc-network`。

**云端部署**（ECS 47.108.143.237）：同一套代码，`deploy.sh` 自动 git pull + docker build + 健康检查 + 回滚备份。

## 快速开始

### 开发模式

```bash
cd ~/playground/discipline
pip install -r backend/requirements.txt
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8898
```

LaunchAgent 自动管理（`ai.hermes.discipline`，端口 8898）。

### 局域网 Docker 部署

```bash
cd ~/playground/discipline
docker compose -f docker-compose.local.yml up -d --build
```

### 云端部署

```bash
ssh root@47.108.143.237 'cd /opt/discipline-git && git fetch origin && git reset --hard origin/main && bash deploy.sh'
```

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| EARLY_RISE_TOKEN | earlyrise2026 | 登录密码 |
| EARLY_RISE_DB | data/earlyrise.db | SQLite 路径 |
| HOTSPOT_UPSTREAM | http://localhost:8200 | Datasette 上游（Docker 内用 http://datasette:8200） |
| PROXY_UPSTREAM_HOTSPOT | 同上 | 通用 proxy 路由的上游覆盖 |
| OBSIDIAN_VAULT | ~/Documents/Obsidian Vault | 笔记库路径 |

## 子系统

由 `portal/portal-registry.yaml` 驱动，后端自动注册路由、导航、健康检查。

| 子系统 | 路径 | 说明 |
|--------|------|------|
| 门户 | /portal | 总览面板 |
| 文档 | /docs | Obsidian 文档浏览（SPA 路由） |
| 知识库 | /knowledge | 知识检索 |
| 模型 | /models | AI 模型管理 |
| 图谱 | /graph | 知识图谱 |
| 部署 | /deploy | 服务部署管控（需 admin） |
| 热点 | /hotspot | Datasette 反代（容器化） |

加子系统：编辑 `portal-registry.yaml`，有 `proxy` 字段的走反代，有 `html` 字段的走静态页面。

## API

| 端点 | 方法 | 说明 |
|------|------|------|
| /api/auth/login | POST | 登录 |
| /api/auth/logout | POST | 登出 |
| /api/checkin | POST | 打卡 |
| /api/checkin/today | GET | 今日状态 |
| /api/stats | GET | 统计 |
| /api/records | GET | 历史记录 |
| /api/heatmap | GET | 热力图数据 |
| /api/portal/status | GET | 服务健康检查 |
| /api/portal/nav | GET | 导航配置 |
| /api/portal/systems | GET | 子系统列表 |

## 项目结构

```
discipline/
├── backend/
│   ├── main.py              # FastAPI 入口，auth/checkin/hotspot 路由
│   ├── deps.py              # 共享配置、数据库、认证
│   ├── routers/
│   │   ├── portal.py        # 门户页面路由（registry 驱动）
│   │   ├── docs.py          # 文档浏览
│   │   ├── actions.py       # 操作类 API
│   │   └── proxy.py         # 通用反代（registry 驱动）
│   └── requirements.txt
├── portal/
│   ├── index.html           # 门户主页
│   ├── shared-nav.js        # 统一导航
│   ├── portal-registry.yaml # 子系统注册表
│   └── *.html               # 各子系统页面
├── docker-compose.local.yml # 本地局域网 Docker 编排
├── docker-compose.yml       # 云端 Docker 编排
├── Dockerfile               # Discipline 容器
├── docker/datasette/        # Datasette 容器
├── deploy.sh                # 云端部署脚本
└── deploy-agent.py          # 部署 Agent
```
