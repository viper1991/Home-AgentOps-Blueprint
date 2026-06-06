"""首轮实时快照构建器。

读取 entity_catalog.yaml + 拉取 API 实时数据 → 构建首轮 User Message。
~2500 tokens，包含实体目录、当前状态、网络状态、近期事件。
"""
import logging
from datetime import datetime, timedelta
from typing import Any

from lib.clients.ha_client import HAClient
from lib.clients.unifi_client import UniFiClient

logger = logging.getLogger(__name__)

# 事件回溯时间
EVENT_HOURS = 4


class SnapshotBuilder:
    """构建首轮快照文本。"""

    def __init__(
        self,
        ha: HAClient,
        unifi: UniFiClient,
        entity_catalog: dict,
        event_hours: int = EVENT_HOURS,
    ):
        self._ha = ha
        self._unifi = unifi
        self._catalog = entity_catalog
        self._event_hours = event_hours

    def build(self) -> str:
        """构建并返回快照文本。"""
        parts = []

        # 1. 实体目录
        parts.append(self._build_catalog())

        # 2. 当前状态
        parts.append(self._build_states())

        # 3. 网络状态
        parts.append(self._build_network())

        # 4. 近期事件
        parts.append(self._build_events())

        # 5. DPI 流量分析
        parts.append(self._build_dpi())

        text = '\n\n'.join(parts)
        logger.info('Snapshot built: %d chars', len(text))
        return text

    # ── 实体目录 ──

    def _build_catalog(self) -> str:
        """格式化 entity_catalog 为文本。"""
        lines = ['## 实体目录']
        rooms = self._catalog.get('rooms', [])
        for room in rooms:
            name = room.get('name', '?')
            lines.append(f'### {name}')
            for ent in room.get('entities', []):
                label = ent.get('label', '?')
                etype = ent.get('type', '?')
                eid = ent.get('id', '?')
                lines.append(f'  {label} | {etype} | {eid}')
            lines.append('')
        return '\n'.join(lines).rstrip()

    # ── 当前状态 ──

    def _build_states(self) -> str:
        """拉取 snapshot_entities 的状态并格式化。

        同 label 的温湿度传感器合并为一行显示（如"客厅温湿度: 26°C / 60%"），
        让 LLM 将它们视为一个设备而非两个独立实体。
        """
        lines = ['## 当前状态']
        entity_ids = self._catalog.get('snapshot_entities', [])
        if not entity_ids:
            return '\n'.join(lines)

        states = self._ha.get_states_batch(entity_ids)

        # 构建 entity_id → label 映射
        label_map: dict[str, str] = {}
        for room in self._catalog.get('rooms', []):
            for ent in room.get('entities', []):
                eid = ent.get('id', '')
                lab = ent.get('label', '')
                if eid and lab:
                    label_map[eid] = lab

        # 按 label 分组，合并同 label 的温湿度
        from collections import OrderedDict
        groups: dict[str, dict] = OrderedDict()
        singles: list[dict] = []
        for s in states:
            eid = s.get('entity_id', '?')
            state = s.get('state', 'unavailable')
            attrs = s.get('attributes', {})
            domain = eid.split('.')[0] if '.' in eid else ''
            label = label_map.get(eid, eid)

            if domain == 'climate':
                current = attrs.get('current_temperature', '?')
                target = attrs.get('temperature', '?')
                fan = attrs.get('fan_mode', '?')
                lines.append(f'{eid}: {state}, 当前{current}°C→目标{target}°C, {fan}风速')
            elif domain in ('cover',):
                lines.append(f'{label}: {state}')
            elif domain == 'sensor':
                unit = attrs.get('unit_of_measurement', '')
                dc = attrs.get('device_class', '')
                val = f'{state}{unit}' if unit else str(state)
                if dc in ('temperature', 'humidity') and label in label_map.values():
                    g = groups.setdefault(label, {'temp': None, 'hum': None})
                    if dc == 'temperature':
                        g['temp'] = val
                    else:
                        g['hum'] = val
                else:
                    lines.append(f'{label}: {val}')
            else:
                lines.append(f'{label}: {state}')

        # 输出合并后的温湿度
        for label, g in groups.items():
            parts = []
            if g['temp']:
                parts.append(g['temp'])
            if g['hum']:
                parts.append(g['hum'])
            if parts:
                lines.append(f'{label}: {" / ".join(parts)}')

        return '\n'.join(lines)

    # ── 网络状态 ──

    def _build_network(self) -> str:
        """拉取 UniFi 网络信息（使用公共模块，与显示面板格式一致）。"""
        from lib.network_panel import build_network_snapshot
        try:
            return build_network_snapshot(self._unifi)
        except Exception as e:
            logger.warning('Failed to get UniFi network: %s', e)
            return '## 网络状态\nWAN: 获取失败'

    # ── 近期事件 ──

    def _build_events(self) -> str:
        """拉取 HA logbook + UniFi events 并合并去噪。"""
        lines = ['## 近期事件']
        now = datetime.now()
        start = now - timedelta(hours=self._event_hours)
        all_events = []

        # HA logbook
        try:
            ha_events = self._ha.get_logbook(start, now)
            for e in ha_events:
                all_events.append({
                    'time': e.get('when', ''),
                    'text': (e.get('name', '') + ': ' + e.get('message', '')).strip(': '),
                    'level': 'info',
                    'source': 'ha',
                    'entity_id': e.get('entity_id', ''),
                })
        except Exception as e:
            logger.warning('Failed to get HA logbook: %s', e)

        # UniFi events — 按客户端 MAC 聚合 connect/disconnect
        try:
            u_events = (self._unifi.get_events(limit=100) or [])[:50]
            # 聚合: {mac: {'up': n, 'down': n, 'latest_time': int, 'texts': [str]}}
            from collections import defaultdict
            agg: dict = defaultdict(lambda: {'up': 0, 'down': 0, 'latest_time': 0})
            for e in u_events:
                msg = str(e.get('msg', ''))
                t = e.get('time', 0)
                # 提取 MAC: User[XX:XX:XX:XX:XX:XX]
                import re
                m = re.search(r'User\[([0-9a-f:]{17})\]', msg)
                if not m:
                    continue
                mac = m.group(1)
                entry = agg[mac]
                if t > entry['latest_time']:
                    entry['latest_time'] = t
                if 'disconnected from' in msg:
                    entry['down'] += 1
                elif 'connected to' in msg:
                    entry['up'] += 1
                elif 'roams from' in msg:
                    # 漫游计为 1 次下线 + 1 次上线
                    entry['down'] += 1
                    entry['up'] += 1

            for mac, data in agg.items():
                short_mac = mac[-8:]  # 取后 8 位
                label = f'Client[{short_mac}]'
                parts = []
                if data['up']:
                    parts.append(f'上线{data["up"]}次')
                if data['down']:
                    parts.append(f'下线{data["down"]}次')
                text = f'{label}: {" ".join(parts)}'
                all_events.append({
                    'time': data['latest_time'],
                    'text': text,
                    'level': 'info',
                    'source': 'unifi_agg',
                    'entity_id': '',
                })
        except Exception as e:
            logger.warning('Failed to get UniFi events: %s', e)

        # 去噪关键词（中英文）
        noise_keywords = [
            'heartbeat', 'button_unavailable', 'device_tracker',
            'unavailable', 'attribute', 'EVT_WU_Roam',
            '心跳',                        # HA 中文心跳事件
        ]

        filtered = []
        for e in all_events:
            text = (e.get('text', '') or '').lower()
            if any(kw in text for kw in noise_keywords):
                continue
            filtered.append(e)

        # 排序（按时间倒序），取最近 8 条
        def _sort_key(e):
            v = e.get('time', 0)
            if isinstance(v, (int, float)):
                return v
            try:
                # HA logbook 时间是 UTC ISO 格式，不含时区后缀
                # 强制 +00:00 避免被当作本地时间解析
                s = str(v).strip()
                if s.endswith('Z'):
                    s = s[:-1]
                if '+' not in s and ' ' not in s and s.count('-') >= 2:
                    s += '+00:00'
                return datetime.fromisoformat(s).timestamp() * 1000
            except Exception:
                return 0
        filtered.sort(key=_sort_key, reverse=True)
        top = filtered[:8]

        for e in top:
            t_raw = e.get('time', '')
            # UniFi time 是 int 时间戳，HA logbook time 是 ISO 字符串
            if isinstance(t_raw, (int, float)):
                t = datetime.fromtimestamp(t_raw / 1000).strftime('%H:%M')
            else:
                # HA logbook time 是 UTC ISO 格式，转为本地时区
                t = self._fmt_ha_time(t_raw)
            text = e.get('text', '')[:60]
            src = e.get('source', '?')
            if t:
                lines.append(f'{t} | {text}')
            else:
                lines.append(f'{text}')

        if not top:
            lines.append('无近期事件')

        return '\n'.join(lines)

    # ── DPI 流量分析 ──

    def _build_dpi(self) -> str:
        """拉取全站 DPI + 流量 TOP10 设备，作为快照发给 LLM。"""
        lines = ['## 流量分析']
        try:
            from lib.dpi_apps import get_app_name, get_cat_name

            # 全站 DPI TOP 10 应用
            raw = self._unifi.get_dpi_by_app()
            if raw:
                apps = raw[0].get('by_app', [])
                ranked = sorted(
                    apps,
                    key=lambda x: x.get('rx_bytes', 0) + x.get('tx_bytes', 0),
                    reverse=True,
                )
                total_gb = sum(
                    a.get('rx_bytes', 0) + a.get('tx_bytes', 0) for a in ranked
                ) / (1024 ** 3)
                lines.append(f'全站总流量: {total_gb:.0f}GB')

                lines.append('TOP 10 应用:')
                for a in ranked[:10]:
                    app_id = a.get('app', 0)
                    name = get_app_name(app_id)
                    rx = a.get('rx_bytes', 0) / (1024 ** 3)
                    tx = a.get('tx_bytes', 0) / (1024 ** 3)
                    clients = a.get('known_clients', 0)
                    lines.append(
                        f'  {name}: ↓{rx:.1f}GB ↑{tx:.1f}GB ({clients}台设备)'
                    )
        except Exception as e:
            logger.warning('Snapshot DPI apps failed: %s', e)
            lines.append('应用数据获取失败')

        # 当前活跃设备（按会话流量排序）
        lines.append('')
        try:
            clients = self._unifi.get_clients()
            ranked_clients = sorted(
                clients,
                key=lambda c: c.get('rx_bytes', 0) + c.get('tx_bytes', 0),
                reverse=True,
            )
            lines.append('当前活跃设备 TOP 10（会话流量）:')
            for c in ranked_clients[:10]:
                name = c.get('hostname', '') or c.get('name', '') or c.get('mac', '?')
                rx = c.get('rx_bytes', 0) / (1024 ** 2)
                tx = c.get('tx_bytes', 0) / (1024 ** 2)
                ap = c.get('ap_mac', '')[-8:] if c.get('ap_mac') else '?'
                signal = c.get('signal', '?')
                wired = '有线' if c.get('is_wired') else f'WiFi({ap})'
                uptime_min = round(c.get('uptime', 0) / 60, 1)
                lines.append(
                    f'  {name}: ↓{rx:.0f}MB ↑{tx:.0f}MB {wired} '
                    f'信号={signal}dBm 在线{uptime_min}min'
                )
        except Exception as e:
            logger.warning('Snapshot DPI clients failed: %s', e)
            lines.append('活跃设备获取失败')

        return '\n'.join(lines)

    @staticmethod
    def _fmt_ha_time(t_raw) -> str:
        """将 HA logbook 的 UTC ISO 时间字符串转为本地时区显示。"""
        try:
            s = str(t_raw).strip().replace('Z', '+00:00')
            if '+' not in s and s.count('-') >= 2:
                s += '+00:00'
            return datetime.fromisoformat(s).astimezone().strftime('%H:%M')
        except Exception:
            return str(t_raw)[:16]
