"""轻量刷新入口（Cron: */5 * * * *）。

无需 LLM，直接重拉数值更新 sensor/network/events panel，保持 layout + summary 不变。

首次运行或找不到上次重量级刷新留下的输出时，
从 entity_catalog 的 snapshot_entities 读取传感器列表，构建初始输出。
"""
import logging
import sys

import yaml

from lib.config import load_config
from lib.clients.ha_client import HAClient
from lib.clients.unifi_client import UniFiClient
from lib.working_memory import WorkingMemory
from lib.display.protocol import DisplayClient

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
)
logger = logging.getLogger('refresh_lightweight')


def _fmt_event_text(e: dict) -> str:
    """格式化 HA logbook 事件文本。

    HA logbook 的 message 字段常为空，但 state 字段包含新状态值。
    组合 name + state 让事件可读（如 "书房空调 → 关闭"、"客厅灯 → 关闭"）。
    event 域的状态是时间戳，不显示。
    """
    name = (e.get('name', '') or '').strip()
    msg = (e.get('message', '') or '').strip()
    state = (e.get('state', '') or '').strip()
    eid = (e.get('entity_id', '') or '')
    domain = eid.split('.')[0] if '.' in eid else ''

    if msg:
        return f'{name}: {msg}'[:60]
    if state and state not in ('unknown', '', 'None') and domain != 'event':
        state_map = {
            'cool': '制冷', 'heat': '制热', 'dry': '除湿',
            'fan_only': '送风', 'off': '关闭', 'on': '开启',
            'open': '打开', 'closed': '关闭',
            'idle': '空闲', 'paused': '暂停', 'playing': '播放',
        }
        display_state = state_map.get(state.lower(), state)
        return f'{name} → {display_state}'[:60]
    return name[:60]


def _build_initial_output(ha, unifi, config) -> dict:
    """从 entity_catalog 读取 snapshot_entities，构建初始 final_output。

    用于首次运行或重量级刷新尚未执行过的场景。
    """
    try:
        with open('config/entity_catalog.yaml', encoding='utf-8') as f:
            cat = yaml.safe_load(f)
    except Exception as e:
        logger.error('Failed to load entity_catalog: %s', e)
        return None

    entity_ids = cat.get('snapshot_entities', [])
    if not entity_ids:
        logger.warning('snapshot_entities list is empty in entity_catalog')
        return None

    # 传感器数值
    from datetime import datetime, timedelta
    states = ha.get_states_batch(entity_ids)
    sensor_panel = []
    for s in states:
        eid = s.get('entity_id', '')
        state = s.get('state', 'unavailable')
        attrs = s.get('attributes', {})
        friendly = attrs.get('friendly_name', eid)
        unit = attrs.get('unit_of_measurement', '')
        value = f'{state}{unit}' if unit else str(state)

        # 从 entity_catalog 找 label
        label = friendly
        for room in cat.get('rooms', []):
            for ent in room.get('entities', []):
                if ent.get('id') == eid:
                    label = ent.get('label', friendly)
                    break

        sensor_panel.append({
            'entity_id': eid,
            'label': label,
            'value': value,
        })

    # 网络状态（公共模块）
    from lib.network_panel import build_network_panel
    network_panel = build_network_panel(unifi)

    # 事件（HA logbook 时间为 UTC，转本地时区显示，按时间倒序，自动去噪）
    events_panel = []
    try:
        start = datetime.now() - timedelta(hours=2)
        ha_events = ha.get_logbook(start)
        noise_keywords = ['heartbeat', 'unavailable', 'device_tracker', '心跳']
        raw = []
        for e in ha_events:
            text = _fmt_event_text(e)
            if any(kw in text.lower() for kw in noise_keywords):
                continue
            t_raw = e.get('when', '')
            try:
                s = str(t_raw).replace('Z', '+00:00')
                if '+' not in s and s.count('-') >= 2:
                    s += '+00:00'
                dt = datetime.fromisoformat(s).astimezone()
                t = dt.strftime('%H:%M')
                sort_val = dt.timestamp()
            except Exception:
                t = str(t_raw)[:16]
                sort_val = 0
            raw.append({'time': t, '_sort': sort_val, 'level': 'info', 'text': text[:60]})
        raw.sort(key=lambda x: x['_sort'], reverse=True)
        for e in raw[:6]:
            e.pop('_sort', None)
            events_panel.append(e)
    except Exception:
        pass

    return {
        'sensor_panel': sensor_panel,
        'network_panel': network_panel,
        'events_panel': events_panel,
        'summary': ['仪表盘已就绪'],
    }


