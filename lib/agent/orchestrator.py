"""Agent Loop 编排引擎。

核心循环（1工具/轮约束）：
  1. 首轮快照（user message）+ 系统提示词
  2. LLM 响应 → 提取工具调用（截断至第 1 个）
  3. 执行工具 → 结果追加到 messages
  4. 循环直到 max_rounds 或 LLM 输出 final_output
"""
import json
import logging
import time
from typing import Any

from lib.llm.provider import LLMProvider, LLMResponse
from lib.tools.base import ToolRegistry
from lib.interaction_log import InteractionLog
from lib.prompts import Prompts

logger = logging.getLogger(__name__)


class Orchestrator:
    """Agent Loop 编排引擎。"""

    def __init__(
        self,
        llm: LLMProvider,
        tools: ToolRegistry,
        snapshot: str,
        max_rounds: int = 6,
        tools_per_round: int = 1,
        recent_summaries: list[list[str]] | None = None,
    ):
        self._llm = llm
        self._tools = tools
        self._snapshot = snapshot
        self._max_rounds = max_rounds
        self._tools_per_round = tools_per_round
        self._interaction_log = InteractionLog()
        self._round_counter = 0
        self._prompts = Prompts.load()
        self._recent_summaries = recent_summaries or []

    def _llm_chat(
        self,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
        response_format: dict | None = None,
        interaction_type: str = 'normal',
    ) -> LLMResponse:
        """包装 llm.chat()，自动记录输入输出日志和耗时。

        当 tools=None 且 response_format={'type': 'json_object'} 时，
        DeepSeek 强制输出合法 JSON（需 prompt 包含 json 字样）。
        """
        self._round_counter += 1
        round_num = self._round_counter

        t0 = time.monotonic()
        try:
            response = self._llm.chat(messages, tools=tools, response_format=response_format)
        except Exception:
            duration = int((time.monotonic() - t0) * 1000)
            InteractionLog.log_console(round_num, f'{interaction_type}(ERROR)', messages, LLMResponse(), duration)
            raise

        duration = int((time.monotonic() - t0) * 1000)

        # 文件日志（完整内容）
        self._interaction_log.record(round_num, interaction_type, messages, response, duration)

        # 控制台摘要
        InteractionLog.log_console(round_num, interaction_type, messages, response, duration)

        return response

    def run(self) -> dict:
        """运行 Agent Loop，返回 final_output 数据。"""
        # ── 1. 构建首轮 messages ──
        snapshot_content = self._snapshot
        if self._recent_summaries:
            snapshot_content += '\n\n## 近期摘要参考\n'
            for i, s in enumerate(self._recent_summaries, 1):
                if isinstance(s, list):
                    items = []
                    for item in s:
                        if isinstance(item, dict):
                            items.append(str(item.get('content', item.get('title', str(item)))))
                        else:
                            items.append(str(item))
                    lines = '；'.join(items)
                else:
                    lines = str(s)
                snapshot_content += f'{i}. {lines}\n'

        messages = [
            {'role': 'system', 'content': self._prompts.system_prompt},
            {'role': 'user', 'content': snapshot_content},
        ]

        # ── 2. Agent Loop ──
        for round_idx in range(self._max_rounds + 1):
            logger.info('Agent round %d/%d', round_idx + 1, self._max_rounds + 1)

            # 最后一轮仅保留 final_output，强制 LLM 提交
            is_last_round = (round_idx == self._max_rounds)
            tool_defs = self._tools.get_openai_tool_defs()
            if is_last_round:
                tool_defs = [t for t in tool_defs
                             if t.get('function', {}).get('name') == 'final_output']

            response = self._llm_chat(
                messages,
                tools=tool_defs if tool_defs else None,
                interaction_type='round',
            )

            if not response.tool_calls:
                # LLM 没有调用工具 → 期待它输出文本（退出循环）
                logger.info('LLM returned no tool calls, exiting loop')
                break

            # ── 3. 截断至 tools_per_round 个工具调用 ──
            all_calls = response.tool_calls[:self._tools_per_round]
            discarded = len(response.tool_calls) - len(all_calls)
            reasoning = (response.assistant_message or {}).get('reasoning_content', '') or ''

            # 先执行所有工具，收集结果
            results: list[dict] = []
            for tool_call in all_calls:
                tool_name = tool_call['function']['name']
                tool_args = tool_call['function']['arguments']

                # 检查配额
                if self._tools.is_exhausted(tool_name):
                    logger.warning('Tool %s exhausted, notifying LLM', tool_name)
                    results.append({
                        'role': 'tool',
                        'tool_call_id': tool_call['id'],
                        'content': json.dumps(
                            {'error': self._prompts.get_message('quota_exhausted', tool_name=tool_name)},
                            ensure_ascii=False,
                        ),
                    })
                    continue

                # 执行工具（含 JSON 格式校验 + 自动修复）
                logger.info('Tool call: %s(%s)', tool_name, str(tool_args)[:200])
                result = self._execute_with_retry(messages, tool_call, reasoning=reasoning)

                if result is None:
                    results.append({
                        'role': 'tool',
                        'tool_call_id': tool_call['id'],
                        'content': json.dumps({'error': '工具执行失败，请尝试其他方式获取信息'}, ensure_ascii=False),
                    })
                    continue

                self._tools.increment(tool_name)

                # 如果调用了 final_output，直接提取返回
                if tool_name == 'final_output':
                    logger.info('Agent completed with final_output in %d rounds', round_idx + 1)
                    if isinstance(result, dict):
                        return result
                    if isinstance(tool_args, str):
                        return json.loads(tool_args)
                    return tool_args

                results.append({
                    'role': 'tool',
                    'tool_call_id': tool_call['id'],
                    'content': json.dumps(result, ensure_ascii=False),
                })

            # ── 4. 追加 assistant 消息（在 tool results 之前） ──
            asst_msg = dict(response.assistant_message) if response.assistant_message else {
                'role': 'assistant', 'content': None}
            asst_msg['tool_calls'] = all_calls
            messages.append(asst_msg)

            # ── 5. 追加 tool 结果 ──
            messages.extend(results)

            # 如果有被丢弃的工具调用，给 LLM 一个提示
            if discarded > 0:
                messages.append({
                    'role': 'user',
                    'content': self._prompts.get_message('discarded_tool_call'),
                })

        # ── 6. 循环结束但没有 final_output — 让 LLM 再试一次（仅含 final_output） ──
        logger.warning('Agent loop exhausted without final_output, retrying with only final_output')
        final_tools = [
            self._tools.get('final_output').to_openai_tool()
        ] if self._tools.get('final_output') else []

        # 追加一条提示，要求 LLM 立即提交
        messages.append({
            'role': 'user',
            'content': self._prompts.get_message('fallback_prompt'),
        })

        response = self._llm_chat(messages, tools=final_tools if final_tools else None,
                                  interaction_type='fallback')

        if response.tool_calls:
            tc = response.tool_calls[0]
            if tc['function']['name'] == 'final_output':
                args = tc['function']['arguments']
                try:
                    if isinstance(args, str):
                        parsed = self._try_extract_json(args)
                        if parsed and 'sensor_panel' in parsed:
                            return parsed
                        return json.loads(args)
                    return args
                except (json.JSONDecodeError, ValueError) as e:
                    logger.error('Fallback final_output JSON/validation error: %s', e)
                    # 最后尝试：先补上 assistant 消息，再回传 tool 结果
                    #（否则 API 报 tool must follow a message with tool_calls）
                    messages.append({
                        'role': 'assistant',
                        'content': None,
                        'tool_calls': [tc],
                    })
                    messages.append({
                        'role': 'tool',
                        'tool_call_id': tc['id'],
                        'content': json.dumps({'error': f'参数格式错误: {e}'}, ensure_ascii=False),
                    })
                    messages.append({
                        'role': 'user',
                        'content': self._prompts.get_message('fallback_fix_request'),
                    })
                    final_resp = self._llm_chat(messages, tools=None,
                                                response_format={'type': 'json_object'},
                                                interaction_type='fallback_fix')
                    if final_resp.content:
                        fixed = self._try_extract_json(final_resp.content)
                        if fixed and 'sensor_panel' in fixed:
                            return fixed

        # 最终退路
        logger.error('No final_output obtained even after retry')
        return self._default_output()

    def _execute_with_retry(self, messages: list, tool_call: dict,
                            reasoning: str = '') -> Any:
        """执行工具，参数格式错误时丢回 LLM 修复（不提供工具），最多重试一次。

        Args:
            reasoning: 原始 LLM 响应的 reasoning_content（thinking mode），
                       修复轮中也需要回传以保持 thinking 上下文。
        """
        tool_name = tool_call['function']['name']
        tool_args = tool_call['function']['arguments']

        for attempt in range(2):  # 原始尝试 + 1 次修复
            try:
                return self._tools.execute(tool_name, tool_args)
            except json.JSONDecodeError as e:
                logger.warning('JSON parse error in %s: %s', tool_name, e)
                if attempt == 1:
                    logger.error('JSON fix failed for %s, giving up', tool_name)
                    return None

                # 通知 LLM 参数格式错误，要求修复（不提供任何工具）
                err_msg = f'❌ 工具 {tool_name} 的参数 JSON 格式错误：{e}\n\n请仅输出修复后的 JSON 参数，不要调用任何工具。'
                asst = {'role': 'assistant', 'content': None, 'tool_calls': [tool_call]}
                if reasoning:
                    asst['reasoning_content'] = reasoning
                messages.append(asst)
                messages.append({
                    'role': 'tool',
                    'tool_call_id': tool_call['id'],
                    'content': json.dumps({'error': err_msg}, ensure_ascii=False),
                })
                messages.append({
                    'role': 'user',
                    'content': self._prompts.get_message('json_fix_request'),
                })

                fix_resp = self._llm_chat(messages, tools=None,
                                          response_format={'type': 'json_object'},
                                          interaction_type='fix_retry')
                if not fix_resp.content:
                    logger.warning('LLM returned empty fix response')
                    return None

                fixed = self._try_extract_json(fix_resp.content)
                if fixed is not None:
                    # 验证提取的结果是 dict 而非 list/str，否则拒绝
                    if isinstance(fixed, dict):
                        tool_args = json.dumps(fixed, ensure_ascii=False)
                        logger.info('JSON fixed for %s, retrying', tool_name)
                        continue
                    else:
                        logger.warning('Fixed JSON has wrong type: %s, expected dict', type(fixed).__name__)
                        return None

                logger.warning('Could not extract valid JSON from fix response')
                return None

            except (ValueError, TypeError) as e:
                # final_output 等工具的校验失败
                logger.warning('Argument validation error in %s: %s', tool_name, e)
                if attempt == 1:
                    logger.error('Validation fix failed for %s, giving up', tool_name)
                    return None

                err_msg = f'❌ 工具 {tool_name} 的参数校验失败：{e}'
                messages.append({
                    'role': 'assistant',
                    'content': None,
                    'tool_calls': [tool_call],
                })
                messages.append({
                    'role': 'tool',
                    'tool_call_id': tool_call['id'],
                    'content': json.dumps({'error': err_msg}, ensure_ascii=False),
                })
                messages.append({
                    'role': 'user',
                    'content': self._prompts.get_message('validation_fix_request'),
                })

                fix_resp = self._llm_chat(messages, tools=None,
                                          response_format={'type': 'json_object'},
                                          interaction_type='fix_retry')
                if not fix_resp.content:
                    return None

                fixed = self._try_extract_json(fix_resp.content)
                if fixed is not None and isinstance(fixed, dict):
                    tool_args = json.dumps(fixed, ensure_ascii=False)
                    logger.info('Arguments fixed for %s, retrying', tool_name)
                    continue
                elif fixed is not None:
                    logger.warning('Fixed JSON has wrong type: %s, expected dict', type(fixed).__name__)
                    return None

                return None

        return None  # 不应到达

    @staticmethod
    def _try_extract_json(text: str) -> dict | None:
        """从 LLM 文本回复中提取 JSON 对象。"""
        if not text:
            return None
        text = text.strip()

        # 尝试直接解析整个文本
        if text.startswith('{'):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                pass

        # 尝试从代码块中提取：```json ... ```
        import re
        code_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        if code_match:
            try:
                return json.loads(code_match.group(1).strip())
            except json.JSONDecodeError:
                pass

        # 尝试找到第一个 { 到匹配的 }
        brace_match = re.search(r'\{.*\}', text, re.DOTALL)
        if brace_match:
            try:
                return json.loads(brace_match.group())
            except json.JSONDecodeError:
                pass

        return None

    @staticmethod
    def _default_output() -> dict:
        """兜底：当 LLM 完全无法生成 final_output 时返回默认值。"""
        return {
            'sensor_panel': [],
            'network_panel': [
                {'source': 'system', 'label': '状态', 'value': '仪表盘生成失败',
                 'status': 'error', 'detail': 'LLM 未返回有效输出'},
            ],
            'events_panel': [],
            'summary': ['仪表盘数据获取异常'],
        }
