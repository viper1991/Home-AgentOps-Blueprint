#!/usr/bin/env python3
"""Probe UniFi for dual WAN info on USG.
用法: 从项目根目录运行: python scripts/check_wan.py
"""
import os
import sys
import yaml
import json

# 确保项目根在 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.clients.unifi_client import UniFiClient

cfg = yaml.safe_load(open('config/config.yaml', encoding='utf-8'))
u = UniFiClient(cfg['unifi']['url'], cfg['unifi']['username'], cfg['unifi']['password'], timeout=20.0)

devices = u.get_devices()
for d in devices:
    model = d.get('model', '')
    if 'usg' not in model.lower():
        continue
    print(f'=== {model} {d.get("name","")} ===')

    # 1. Port table - WAN ports
    pt = d.get('port_table', [])
    print(f'\nPorts ({len(pt)}):')
    for p in pt:
        port_idx = p.get('port_idx', '?')
        name = p.get('name', f'port{port_idx}')
        up = p.get('up', '?')
        ip = p.get('ip', '')
        media = p.get('media', '')
        speed = p.get('speed', '')
        full_dup = p.get('full_duplex', '')
        mac = p.get('mac', '')[:8]
        print(f'  {name:12s}  up={up}  ip={ip:20s}  speed={speed}  media={media}  mac={mac}')

    # 2. network_groups - has WAN0/WAN1 info
    ng = d.get('network_groups', {})
    if isinstance(ng, dict):
        print(f'\nNetwork groups:')
        for k, v in ng.items():
            if isinstance(v, dict) and 'name' in v:
                print(f'  {k}: name={v.get("name")}, ifname={v.get("ifname")}, ip={v.get("ip","")}, up={v.get("up")}, speed={v.get("speed")}, mac={str(v.get("mac",""))[:8]}')
            else:
                print(f'  {k}: {str(v)[:100]}')

    # 3. Check for wan1/wan2 fields
    for k in sorted(d.keys()):
        if k.startswith('wan') or k.startswith('WAN'):
            print(f'\n{d["model"]}.{k}: {json.dumps(d[k], indent=2, ensure_ascii=False)[:300]}')