def _update_sensor_values(last: dict, ha: HAClient) -> list[dict]:
    """根据上次输出的 sensor_panel 结构，按 label 从 HA 重拉数值并合并温湿度。"""
    old_panel = last.get('sensor_panel', []) or []
    if not old_panel:
        return []

    # 构建 label → entity_ids 映射
    import yaml
    try:
        with open('config/entity_catalog.yaml', encoding='utf-8') as f:
            cat = yaml.safe_load(f)
    except Exception:
        return old_panel

    label_entities: dict[str, list[str]] = {}
    for room in cat.get('rooms', []):
        for ent in room.get('entities', []):
            lab = ent.get('label', '')
            eid = ent.get('id', '')
            if lab and eid:
                label_entities.setdefault(lab, []).append(eid)

    # 收集所有需要查询的 entity_id
    all_ids = []
    for item in old_panel:
        lab = item.get('label', '')
        eids = label_entities.get(lab, [])
        all_ids.extend(eids)

    if not all_ids:
        return old_panel

    states = ha.get_states_batch(all_ids)
    state_map = {s['entity_id']: s for s in states}

    updated = []
    for item in old_panel:
        lab = item.get('label', '')
        eids = label_entities.get(lab, [])
        if not eids:
            updated.append(item)
            continue

        # 拉取该 label 下所有实体的最新值
        values = []
        for eid in eids:
            s = state_map.get(eid)
            if not s:
                continue
            state_val = s.get('state', '')
            attrs = s.get('attributes', {})
            unit = attrs.get('unit_of_measurement', '')
            domain = eid.split('.')[0] if '.' in eid else ''

            if domain == 'climate':
                current = attrs.get('current_temperature', '')
                target = attrs.get('temperature', '')
                state_map_cn = {'cool': '制冷', 'heat': '制热', 'dry': '除湿',
                                'fan_only': '送风', 'off': '关闭', 'on': '开启'}
                display = state_map_cn.get(state_val, state_val)
                if state_val != 'off' and current:
                    values.append(f'{display} {current}°C')
                else:
                    values.append(display)
            elif unit:
                values.append(f'{state_val}{unit}')
            else:
                values.append(str(state_val))

        new_item = dict(item)
        new_item['value'] = ' / '.join(values) if values else item.get('value', '')
        updated.append(new_item)

    return updated


def _update_events(last: dict, ha: HAClient, unifi: UniFiClient, hours: float = 2) -> list[dict]:
    """重拉 HA 事件列表（倒序，屏幕仅显示 HA 事件，不影响 LLM 快照）。"""
    from datetime import datetime, timedelta

    now = datetime.now()
    start = now - timedelta(hours=hours)

    ha_events = []

    try:
        for e in ha.get_logbook(start, now):
            t_raw = e.get('when', '')
            try:
                s = str(t_raw).replace('Z', '+00:00')
                if '+' not in s and s.count('-') >= 2:
                    s += '+00:00'
                ts = datetime.fromisoformat(s).astimezone()
                time_str = ts.strftime('%H:%M')
                sort_val = ts.timestamp()
            except Exception:
                time_str = str(t_raw)[:16]
                sort_val = 0
            ha_events.append({
                'time': time_str, '_sort': sort_val,
                'text': _fmt_event_text(e),
                'level': 'info',
            })
    except Exception:
        pass

    # 去噪 + 屏蔽灯组子设备（"米家LED筒灯 蓝牙MESH版xxx" 由餐厅筒灯组驱动，无需重复显示）
    noise = ['heartbeat', 'unavailable', 'device_tracker', '心跳']
    ha_events = [e for e in ha_events
                 if not any(kw in (e.get('text', '') or '').lower() for kw in noise)
                 and not e.get('text', '').startswith('米家LED筒灯 蓝牙MESH版')]

    # 倒序
    ha_events.sort(key=lambda e: e['_sort'], reverse=True)

    # 去掉内部排序字段，取前 6 条
    for e in ha_events[:6]:
        e.pop('_sort', None)

    return ha_events[:6]


def main():
    # 夜间休眠：22:00-08:00 不执行
    from datetime import datetime
    hour = datetime.now().hour
    if hour >= 22 or hour < 8:
        logger.info('夜间休眠时段（22:00-08:00），跳过轻量级刷新')
        return

    config = load_config()

    mem = WorkingMemory(
        outputs_dir=config.working_memory.outputs_dir,
        keep_count=config.working_memory.keep_count,
        dedup_check_recent=config.working_memory.dedup_check_recent,
    )

    ha = HAClient(config.ha.url, config.ha.token)
    unifi = UniFiClient(
        config.unifi.url,
        config.unifi.username,
        config.unifi.password,
        site=config.unifi.site,
        timeout=30.0,
    )

    last = mem.load_last()

    if not last:
        logger.info('No previous output found, building initial output from snapshot_entities')
        last = _build_initial_output(ha, unifi, config)
        if last is None:
            logger.error('Failed to build initial output, skipping')
            return
        client = DisplayClient(host=config.display.daemon_host, port=config.display.daemon_port)
        ok = client.render(last, mode='full')
        if ok:
            logger.info('Initial display rendered (full)')
        return

    # 增量更新：保留 summary，按上次输出结构更新数值
    from lib.network_panel import build_network_panel
    summary = last.get('summary', ['仪表盘已就绪'])
    events = _update_events(last, ha, unifi)
    network = build_network_panel(unifi)
    sensors = _update_sensor_values(last, ha)

    updated = dict(last)
    if sensors:
        updated['sensor_panel'] = sensors
    if network:
        updated['network_panel'] = network
    if events:
        updated['events_panel'] = events
    updated['summary'] = summary

    client = DisplayClient(host=config.display.daemon_host, port=config.display.daemon_port)
    ok = client.render(updated, mode='partial')
    if ok:
        logger.info('Display rendered (partial)')


if __name__ == '__main__':
    main()
