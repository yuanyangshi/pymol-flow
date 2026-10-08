"""Core PyMOL Agent execution loop and message history management."""

from __future__ import annotations

import json
import random
import re
import time
from typing import Any, Callable

from ..api_client import get_client
from ..config import (
    api_key,
    enable_thinking as config_enable_thinking,
    max_history_messages as config_max_history,
    max_tokens as config_max_tokens,
    max_tool_output_chars as config_max_tool_output,
    model,
    thinking_budget as config_thinking_budget,
    thinking_mode as config_thinking_mode,
)
from ..executor import PyMOLExecutor
from ..image_utils import encode_image_to_data_url
from .prompts import SYSTEM_PROMPT
from .router import should_enable_thinking
from .tools import TOOLS, can_confirm_directly

MAX_TOOL_ROUNDS = 4


def is_pure_greeting(text: str) -> bool:
    """Identify simple conversational greetings/chitchat that do not require tool invocation."""
    clean = re.sub(r"[^\w\u4e00-\u9fa5]", "", text.strip().lower())
    greetings = {
        "你好", "您好", "在吗", "在不在", "在么",
        "你好呀", "你好啊", "您好呀", "哈喽", "哈喽啊", "嗨", "嗨嗨",
        "早上好", "中午好", "下午好", "晚上好",
    }
    return clean in greetings


def generate_greeting_reply(messages: list[dict[str, Any]], scene_info: dict[str, Any]) -> str:
    """Generate dynamic, context-aware greetings that vary naturally instead of repeating a static template."""
    objects = [obj["name"] for obj in scene_info.get("objects", []) if "name" in obj]
    obj_list_str = "、".join(f"`{name}`" for name in objects[:5])
    extra_cnt = f"等共 {len(objects)} 个对象" if len(objects) > 5 else ""

    # Check if an introductory guide has already been presented in this conversation
    has_seen_guide = any(
        isinstance(m.get("content"), str)
        and ("我可以为你执行" in m.get("content") or "我可以帮你在" in m.get("content") or "常用功能速览" in m.get("content"))
        for m in messages
        if m.get("role") == "assistant"
    )

    if has_seen_guide:
        # Follow-up greetings: concise, dynamic, and non-repetitive
        if objects:
            followups = [
                f"在呢！当前场景中已有 {obj_list_str}。想做结构对齐、表面着色还是分析结合位点？随时告诉我。",
                f"你好呀！随时待命。针对当前加载的 {obj_list_str}，有什么需要我协助调整或测量的？",
                f"嗨！我一直在。需要测量原子距离、查看残基相互作用还是渲染高质量视图？",
                f"在的！告诉我接下来想对 {obj_list_str} 进行什么操作即可。",
            ]
        else:
            followups = [
                "在呢！随时待命，想加载哪个结构？直接告诉我 PDB ID（如 `fetch 6VXX`）即可。",
                "你好呀！当前场景还是空的，输入 PDB ID 或描述你的任务，我们马上开始。",
                "嗨！我一直在。告诉我你想执行的任务，随时为你操作 PyMOL。",
                "在的！有什么我可以帮你的？比如载入蛋白质、比对结构或设置显示模式。",
            ]
        last_assistant_msg = next((m.get("content") for m in reversed(messages) if m.get("role") == "assistant"), None)
        valid_followups = [f for f in followups if f != last_assistant_msg]
        return random.choice(valid_followups or followups)

    # First greeting: friendly, scene-aware introduction with quick guidance
    if objects:
        first_options = [
            (
                f"你好！👋\n\n"
                f"检测到当前 PyMOL 场景中已加载：{obj_list_str}{extra_cnt}。\n\n"
                f"我可以为你执行多种分子操作，比如：\n"
                f"- **结构对齐与比对**（计算并报告 RMSD）\n"
                f"- **可视化渲染**（cartoon、sticks、表面与电荷配色）\n"
                f"- **口袋与相互作用分析**（结合位点残基、氢键网络与空间碰撞）\n"
                f"- **位点标记与测量**（关键残基测量、突变展示等）\n\n"
                f"请告诉我你接下来想进行的操作！"
            ),
            (
                f"你好！👋 已检测到当前场景中的分子对象：{obj_list_str}{extra_cnt}。\n\n"
                f"随时可以开始分析或渲染：\n"
                f"- **口袋与相互作用**：如“高亮配体周围 4Å 的残基并显示氢键”\n"
                f"- **样式与着色**：如“按链着色并显示二级结构”\n"
                f"- **对齐比对**：如“将这两个对象对齐并输出 RMSD”\n\n"
                f"请告诉我你的具体任务！"
            ),
        ]
    else:
        first_options = [
            (
                "你好！👋\n\n"
                "我可以帮你在这个 PyMOL 会话里操作分子结构，比如：\n"
                "- **加载/获取结构**（输入 PDB ID，如 `fetch 6VXX` 或“加载 1ABC”）\n"
                "- **结构对齐、比较结合模式**（自动计算并报告 RMSD）\n"
                "- **可视化设置**（cartoon、sticks、surface、配色等）\n"
                "- **配体与口袋分析**（接触残基、氢键、距离、空间冲突）\n"
                "- **突变、选择、测量等操作**\n\n"
                "目前场景是空的。你想从哪个结构或任务开始？告诉我 PDB ID 或你的需求即可。"
            ),
            (
                "你好！👋 很高兴协助你进行分子结构操作与可视化。\n\n"
                "目前场景中暂无对象。常用功能速览：\n"
                "- **快速获取**：输入任意 PDB ID 即可自动载入（如 `fetch 1ABC`）\n"
                "- **结构分析**：支持口袋残基识别、氢键网络与空间碰撞检测\n"
                "- **展示效果**：卡通（cartoon）、棒状（sticks）、静电表面等一键切换\n\n"
                "你想从哪一步开始？直接发指令即可！"
            ),
        ]
    return random.choice(first_options)



