import asyncio
import json
import random
import re

from astrbot.api import logger
from astrbot.api.all import AstrBotConfig
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Plain
from astrbot.api.star import Context, Star, register
from astrbot.core.message.message_event_result import MessageChain


@register("astrbot_plugin_split_multirole_reply", "ThinkNaive", "分割多人格回复",
          "v1.0")
class SplitMultiroleReply(Star):

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.context = context
        # 确保 config 存在
        self.config = config or {}
        # 获取人格列表配置
        self.role = self.config.get("role", [])
        # 获取回复延迟配置
        self.delay_min = 1.0
        self.delay_max = 3.0
        delay_range = self.config.get("random_delay_range", [1, 3])
        if isinstance(delay_range, list) and len(delay_range) >= 2:
            try:
                self.delay_min = min(float(delay_range[0]),
                                     float(delay_range[1]))
                self.delay_max = max(float(delay_range[0]),
                                     float(delay_range[1]))
            except (ValueError, TypeError):
                pass

    @filter.on_decorating_result()
    async def handle_multirole_reply(self, event: AstrMessageEvent):
        result = event.get_result()
        if not result or not result.chain:
            return

        raw_text = ""
        for comp in result.chain:
            if isinstance(comp, Plain):
                raw_text += comp.text.strip()
        raw_text = raw_text.strip()
        if not raw_text:
            return

        try:
            logger.info(f"——准备进行多人格分段（原回复长度：{len(raw_text)}字符）——")

            segments = self._segment_reply_by_role(raw_text)

            if not segments or len(segments) <= 1:
                logger.info("——分段完成，无需拆分，保持1段输出——")
                return

            full_segmented_text = "\n\n".join(segments)

            result.chain.clear()

            for i, segment in enumerate(segments):
                if i > 0:
                    delay = random.uniform(self.delay_min, self.delay_max)
                    await asyncio.sleep(delay)
                await event.send(MessageChain().message(segment))

            await self._save_to_conversation_history(event,
                                                     full_segmented_text)

            logger.info(f"——本地规则分段回复成功，共分{len(segments)}段——")

        except Exception as e:
            logger.error(f"——本地规则分段异常，发送原消息。失败原因：{str(e)}——")
            return

    def _segment_reply_by_role(self, text: str) -> list[str]:
        final_segments = []
        # 匹配以'【role】：'开头的语句
        escaped = ([re.escape(name) for name in self.role]
                   if len(self.role) > 0 else ["UNKNOWN"])
        pattern = re.compile(r"(【(?:" + "|".join(escaped) + r")】(:|：))",
                             re.MULTILINE)
        # pattern = re.compile(r"^(【(?:" + "|".join(escaped) + r")】(:|：))",
        #                 re.MULTILINE)

        prev = 0
        for m in pattern.finditer(text):
            if m.start() == 0:
                continue
            final_segments.append(text[prev:m.start()])
            prev = m.start()
        final_segments.append(text[prev:])

        return final_segments

    async def _save_to_conversation_history(self, event: AstrMessageEvent,
                                            content: str):
        try:
            conv_mgr = self.context.conversation_manager
            if not conv_mgr:
                return

            umo = event.unified_msg_origin
            curr_cid = await conv_mgr.get_curr_conversation_id(umo)

            if curr_cid:
                conversation = await conv_mgr.get_conversation(umo, curr_cid)
                if conversation:
                    try:
                        history = (json.loads(conversation.history)
                                   if isinstance(conversation.history, str)
                                   else conversation.history)
                    except Exception:
                        history = []

                    user_content = event.message_str
                    if user_content:
                        if not history or history[-1].get("role") != "user":
                            history.append({
                                "role": "user",
                                "content": user_content
                            })

                    history.append({"role": "assistant", "content": content})

                    await conv_mgr.update_conversation(
                        unified_msg_origin=umo,
                        conversation_id=curr_cid,
                        history=history,
                    )
        except Exception as e:
            logger.error(f"——保存对话历史失败: {str(e)}——")

    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""
