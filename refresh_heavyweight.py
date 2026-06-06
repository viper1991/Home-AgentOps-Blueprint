"""重型刷新入口（Cron: 5 * * * *）。

Agent Loop 全流程：快照 → LLM Agent（1工具/轮）→ final_output → Display。
"""
import logging
import sys

from lib.config import load_config
from lib.clients.ha_client import HAClient
from lib.clients.unifi_client import UniFiClient
from lib.tools.base import ToolRegistry
from lib.tools.room_status import GetRoomStatusTool
from lib.tools.trend import GetTrendTool
from lib.tools.events import GetEventsTool
from lib.tools.wifi_env import GetWifiEnvironmentTool
from lib.tools.client_status import GetClientStatusTool
from lib.tools.final_output import FinalOutputTool
from lib.tools.traffic_analysis import GetTrafficAnalysisTool
from lib.tools.device_inventory import GetDeviceInventoryTool
from lib.tools.network_alarms import GetNetworkAlarmsTool
from lib.agent.snapshot import SnapshotBuilder
from lib.agent.orchestrator import Orchestrator
from lib.llm.deepseek import DeepSeekProvider
from lib.working_memory import WorkingMemory
from lib.display.protocol import DisplayClient

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
)
logger = logging.getLogger('refresh_heavyweight')


def main():
    # 夜间休眠：22:00-08:00 不执行
    from datetime import datetime
    hour = datetime.now().hour
    if hour >= 22 or hour < 8:
        logger.info('夜间休眠时段（22:00-08:00），跳过重量级刷新')
        return

    config = load_config()

    # ── 初始化客户端 ──
    ha = HAClient(config.ha.url, config.ha.token)
    unifi = UniFiClient(
        config.unifi.url,
        config.unifi.username,
        config.unifi.password,
        site=config.unifi.site,
        timeout=30.0,
    )

    # ── 加载实体目录 ──
    import yaml
    try:
        with open('config/entity_catalog.yaml', 'r', encoding='utf-8') as f:
            entity_catalog = yaml.safe_load(f)
    except Exception as e:
        logger.error('Failed to load entity_catalog: %s', e)
        sys.exit(1)

    # ── 构建首轮快照 ──
    snapshot = SnapshotBuilder(ha, unifi, entity_catalog).build()
    logger.info('Snapshot built (%d chars)', len(snapshot))

    # ── 注册工具 ──
    tools = ToolRegistry()
    tools.register(GetRoomStatusTool(ha, entity_catalog.get('rooms', []),
                                     max_calls=config.agent.max_room_status_calls))
    tools.register(GetTrendTool(ha, max_calls=config.agent.max_trend_calls,
                                max_hours=config.agent.max_trend_hours))
    tools.register(GetEventsTool(ha, unifi))
    tools.register(GetWifiEnvironmentTool(unifi))
    tools.register(GetClientStatusTool(unifi))
    tools.register(GetTrafficAnalysisTool(unifi))
    tools.register(GetDeviceInventoryTool(unifi))
    tools.register(GetNetworkAlarmsTool(unifi))
    tools.register(FinalOutputTool())

    # ── LLM Provider ──
    llm = DeepSeekProvider(
        model=config.llm.model,
        base_url=config.llm.base_url,
        api_key_env=config.llm.api_key_env,
        max_tokens=config.llm.max_tokens_per_turn,
        temperature=config.llm.temperature,
    )

    # ── 工作记忆（含最近 5 次 summary 供 LLM 参考） ──
    mem = WorkingMemory(
        outputs_dir=config.working_memory.outputs_dir,
        keep_count=config.working_memory.keep_count,
        dedup_check_recent=config.working_memory.dedup_check_recent,
    )
    recent_outputs = mem.list_recent(5)
    recent_summaries = [o.get('summary', []) for o in recent_outputs if o.get('summary')]

    # ── Agent Loop ──
    orchestrator = Orchestrator(
        llm, tools, snapshot,
        max_rounds=config.agent.max_rounds,
        tools_per_round=config.agent.tools_per_round,
        recent_summaries=recent_summaries,
    )
    output = orchestrator.run()

    # 网络面板和事件面板由系统生成，LLM 不参与
    from lib.network_panel import build_network_panel
    from refresh_lightweight import _update_events
    output['network_panel'] = build_network_panel(unifi)
    output['events_panel'] = _update_events(output, ha, unifi)

    logger.info('Agent completed with %d sensors, %d network, %d events',
                len(output.get('sensor_panel', [])),
                len(output.get('network_panel', [])),
                len(output.get('events_panel', [])))

    if not mem.is_duplicate(output):
        mem.save(output)
        client = DisplayClient(
            host=config.display.daemon_host,
            port=config.display.daemon_port,
        )
        ok = client.render(output, mode='full')
        if ok:
            logger.info('Display rendered (full)')
        else:
            logger.warning('Display render failed')
    else:
        logger.info('Duplicate output, skipping display')


if __name__ == '__main__':
    main()
