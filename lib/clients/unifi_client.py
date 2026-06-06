"""UniFi Controller REST API 客户端。

提供 health / device / sta / rogueap / event 接口。
自动处理登录认证（Cookie + CSRF Token）。
"""
import logging
import re
from typing import Any

import requests

logger = logging.getLogger(__name__)


class UniFiClient:
    """UniFi Controller REST API 客户端。"""

    def __init__(self, url: str, username: str, password: str, site: str = 'default',
                 timeout: float = 60.0, verify_ssl: bool = False):
        self._base = url.rstrip('/')
        self._username = username
        self._password = password
        self._site = site
        self._timeout = timeout
        self._verify_ssl = verify_ssl
        self._session = requests.Session()
        self._session.verify = verify_ssl
        self._csrf_token: str | None = None

    # ── 会话管理 ──

    def _ensure_logged_in(self):
        """检查并维持登录状态。"""
        # 简单方案：每次调用前尝试登录（UniFi 会话较短）
        self._login()

    def _login(self):
        """登录 UniFi Controller。"""
        try:
            resp = self._session.post(
                f'{self._base}/api/login',
                json={
                    'username': self._username,
                    'password': self._password,
                    'remember': True,
                },
                timeout=self._timeout,
            )
            resp.raise_for_status()
            # 提取 CSRF Token
            csrf = resp.headers.get('x-csrf-token')
            if csrf:
                self._csrf_token = csrf
            logger.info('UniFi login success')
        except requests.RequestException as e:
            logger.error('UniFi login failed: %s', e)
            raise

    def _get(self, path: str) -> Any:
        """发起经过认证的 GET 请求。"""
        self._ensure_logged_in()
        headers = {}
        if self._csrf_token:
            headers['X-Csrf-Token'] = self._csrf_token

        resp = self._session.get(
            f'{self._base}{path}',
            headers=headers,
            timeout=self._timeout,
        )
        resp.raise_for_status()

        # 更新 CSRF Token（每次响应可能刷新）
        csrf = resp.headers.get('x-csrf-token')
        if csrf:
            self._csrf_token = csrf

        data = resp.json()
        return data.get('data', data)

    # ── API 方法 ──

    def get_health(self) -> list[dict]:
        """获取网络健康状态。返回各子系统健康数据。"""
        return self._get(f'/api/s/{self._site}/stat/health')

    def get_devices(self) -> list[dict]:
        """获取所有 UniFi 设备（AP/网关/交换机）列表。"""
        return self._get(f'/api/s/{self._site}/stat/device')

    def get_clients(self) -> list[dict]:
        """获取所有在线 WiFi 客户端。"""
        return self._get(f'/api/s/{self._site}/stat/sta')

    def get_rogue_aps(self) -> list[dict]:
        """获取周围干扰 AP（rogue AP）列表。"""
        return self._get(f'/api/s/{self._site}/stat/rogueap')

    def get_events(self, limit: int = 50) -> list[dict]:
        """获取近期网络事件。"""
        return self._get(f'/api/s/{self._site}/stat/event?limit={limit}')

    def get_dpi_summary(self) -> dict:
        """获取 DPI 流量摘要（按分类 + 按应用）。"""
        return self._get(f'/api/s/{self._site}/stat/dpi')

    def get_dpi_by_app(self) -> list[dict]:
        """获取 DPI 按应用流量排行。"""
        return self._get(f'/api/s/{self._site}/stat/sitedpi?type=by_app')

    def get_dpi_by_cat(self) -> list[dict]:
        """获取 DPI 按分类流量排行。"""
        return self._get(f'/api/s/{self._site}/stat/sitedpi?type=by_cat')

    def get_all_users(self) -> list[dict]:
        """获取所有已知用户（历史+在线）。"""
        return self._get(f'/api/s/{self._site}/stat/alluser')

    def get_alarms(self) -> list[dict]:
        """获取网络告警列表。"""
        return self._get(f'/api/s/{self._site}/stat/alarm')
