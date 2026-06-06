"""网络面板公共模块。

轻量刷新、重量刷新、快照构建均从此模块获取网络信息，
确保显示格式一致性。

提供两个接口：
  build_network_panel(unifi) → list[dict]   用于 DisplayClient 渲染
  build_network_snapshot(unifi) → str          用于 LLM 快照文本
"""
import logging
from lib.clients.unifi_client import UniFiClient

logger = logging.getLogger(__name__)


def _fmt_bps(bps: int) -> str:
    """格式化字节数为可读速率字符串。"""
    if bps >= 1_000_000:
        return f'{bps/1_000_000:.1f}MB/s'
    if bps >= 1_000:
        return f'{bps/1_000:.0f}KB/s'
    return f'{bps}B/s'


def _gather_network_data(unifi: UniFiClient) -> dict:
    """从 UniFi 拉取所有网络数据，返回结构化 dict。"""
    data = {
        'wan_ip': '?', 'wan2_ip': None,
        'tx_bps': 0, 'rx_bps': 0, 'latency_ms': None,
        'aps': [],           # [{name, ch2g, ch5g, clients}]
        'wifi_users': 0, 'wired_users': 0,
    }

    # ── Health ──
    try:
        health = unifi.get_health()
        wan = www = wlan = lan = {}
        for h in health:
            s = h.get('subsystem', '')
            if s == 'wan': wan = h
            elif s == 'www': www = h
            elif s == 'wlan': wlan = h
            elif s == 'lan': lan = h

        if wan:
            data['wan_ip'] = wan.get('wan_ip', '?')
            data['tx_bps'] = wan.get('tx_bytes-r', 0)
            data['rx_bps'] = wan.get('rx_bytes-r', 0)
        if www:
            data['latency_ms'] = www.get('latency', None)
        if wlan:
            data['wifi_users'] = wlan.get('num_user', 0) + wlan.get('num_guest', 0)
        if lan:
            data['wired_users'] = lan.get('num_user', 0)
    except Exception as e:
        logger.warning('UniFi health failed: %s', e)

    # ── Devices (failover WAN + AP details) ──
    ap_mac_map: dict[str, str] = {}  # mac → name
    aps_temp: dict[str, dict] = {}
    try:
        for d in unifi.get_devices():
            dtype = d.get('type', '')
            if dtype == 'ugw':
                for p in d.get('port_table', []):
                    if p.get('name') == 'lan2':
                        pip = p.get('ip', '')
                        if pip and not pip.startswith('172.'):
                            data['wan2_ip'] = pip
                        break
            elif dtype in ('uap', 'ap'):
                name = d.get('name', d.get('model', '?'))
                mac = d.get('mac', '').lower()
                ap_mac_map[mac] = name
                ch2g = ch5g = '?'
                for r in d.get('radio_table', []):
                    radio = r.get('radio', '')
                    ch = r.get('channel', '?')
                    if radio == 'ng': ch2g = ch
                    elif radio == 'na': ch5g = ch
                aps_temp[mac] = {'name': name, 'ch2g': ch2g, 'ch5g': ch5g,
                                 'clients_2g': 0, 'clients_5g': 0, 'total': d.get('num_sta', 0)}
    except Exception as e:
        logger.warning('UniFi devices failed: %s', e)

    # ── 客户端按 AP + 信道分布 ──
    try:
        for c in unifi.get_clients():
            ap_mac = c.get('ap_mac', '').lower()
            radio = c.get('radio', '')
            if ap_mac in aps_temp:
                if radio == 'ng':
                    aps_temp[ap_mac]['clients_2g'] += 1
                elif radio == 'na':
                    aps_temp[ap_mac]['clients_5g'] += 1
    except Exception as e:
        logger.warning('UniFi clients failed: %s', e)

    data['aps'] = list(aps_temp.values())

    return data


def build_network_panel(unifi: UniFiClient) -> list[dict]:
    """构建网络面板数据。"""
    d = _gather_network_data(unifi)
    panel = []

    panel.append({'source': 'unifi', 'label': 'WAN',
                   'value': d['wan_ip'],
                   'status': 'ok', 'detail': ''})

    if d['wan2_ip']:
        panel.append({'source': 'unifi', 'label': '备线',
                       'value': d['wan2_ip'],
                       'status': 'ok', 'detail': ''})

    panel.append({'source': 'unifi',
                   'label': '↑↓',
                   'value': f'{_fmt_bps(d["tx_bps"])} {_fmt_bps(d["rx_bps"])}',
                   'status': 'ok', 'detail': ''})

    if d['latency_ms'] is not None:
        panel.append({'source': 'unifi', 'label': '延迟',
                       'value': f'{d["latency_ms"]}ms',
                       'status': 'ok', 'detail': ''})

    for ap in d['aps']:
        parts = []
        if ap.get('clients_2g', 0):
            parts.append(f'ch{ap["ch2g"]} {ap["clients_2g"]}台')
        if ap.get('clients_5g', 0):
            parts.append(f'ch{ap["ch5g"]} {ap["clients_5g"]}台')
        value = '  '.join(parts) if parts else f'{ap["total"]}台'
        panel.append({'source': 'unifi',
                       'label': ap['name'],
                       'value': value,
                       'status': 'ok', 'detail': ''})

    return panel


def build_network_snapshot(unifi: UniFiClient) -> str:
    """构建网络状态快照文本（发给 LLM）。"""
    d = _gather_network_data(unifi)
    lines = ['## 网络状态']

    if d['wan_ip'] == '?' and d['wan2_ip'] is None:
        lines.append('WAN: 获取失败')
    else:
        wan_line = f'WAN: {d["wan_ip"]}'
        if d['wan2_ip']:
            wan_line += f'  备线: {d["wan2_ip"]}'

        speed = f'↑{_fmt_bps(d["tx_bps"])} ↓{_fmt_bps(d["rx_bps"])}'
        if d['latency_ms'] is not None:
            speed += f'  {d["latency_ms"]}ms'
        lines.append(f'{wan_line}  {speed}')

    for ap in d['aps']:
        parts = []
        if ap.get('clients_2g', 0):
            parts.append(f'ch{ap["ch2g"]}={ap["clients_2g"]}')
        if ap.get('clients_5g', 0):
            parts.append(f'ch{ap["ch5g"]}={ap["clients_5g"]}')
        sn = ' '.join(parts)
        lines.append(f'{ap["name"]}: {sn}')

    return '\n'.join(lines)
