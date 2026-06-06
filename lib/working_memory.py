"""工作记忆：最近 N 次 final_output 的持久化与去重。

将每次 final_output 存入 outputs/ 目录（JSON 文件），
并提供最近 N 次输出的读取和去重检查。
"""
import json
import logging
import os
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_KEEP_COUNT = 10
DEFAULT_OUTPUTS_DIR = 'outputs'
DEFAULT_DEDUP_CHECK_RECENT = 3


class WorkingMemory:
    """管理最近 N 次 final_output 的读写与去重。"""

    def __init__(self, outputs_dir: str = DEFAULT_OUTPUTS_DIR,
                 keep_count: int = DEFAULT_KEEP_COUNT,
                 dedup_check_recent: int = DEFAULT_DEDUP_CHECK_RECENT):
        self._dir = outputs_dir
        self._keep = keep_count
        self._dedup_n = dedup_check_recent
        os.makedirs(self._dir, exist_ok=True)

    # ── 文件管理 ──

    def _list_files(self) -> list[str]:
        """按修改时间排序的输出文件列表（最新在前）。"""
        files = []
        for f in os.listdir(self._dir):
            if f.endswith('.json'):
                path = os.path.join(self._dir, f)
                files.append((os.path.getmtime(path), path))
        files.sort(key=lambda x: x[0], reverse=True)
        return [f[1] for f in files]

    def save(self, data: dict) -> str:
        """保存 final_output 到 outputs/，并清理超出 keep_count 的老文件。

        Returns:
            文件路径。
        """
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        path = os.path.join(self._dir, f'{ts}.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info('Saved output: %s', path)

        # 清理旧文件
        files = self._list_files()
        for old in files[self._keep:]:
            try:
                os.remove(old)
                logger.debug('Removed old output: %s', old)
            except OSError as e:
                logger.warning('Failed to remove %s: %s', old, e)

        return path

    def load_last(self) -> dict | None:
        """加载最近一次 final_output。"""
        files = self._list_files()
        if not files:
            return None
        try:
            with open(files[0], 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.error('Failed to load %s: %s', files[0], e)
            return None

    def list_recent(self, n: int | None = None) -> list[dict]:
        """返回最近 N 次 final_output 列表（最新在前）。"""
        count = n or self._keep
        files = self._list_files()[:count]
        results = []
        for f in files:
            try:
                with open(f, 'r', encoding='utf-8') as fh:
                    results.append(json.load(fh))
            except (json.JSONDecodeError, OSError) as e:
                logger.warning('Failed to read %s: %s', f, e)
        return results

    # ── 去重 ──

    def is_duplicate(self, data: dict) -> bool:
        """检查 data 是否与最近 N 次输出重复（基于 sensor_panel 的数值摘要）。"""
        recent = self.list_recent(self._dedup_n)
        if not recent:
            return False

        # 提取当前摘要（sensor_panel 的 entity_id → value 映射）
        current_sig = self._signature(data)

        for prev in recent:
            if current_sig == self._signature(prev):
                logger.info('Duplicate output detected (same sensor values)')
                return True

        return False

    @staticmethod
    def _signature(data: dict) -> frozenset:
        """从 final_output 提取去重签名（sensor 的 (label, value) 元组）。"""
        sensor_panel = data.get('sensor_panel', []) or []
        pairs = tuple(
            (item.get('label', ''), item.get('value', ''))
            for item in sensor_panel if isinstance(item, dict)
        )
        return frozenset(pairs)
