#!/usr/bin/env python3
"""HA WebSocket 事件探路工具 — 订阅指定时间，实时打印 + 最终汇总。
用法: 从项目根目录运行: python scripts/test_ha_ws_explore.py
需要: pip install aiohttp
"""
import asyncio
import json
import os
import sys
import time
from collections import Counter

# 从环境变量或命令行读取
HA_URL = os.environ.get("HA_URL", "http://<your-ha-ip>:8123")
HA_TOKEN = os.environ.get("HA_TOKEN", "")

DURATION = int(os.environ.get("HA_WS_DURATION", "180"))  # 默认 3 分钟

event_types = Counter()
domains = Counter()
by_entity = Counter()
total = 0
start = None


async def main():
    global total, start

    if not HA_TOKEN:
        print("错误: 请设置环境变量 HA_TOKEN", file=sys.stderr)
        sys.exit(1)

    ws_url = HA_URL.replace("http", "ws") + "/api/websocket"

    import aiohttp

    print(f"连接 {ws_url} ...")
    start = time.monotonic()

    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(ws_url, timeout=aiohttp.ClientTimeout(total=30)) as ws:
            # 1. auth
            msg = await ws.receive_json()
            print(f"← {msg['type']} (HA {msg.get('ha_version', '?')})")

            await ws.send_json({"type": "auth", "access_token": HA_TOKEN})
            msg = await ws.receive_json()
            print(f"← {msg['type']}")
            if msg["type"] != "auth_ok":
                print(f"认证失败: {msg}")
                return

            # 2. 订阅 state_changed
            await ws.send_json({
                "id": 1, "type": "subscribe_events", "event_type": "state_changed",
            })
            msg = await ws.receive_json()
            print(f"← subscribe_events: success={msg.get('success')}")

            # 3. 也订阅一下其他常见事件类型做探路
            for etype in ("call_service", "automation_triggered"):
                n = int(time.monotonic() * 1000) % 10000
                await ws.send_json({
                    "id": n, "type": "subscribe_events", "event_type": etype,
                })
                msg = await ws.receive_json()
                print(f"← subscribe_events({etype}): success={msg.get('success')}")

            print(f"\n监听 {DURATION}s, 实时打印事件 (按 Ctrl+C 可提前结束)...\n")

            try:
                async for msg in ws:
                    elapsed = time.monotonic() - start
                    if elapsed > DURATION:
                        break

                    data = msg.json()
                    etype = data.get("type", "")

                    if etype == "event":
                        ev = data.get("event", {})
                        ev_type = ev.get("event_type", "?")
                        ev_data = ev.get("data", {})
                        entity_id = ev_data.get("entity_id", "")
                        new_state = ev_data.get("new_state", {})
                        old_state = ev_data.get("old_state", {}) or {}

                        total += 1
                        event_types[ev_type] += 1
                        if entity_id:
                            domain = entity_id.split(".")[0] if "." in entity_id else "?"
                            domains[domain] += 1
                            by_entity[entity_id] += 1

                        # 实时打印
                        old_s = old_state.get("state", "?") if old_state else "?"
                        new_s = (new_state or {}).get("state", "?") if new_state else "?"
                        ts = time.strftime("%H:%M:%S")
                        print(f"[{ts}] #{total:<5} {ev_type:<20} {entity_id:<50} {old_s:<12} → {new_s}")

                    elif etype == "ping":
                        await ws.send_json({"id": 0, "type": "pong"})

            except asyncio.TimeoutError:
                pass

    elapsed = time.monotonic() - start
    spm = total / (elapsed / 60) if elapsed > 0 else 0
    print(f"\n{'='*60}")
    print(f"监听结束 ({elapsed:.0f}s) — 共 {total} 条, 速率 {spm:.0f}/min")
    print(f"{'='*60}")

    print(f"\n事件类型分布:")
    for et, n in event_types.most_common():
        print(f"  {et}: {n}")

    print(f"\n实体域 (top 15):")
    for dom, n in domains.most_common(15):
        print(f"  {dom}: {n}")

    print(f"\n高频实体 (top 15):")
    for eid, n in by_entity.most_common(15):
        print(f"  {eid}: {n}")


if __name__ == "__main__":
    asyncio.run(main())