class AgentReply(str):
    """String subclass that encapsulates response text along with thought, timing, and tool metadata."""

    thought: str = ""
    thought_duration: float = 0.0
    exec_duration: float = 0.0
    total_duration: float = 0.0
    tool_calls: list[dict[str, Any]] = []
    tool_rounds: int = 0

    def __new__(
        cls,
        content: str,
        thought: str = "",
        thought_duration: float = 0.0,
        exec_duration: float = 0.0,
        total_duration: float = 0.0,
        tool_calls: list[dict[str, Any]] | None = None,
        tool_rounds: int = 0,
    ):
        obj = super().__new__(cls, content)
        obj.thought = thought
        obj.thought_duration = thought_duration
        obj.exec_duration = exec_duration
        obj.total_duration = total_duration
        obj.tool_calls = tool_calls or []
        obj.tool_rounds = tool_rounds
        return obj


class PyMOLAgent:
    def __init__(
        self,
        executor: PyMOLExecutor | None = None,
        debug: Callable[[str], None] | None = None,
        client: Any | None = None,
        on_token: Callable[[str], None] | None = None,
        on_thought: Callable[[str], None] | None = None,
        on_tool_call: Callable[[dict[str, Any]], None] | None = None,
        enable_thinking: bool | str | None = None,
    ):
        key = api_key()
        if not key and client is None:
            raise RuntimeError(
                "An API key is required. Open ⋯ → API Key Settings… or configure DASHSCOPE_API_KEY in .env."
            )
        self.client = client if client is not None else get_client(key)
        self.executor = executor or PyMOLExecutor()
        self.debug = debug or (lambda _message: None)
        self.on_token = on_token or (lambda _token: None)
        self.on_thought = on_thought or (lambda _thought: None)
        self.on_tool_call = on_tool_call or (lambda _tool: None)
        self.enable_thinking = (
            enable_thinking if enable_thinking is not None else config_thinking_mode()
        )
        self.messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
        self._cancelled = False

    def cancel(self) -> None:
        """Signal the agent to abort its current execution loop immediately."""
        self._cancelled = True

    def _compact_conversation_history(self) -> None:
        """Compact conversation messages to bound token consumption and maximize prompt cache hits.

        1. Strip bulky ephemeral 'Current live scene: ...' JSON from completed historical turns,
           leaving only the clean semantic user request.
        2. Compact historical tool responses (from completed turns) to concise summaries.
        3. Form structured memory anchors when sliding window reaches maximum capacity.
        """
        # 1. Clean historical user messages (all except the latest active turn)
        user_indices = [i for i, m in enumerate(self.messages) if m.get("role") == "user"]
        if len(user_indices) > 1:
            for idx in user_indices[:-1]:
                content = self.messages[idx].get("content", "")
                if isinstance(content, str):
                    if "Current live scene:" in content and "\n\nUser request: " in content:
                        clean_req = content.split("\n\nUser request: ", 1)[-1].strip()
                        self.messages[idx]["content"] = clean_req
                elif isinstance(content, list):
                    # Multi-modal list of blocks: [{"type": "text", ...}, {"type": "image_url", ...}]
                    new_blocks = []
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            txt = block.get("text", "")
                            if "Current live scene:" in txt and "\n\nUser request: " in txt:
                                txt = txt.split("\n\nUser request: ", 1)[-1].strip()
                            new_blocks.append({"type": "text", "text": txt})
                        elif isinstance(block, dict) and block.get("type") == "image_url":
                            # Compact bulky historical image payloads to lightweight token placeholders
                            new_blocks.append({
                                "type": "text",
                                "text": "[Image: Previously provided in earlier turn]",
                            })
                        else:
                            new_blocks.append(block)
                    self.messages[idx]["content"] = new_blocks

        # 2. Compact bulky historical tool messages (older than current active turn)
        for m in self.messages[:-2]:
            if m.get("role") == "tool" and isinstance(m.get("content"), str):
                raw = m["content"]
                if len(raw) > 350:
                    try:
                        data = json.loads(raw)
                        if isinstance(data, dict):
                            out = data.get("output", "")
                            if isinstance(out, str) and len(out) > 200:
                                lines = [line.strip() for line in out.strip().splitlines() if line.strip()]
                                concise_out = "\n".join(lines[:3]) + f"\n... [compacted for cache from {len(out)} chars]"
                                data["output"] = concise_out
                                m["content"] = json.dumps(data, ensure_ascii=False)
                    except Exception:
                        m["content"] = raw[:200] + "... [compacted]"

        # 3. Dynamic Sliding Window with Structured Context Anchor
        max_hist = config_max_history()
        if len(self.messages) > max_hist:
            keep_count = max(4, int(max_hist * 0.7))
            discarded = self.messages[1:-keep_count]
            topics = []
            for disc in discarded:
                txt = disc.get("content", "")
                if isinstance(txt, list):
                    txt = " ".join(
                        b.get("text", "") for b in txt if isinstance(b, dict) and b.get("type") == "text"
                    )
                if isinstance(txt, str) and any(kw in txt.lower() for kw in ("load", "align", "preset", "plddt", "heatmap", "rmsd", "fetch", "sele", "image")):
                    topics.append(txt[:50].replace("\n", " "))

            tail = self.messages[-keep_count:]
            if topics:
                summary_sample = "; ".join(topics[:3])
                anchor_msg = {
                    "role": "system",
                    "content": f"[Context Memory Anchor: Earlier session operations included: {summary_sample}...]",
                }
                self.messages = [self.messages[0], anchor_msg] + tail
            else:
                self.messages = [self.messages[0]] + tail

    def _truncate_history_if_needed(self) -> None:
        """Alias for backward compatibility with existing tests and call sites."""
        self._compact_conversation_history()


    def ask(self, user_text: str, images: list[Any] | None = None) -> AgentReply:
        self._cancelled = False
        t_start = time.time()
        t_thought_end: float | None = None
        all_reasoning_chunks: list[str] = []
        executed_tools: list[dict[str, Any]] = []

        def build_reply(text_content: str, rounds: int) -> AgentReply:
            t_end = time.time()
            total_dur = max(0.05, t_end - t_start)
            if t_thought_end is not None:
                thought_dur = max(0.0, t_thought_end - t_start)
            elif all_reasoning_chunks:
                thought_dur = total_dur
            else:
                thought_dur = 0.0
            exec_dur = max(0.0, total_dur - thought_dur)
            return AgentReply(
                text_content,
                thought="".join(all_reasoning_chunks).strip(),
                thought_duration=thought_dur,
                exec_duration=exec_dur,
                total_duration=total_dur,
                tool_calls=executed_tools,
                tool_rounds=rounds,
            )

        scene = json.dumps(self.executor.scene_summary(), separators=(",", ":"))
        user_prompt = f"Current live scene: {scene}\n\nUser request: {user_text}"

        if images:
            content_blocks: list[dict[str, Any]] = [{"type": "text", "text": user_prompt}]
            for img in images:
                try:
                    data_url = encode_image_to_data_url(img)
                    content_blocks.append({
                        "type": "image_url",
                        "image_url": {"url": data_url},
                    })
                except Exception as exc:
                    self.debug(f"[Image Error] Failed to encode image: {exc}")
            self.messages.append({"role": "user", "content": content_blocks})
        else:
            self.messages.append({"role": "user", "content": user_prompt})

        thinking_mode = getattr(self, "enable_thinking", None)
        if thinking_mode is None:
            thinking_mode = config_thinking_mode()

        active_thinking = should_enable_thinking(user_text, thinking_mode)
        if active_thinking:
            self.debug(f"[Thinking Mode] Intelligently triggered deep reasoning for query: {user_text[:60]}")
        else:
            self.debug(f"[Thinking Mode] Fast mode active (thinking bypassed)")

        on_token_cb = getattr(self, "on_token", None)
        on_thought_cb = getattr(self, "on_thought", None)
        on_tool_cb = getattr(self, "on_tool_call", None)

        if not images and is_pure_greeting(user_text):
            scene_info = self.executor.scene_summary()
            greeting_text = generate_greeting_reply(self.messages, scene_info)
            if on_token_cb:
                for chunk in re.split(r"([，。、\n\s]+)", greeting_text):
                    if chunk:
                        on_token_cb(chunk)
            self.messages.append({"role": "user", "content": user_text})
            self.messages.append({"role": "assistant", "content": greeting_text})
            return build_reply(greeting_text, 0)

        consecutive_tool_failures = 0
        for _step in range(MAX_TOOL_ROUNDS + 1):
            if self._cancelled:
                return build_reply("操作已由用户手动取消。", _step)
            final_only = _step == MAX_TOOL_ROUNDS or consecutive_tool_failures >= 3
            extra_body: dict[str, Any] = {"enable_thinking": bool(active_thinking)}
            if active_thinking:
                extra_body["thinking_budget"] = config_thinking_budget()
            kwargs: dict[str, Any] = {
                "model": model(),
                "messages": list(self.messages),
                "extra_body": extra_body,
                "stream": True,
                "max_tokens": config_max_tokens(),
            }

            kwargs["tools"] = TOOLS
            if not final_only:
                kwargs["tool_choice"] = "auto"
            else:
                kwargs["tool_choice"] = "none"
                reason_msg = (
                    "Execution circuit breaker triggered due to consecutive failures. "
                    if consecutive_tool_failures >= 3
                    else "Command budget exhausted. "
                )
                self.messages.append({
                    "role": "user",
                    "content": (
                        f"{reason_msg}Please summarize verified results and scene observations now; "
                        "clearly state your findings and structural comparison for the user in Chinese. Do not request more tools."
                    ),
                })
                kwargs["messages"] = list(self.messages)

            completion = self.client.chat.completions.create(**kwargs)

            reasoning_chunks: list[str] = []
            content_chunks: list[str] = []
            tool_calls_dict: dict[int, dict[str, Any]] = {}

            # Handle both streaming chunks and non-streaming responses (for mocks/compatibility)
            if hasattr(completion, "choices"):
                msg = completion.choices[0].message
                reasoning = getattr(msg, "reasoning_content", None)
                if reasoning:
                    reasoning_chunks.append(reasoning)
                    all_reasoning_chunks.append(reasoning)
                    self.debug(f"[Thinking] {reasoning}")
                    if on_thought_cb:
                        on_thought_cb(reasoning)
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    if t_thought_end is None and all_reasoning_chunks:
                        t_thought_end = time.time()
                    for i, tc in enumerate(msg.tool_calls):
                        tool_calls_dict[i] = {
                            "id": getattr(tc, "id", "") or f"call_{i}",
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        }
                if getattr(msg, "content", None):
                    if t_thought_end is None and all_reasoning_chunks:
                        t_thought_end = time.time()
                    content_chunks.append(msg.content)
                    if on_token_cb and not tool_calls_dict:
                        on_token_cb(msg.content)
            else:
                for chunk in completion:
                    if self._cancelled:
                        return build_reply("操作已由用户手动取消。", _step)
                    if not getattr(chunk, "choices", None):
                        continue
                    delta = chunk.choices[0].delta
                    if hasattr(delta, "reasoning_content") and delta.reasoning_content is not None:
                        reasoning_chunks.append(delta.reasoning_content)
                        all_reasoning_chunks.append(delta.reasoning_content)
                        self.debug(f"[Thinking] {delta.reasoning_content}")
                        if on_thought_cb:
                            on_thought_cb(delta.reasoning_content)
                    if hasattr(delta, "tool_calls") and delta.tool_calls:
                        if t_thought_end is None and all_reasoning_chunks:
                            t_thought_end = time.time()
                        for tc in delta.tool_calls:
                            idx = getattr(tc, "index", 0)
                            if idx not in tool_calls_dict:
                                tool_calls_dict[idx] = {
                                    "id": getattr(tc, "id", "") or f"call_{idx}",
                                    "name": getattr(tc.function, "name", "") if getattr(tc, "function", None) else "",
                                    "arguments": "",
                                }
                            if getattr(tc, "id", None):
                                tool_calls_dict[idx]["id"] = tc.id
                            if getattr(tc, "function", None):
                                if getattr(tc.function, "name", None):
                                    tool_calls_dict[idx]["name"] = tc.function.name
                                if getattr(tc.function, "arguments", None):
                                    tool_calls_dict[idx]["arguments"] += tc.function.arguments
                    if hasattr(delta, "content") and delta.content:
                        if t_thought_end is None and all_reasoning_chunks:
                            t_thought_end = time.time()
                        content_chunks.append(delta.content)
                        if on_token_cb and not tool_calls_dict:
                            on_token_cb(delta.content)

            full_content = "".join(content_chunks).strip()

            if final_only and tool_calls_dict:
                if full_content:
                    self.messages.append({"role": "assistant", "content": full_content})
                    self._truncate_history_if_needed()
                    return build_reply(full_content, _step)
                raise RuntimeError(
                    "The model requested commands after the command limit; no further commands were executed."
                )

            if not tool_calls_dict:
                fallback_msg = (
                    "操作遇到对象匹配或语法异常，已触发熔断保护停止尝试。已完成部分视图渲染，请检查PyMOL命令行输出或对象名称。"
                    if consecutive_tool_failures >= 3
                    else "I couldn't produce a final summary. Please check the command log before assuming the request completed."
                )
                final_text = full_content or fallback_msg
                self.messages.append({"role": "assistant", "content": final_text})
                self._truncate_history_if_needed()
                return build_reply(final_text, _step)

            tool_calls_list = []
            for idx in sorted(tool_calls_dict.keys()):
                tc = tool_calls_dict[idx]
                tool_calls_list.append({
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": tc["arguments"],
                    },
                })

            self.messages.append({
                "role": "assistant",
                "content": full_content or None,
                "tool_calls": tool_calls_list,
            })

            # Execute tool calls
            for tc in tool_calls_list:
                if self._cancelled:
                    return build_reply("操作已由用户手动取消。", _step)
                call_id = tc["id"]
                fn_name = tc["function"]["name"]
                raw_args = tc["function"]["arguments"]
                try:
                    arguments = json.loads(raw_args or "{}")
                except Exception:
                    arguments = {}

                if fn_name == "execute_pymol_python":
                    code = arguments.get("code", "")
                    self.debug(f">>> {code}")
                    t_tool_0 = time.time()
                    execution = self.executor.execute(code)
                    t_tool_dur = max(0.01, time.time() - t_tool_0)
                    result = execution.as_json()
                    self.debug(result)

                    tool_record = {
                        "name": fn_name,
                        "code": code,
                        "ok": execution.ok,
                        "output": execution.output,
                        "error": execution.error,
                        "duration": t_tool_dur,
                    }
                    executed_tools.append(tool_record)
                    if on_tool_cb:
                        on_tool_cb(tool_record)

                    # Truncate verbose tool output to prevent context explosion (ACON observation compression)
                    raw_output = execution.output or ""
                    max_chars = config_max_tool_output()
                    if len(raw_output) > max_chars:
                        truncated_output = (
                            raw_output[:max_chars]
                            + f"\n... [output truncated from {len(raw_output)} chars to prevent token overflow]"
                        )
                        tool_content = json.dumps({"ok": execution.ok, "output": truncated_output, "error": execution.error})
                    else:
                        tool_content = result

                    if not execution.ok:
                        consecutive_tool_failures += 1
                        if consecutive_tool_failures >= 2:
                            tool_content += (
                                "\n\n[CIRCUIT BREAKER ALERT]: Consecutive executions failed. "
                                "STOP exploratory queries. In this round, generate ONLY a minimal, "
                                "fail-safe script: use 'model <name>' for selections, wrap optional distance/surface calls "
                                "in try-except, and provide your final summary."
                            )
                    else:
                        consecutive_tool_failures = 0

                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": tool_content,
                    })

                    confirmation = arguments.get("success_reply")
                    is_align_output = execution.ok and any(
                        line.strip().startswith(("ExecutiveAlign:", "ExecutiveSuper:", "ExecutiveRMS:", "ExecutiveRMSD:", "ExecutiveCealign:"))
                        for line in (execution.output or "").splitlines()
                    )
                    if (
                        _step == 0
                        and len(tool_calls_list) == 1
                        and execution.ok
                        and (not execution.output.strip() or is_align_output)
                        and not execution.error
                        and isinstance(confirmation, str)
                        and 0 < len(confirmation.strip()) <= 400
                        and can_confirm_directly(code)
                    ):
                        confirmation = confirmation.strip()
                        if is_align_output:
                            rms_lines = [
                                l.strip() for l in execution.output.splitlines()
                                if any(l.strip().startswith(p) for p in ("ExecutiveAlign:", "ExecutiveSuper:", "ExecutiveRMS:", "ExecutiveRMSD:", "ExecutiveCealign:"))
                            ]
                            if rms_lines:
                                confirmation = f"{confirmation} ({rms_lines[0]})"
                        self.messages.append({"role": "assistant", "content": confirmation})
                        self._truncate_history_if_needed()
                        return build_reply(confirmation, 1)
                elif fn_name == "align_structures":
                    mobile_obj = arguments.get("mobile_object") or ""
                    target_obj = arguments.get("target_object") or ""
                    mode = arguments.get("mode") or "auto"
                    lig_sel = arguments.get("ligand_selection") or "organic and not solvent"
                    focus_pock = bool(arguments.get("focus_pocket", True))
                    self.debug(f">>> align_structures(mobile={mobile_obj}, target={target_obj}, mode={mode}, ligand={lig_sel}, focus_pocket={focus_pock})")
                    t_tool_0 = time.time()
                    try:
                        from ..analysis import align_structures
                        cmd_api = getattr(self.executor, "safe_cmd", None)
                        aln_res = align_structures(
                            mobile_object=mobile_obj,
                            target_object=target_obj,
                            mode=mode,
                            ligand_selection=lig_sel,
                            focus_pocket=focus_pock,
                            cmd_override=cmd_api,
                        )
                        md_report = aln_res.to_markdown()
                        tool_ok = aln_res.success
                        tool_err = aln_res.warning or ""
                        tool_output = aln_res.to_summary_sentence()
                        full_content = md_report
                    except Exception as exc:
                        tool_output = ""
                        tool_ok = False
                        tool_err = str(exc)
                        full_content = f"对齐执行异常: {exc}"

                    t_tool_dur = max(0.01, time.time() - t_tool_0)
                    tool_record = {
                        "name": fn_name,
                        "code": f"align_structures('{mobile_obj}', '{target_obj}', mode='{mode}')",
                        "ok": tool_ok,
                        "output": tool_output,
                        "error": tool_err,
                        "duration": t_tool_dur,
                    }
                    executed_tools.append(tool_record)
                    if on_tool_cb:
                        on_tool_cb(tool_record)

                    tool_content = json.dumps({"ok": tool_ok, "output": tool_output, "error": tool_err})
                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": tool_content,
                    })

                    if full_content and len(tool_calls_list) == 1:
                        if on_token_cb:
                            for chunk in re.split(r"([，。、\n\s]+)", full_content):
                                if chunk:
                                    on_token_cb(chunk)
                        self.messages.append({"role": "assistant", "content": full_content})
                        self._truncate_history_if_needed()
                        return build_reply(full_content, _step + 1)
                elif fn_name == "analyze_protein_ligand_interactions":
                    ligand = arguments.get("ligand") or "organic"
                    receptor = arguments.get("receptor") or "polymer.protein"
                    cutoff = float(arguments.get("cutoff") or 4.5)
                    visualize = arguments.get("visualize", True)
                    self.debug(f">>> analyze_protein_ligand_interactions(ligand={ligand}, receptor={receptor}, cutoff={cutoff})")
                    t_tool_0 = time.time()
                    try:
                        from ..analysis import analyze_interactions
                        cmd_api = getattr(self.executor, "safe_cmd", None)
                        report = analyze_interactions(
                            ligand_selection=ligand,
                            receptor_selection=receptor,
                            cutoff=cutoff,
                            cmd_api=cmd_api,
                            visualize=visualize,
                        )
                        md_report = report.to_markdown()
                        tool_ok = not bool(report.diagnostic_message)
                        tool_err = report.diagnostic_message
                        tool_output = md_report
                    except Exception as exc:
                        tool_output = ""
                        tool_ok = False
                        tool_err = str(exc)

                    t_tool_dur = max(0.01, time.time() - t_tool_0)
                    tool_record = {
                        "name": fn_name,
                        "code": f"analyze_interactions('{ligand}', '{receptor}', cutoff={cutoff})",
                        "ok": tool_ok,
                        "output": tool_output,
                        "error": tool_err,
                        "duration": t_tool_dur,
                    }
                    executed_tools.append(tool_record)
                    if on_tool_cb:
                        on_tool_cb(tool_record)

                    tool_content = json.dumps({"ok": tool_ok, "output": tool_output, "error": tool_err})
                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": tool_content,
                    })

                    # If single tool call, stream markdown table or diagnostic directly to user!
                    if tool_output and len(tool_calls_list) == 1:
                        if on_token_cb:
                            for chunk in re.split(r"([，。、\n\s]+)", tool_output):
                                if chunk:
                                    on_token_cb(chunk)
                        self.messages.append({"role": "assistant", "content": tool_output})
                        self._truncate_history_if_needed()
                        return build_reply(tool_output, _step + 1)
                elif fn_name == "load_local_structures":
                    path = arguments.get("path") or ""
                    pattern = arguments.get("pattern") or "*"
                    max_files = int(arguments.get("max_files") or 20)
                    clean_scene = bool(arguments.get("clean_scene", False))
                    self.debug(f">>> load_local_structures(path={path}, pattern={pattern}, max_files={max_files})")
                    t_tool_0 = time.time()
                    try:
                        from ..analysis import load_structures_from_path
                        result = load_structures_from_path(
                            path=path,
                            pattern=pattern,
                            max_files=max_files,
                            clean_scene=clean_scene,
                            auto_orient=True,
                        )
                        md_report = result.to_markdown()
                        tool_ok = result.success and result.total_loaded > 0
                        tool_err = result.diagnostic_message if not tool_ok else ""
                        tool_output = md_report
                        loaded_objs = result.loaded_objects
                    except Exception as exc:
                        tool_output = ""
                        tool_ok = False
                        tool_err = str(exc)
                        loaded_objs = []

                    t_tool_dur = max(0.01, time.time() - t_tool_0)
                    tool_record = {
                        "name": fn_name,
                        "code": f"load_structures_from_path('{path}', pattern='{pattern}')",
                        "ok": tool_ok,
                        "output": tool_output,
                        "error": tool_err,
                        "duration": t_tool_dur,
                    }
                    executed_tools.append(tool_record)
                    if on_tool_cb:
                        on_tool_cb(tool_record)

                    tool_content = json.dumps({
                        "ok": tool_ok,
                        "output": tool_output,
                        "error": tool_err,
                        "loaded_objects": loaded_objs,
                    })
                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": tool_content,
                    })
                elif fn_name == "compare_conformations":
                    mob = arguments.get("mobile_object") or ""
                    tgt = arguments.get("target_object") or ""
                    pock = arguments.get("pocket_selection") or "organic"
                    cut = float(arguments.get("cutoff") or 5.0)
                    heatmap = bool(arguments.get("apply_heatmap", True))
                    self.debug(f">>> compare_conformations({mob}, {tgt}, pocket={pock}, cutoff={cut})")
                    t_tool_0 = time.time()
                    try:
                        from ..analysis import compare_conformations
                        cmd_api = getattr(self.executor, "safe_cmd", None)
                        comp_res = compare_conformations(
                            mobile_object=mob,
                            target_object=tgt,
                            pocket_selection=pock,
                            cutoff=cut,
                            apply_heatmap=heatmap,
                            cmd_override=cmd_api,
                        )
                        md_report = comp_res.to_markdown()
                        tool_ok = not bool(comp_res.warning)
                        tool_err = comp_res.warning or ""
                        tool_output = md_report
                    except Exception as exc:
                        tool_output = ""
                        tool_ok = False
                        tool_err = str(exc)

                    t_tool_dur = max(0.01, time.time() - t_tool_0)
                    tool_record = {
                        "name": fn_name,
                        "code": f"compare_conformations('{mob}', '{tgt}', pocket='{pock}')",
                        "ok": tool_ok,
                        "output": tool_output,
                        "error": tool_err,
                        "duration": t_tool_dur,
                    }
                    executed_tools.append(tool_record)
                    if on_tool_cb:
                        on_tool_cb(tool_record)

                    tool_content = json.dumps({"ok": tool_ok, "output": tool_output, "error": tool_err})
                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": tool_content,
                    })
                    if tool_output and len(tool_calls_list) == 1:
                        if on_token_cb:
                            for chunk in re.split(r"([，。、\n\s]+)", tool_output):
                                if chunk:
                                    on_token_cb(chunk)
                        self.messages.append({"role": "assistant", "content": tool_output})
                        self._truncate_history_if_needed()
                        return build_reply(tool_output, _step + 1)
                elif fn_name == "apply_publication_preset":
                    style = arguments.get("style") or "nature"
                    sel = arguments.get("selection") or "all"
                    self.debug(f">>> apply_publication_preset(style={style}, selection={sel})")
                    t_tool_0 = time.time()
                    try:
                        from ..analysis import apply_publication_preset
                        cmd_api = getattr(self.executor, "safe_cmd", None)
                        pres_res = apply_publication_preset(style=style, selection=sel, cmd_override=cmd_api)
                        md_report = pres_res.to_markdown()
                        tool_ok = pres_res.success
                        tool_err = pres_res.details or ""
                        tool_output = md_report
                    except Exception as exc:
                        tool_output = ""
                        tool_ok = False
                        tool_err = str(exc)

                    t_tool_dur = max(0.01, time.time() - t_tool_0)
                    tool_record = {
                        "name": fn_name,
                        "code": f"apply_publication_preset('{style}', selection='{sel}')",
                        "ok": tool_ok,
                        "output": tool_output,
                        "error": tool_err,
                        "duration": t_tool_dur,
                    }
                    executed_tools.append(tool_record)
                    if on_tool_cb:
                        on_tool_cb(tool_record)

                    tool_content = json.dumps({"ok": tool_ok, "output": tool_output, "error": tool_err})
                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": tool_content,
                    })
                    if tool_output and len(tool_calls_list) == 1:
                        if on_token_cb:
                            for chunk in re.split(r"([，。、\n\s]+)", tool_output):
                                if chunk:
                                    on_token_cb(chunk)
                        self.messages.append({"role": "assistant", "content": tool_output})
                        self._truncate_history_if_needed()
                        return build_reply(tool_output, _step + 1)
                elif fn_name == "visualize_plddt":
                    sel = arguments.get("selection") or "all"
                    hide_dis = bool(arguments.get("hide_disordered", False))
                    min_p = float(arguments.get("min_plddt") or 50.0)
                    self.debug(f">>> visualize_plddt(selection={sel}, hide_disordered={hide_dis})")
                    t_tool_0 = time.time()
                    try:
                        from ..analysis import visualize_plddt
                        cmd_api = getattr(self.executor, "safe_cmd", None)
                        plddt_res = visualize_plddt(
                            selection=sel,
                            hide_disordered=hide_dis,
                            min_plddt=min_p,
                            cmd_override=cmd_api,
                        )
                        md_report = plddt_res.to_markdown()
                        tool_ok = plddt_res.success
                        tool_err = plddt_res.warning or ""
                        tool_output = md_report
                    except Exception as exc:
                        tool_output = ""
                        tool_ok = False
                        tool_err = str(exc)

                    t_tool_dur = max(0.01, time.time() - t_tool_0)
                    tool_record = {
                        "name": fn_name,
                        "code": f"visualize_plddt('{sel}', hide_disordered={hide_dis})",
                        "ok": tool_ok,
                        "output": tool_output,
                        "error": tool_err,
                        "duration": t_tool_dur,
                    }
                    executed_tools.append(tool_record)
                    if on_tool_cb:
                        on_tool_cb(tool_record)

                    tool_content = json.dumps({"ok": tool_ok, "output": tool_output, "error": tool_err})
                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": tool_content,
                    })
                    if tool_output and len(tool_calls_list) == 1:
                        if on_token_cb:
                            for chunk in re.split(r"([，。、\n\s]+)", tool_output):
                                if chunk:
                                    on_token_cb(chunk)
                        self.messages.append({"role": "assistant", "content": tool_output})
                        self._truncate_history_if_needed()
                        return build_reply(tool_output, _step + 1)
                else:
                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": json.dumps({"ok": False, "error": f"Tool '{fn_name}' unavailable."}),
                    })

        return build_reply("Command budget completed.", MAX_TOOL_ROUNDS)
