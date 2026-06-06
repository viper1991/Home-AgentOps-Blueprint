"""Home Assistant REST API 客户端。

提供 states / history / logbook 三个核心接口。
"""
import logging
from datetime import datetime, timezone
from typing import Any

import requests

logger = logging.getLogger(__name__)


class HAClient:
    """HA REST API 客户端。"""

    def __init__(self, url: str, token: str, timeout: float = 10.0):
        self._url = url.rstrip('/')
        self._headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
        }
        self._timeout = timeout

    def _get(self, path: str, params: dict | None = None) -> Any:
        """发起 GET 请求，统一错误处理。"""
        resp = requests.get(
            f'{self._url}{path}',
            headers=self._headers,
            params=params,
            timeout=self._timeout,
        )
        resp.raise_for_status()
        return resp.json()

    # ── State API ──

    def get_state(self, entity_id: str) -> dict:
        """获取单个实体的完整状态。"""
        return self._get(f'/api/states/{entity_id}')

    def get_states(self) -> list[dict]:
        """获取所有实体的状态列表（全量 ~500KB）。"""
        return self._get('/api/states')

    def get_states_batch(self, entity_ids: list[str]) -> list[dict]:
        """批量获取多个实体的状态，逐个调用（HA 无批量端点）。"""
        results = []
        for eid in entity_ids:
            try:
                results.append(self.get_state(eid))
            except requests.RequestException as e:
                logger.warning('get_state(%s) failed: %s', eid, e)
                results.append({'entity_id': eid, 'state': 'unavailable', 'attributes': {}})
        return results

    # ── History API ──

    def get_history(
        self,
        entity_id: str,
        start_time: datetime,
        end_time: datetime | None = None,
    ) -> list[dict]:
        """获取实体历史数据点。

        HA API 期望 UTC 时间。
        GET /api/history/period/{start_utc}?filter_entity_id={entity_id}&end_time={end_utc}
        """
        params = {'filter_entity_id': entity_id}
        ts = start_time.astimezone(timezone.utc).isoformat()
        if end_time:
            params['end_time'] = end_time.astimezone(timezone.utc).isoformat()

        data = self._get(f'/api/history/period/{ts}', params=params)
        # 返回格式: [[{...}, {...}, ...]]  — 外层数组每个元素是一个实体的历史列表
        if data and isinstance(data, list) and len(data) > 0:
            return data[0] if isinstance(data[0], list) else data
        return []

    # ── Logbook API ──

    def get_logbook(
        self,
        start_time: datetime,
        end_time: datetime | None = None,
    ) -> list[dict]:
        """获取事件日志。

        HA API 期望 UTC 时间，需将 datetime 转为 UTC ISO 格式。
        GET /api/logbook/{start_utc}?end_time={end_utc}
        """
        params: dict = {}
        ts = start_time.astimezone(timezone.utc).isoformat()
        if end_time:
            params['end_time'] = end_time.astimezone(timezone.utc).isoformat()

        return self._get(f'/api/logbook/{ts}', params=params)
