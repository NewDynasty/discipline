# Early Rise · 早起打卡

极简早起追踪器，nodaysoff 风格。

## 本地运行

```bash
cd backend
pip install -r requirements.txt
python main.py
```

打开 http://localhost:8899

## Docker 部署

```bash
docker compose up -d
```

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| EARLY_RISE_TOKEN | earlyrise2026 | 登录密码 |
| EARLY_RISE_DB | data/earlyrise.db | SQLite 路径 |
| PORT | 8899 | 端口 |

## API

| 端点 | 方法 | 说明 |
|------|------|------|
| /api/auth/login | POST | 登录 |
| /api/checkin | POST | 打卡 |
| /api/checkin/today | GET | 今日状态 |
| /api/stats | GET | 统计 |
| /api/records | GET | 历史记录 |
| /api/heatmap | GET | 热力图数据 |
