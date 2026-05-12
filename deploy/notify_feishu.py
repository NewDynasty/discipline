#!/usr/bin/env python3
"""飞书通知脚本 — 从环境变量读取参数，发送部署结果到飞书群"""
import json
import os
import sys
import urllib.request

WEBHOOK_URL = os.environ["FEISHU_WEBHOOK_URL"]
STATUS = os.environ["DEPLOY_STATUS"]  # success or failure
CHANGELOG = os.environ.get("DEPLOY_CHANGELOG", "")
REPO = os.environ.get("GITHUB_REPOSITORY", "")
RUN_ID = os.environ.get("GITHUB_RUN_ID", "")
ACTIONS_URL = f"https://github.com/{REPO}/actions/runs/{RUN_ID}" if REPO and RUN_ID else ""

if STATUS == "success":
    title = "✅ 部署成功"
    color = "green"
    button_text = "查看 Actions"
    button_type = "primary"
else:
    title = "❌ 部署失败"
    color = "red"
    button_text = "查看日志"
    button_type = "danger"

content = f"**变更内容**:\n{CHANGELOG}\n**github推送**"

elements = [
    {"tag": "div", "text": {"tag": "lark_md", "content": content}}
]
if ACTIONS_URL:
    elements.append({
        "tag": "action",
        "actions": [{
            "tag": "button",
            "text": {"tag": "plain_text", "content": button_text},
            "url": ACTIONS_URL,
            "type": button_type
        }]
    })

payload = {
    "msg_type": "interactive",
    "card": {
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": color
        },
        "elements": elements
    }
}

req = urllib.request.Request(
    WEBHOOK_URL,
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST"
)

try:
    with urllib.request.urlopen(req, timeout=10) as resp:
        body = json.loads(resp.read())
        if body.get("code", -1) != 0:
            print(f"Feishu API error: {body}")
            sys.exit(1)
        print(f"Notification sent: {STATUS}")
except Exception as e:
    print(f"Failed to send notification: {e}")
    sys.exit(1)
