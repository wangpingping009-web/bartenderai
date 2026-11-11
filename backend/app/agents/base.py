# -*- coding: utf-8 -*-
"""六 Agent 角色的公共基础设施。

核心概念：reAct 循环（本项目"真智能"的基座）
==========================================
reAct = Reason + Act。每个 Agent 不是"调用一次 LLM 就结束"，而是循环：
  1. Reason:  LLM 观察当前状态，思考下一步该做什么
  2. Act:     调用一个工具（检索/查库存/算酒精度...）
  3. Observe: 把工具结果写回状态
  4. 回到 1，直到 LLM 判断"信息足够，可以给出结论"

与"预输入 Agent"（写死 if-else 流程 + 固定 prompt）的本质区别：
  工具调几次、调哪个、何时停，都由 LLM 实时决策，代码只提供工具和能力边界。

本文件定义:
- `ReactTool`: 工具描述（LLM 看到的说明）
- `AgentContext`: 一次 Agent 调用的输入输出载体
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ReactTool:
    """一个可供 LLM 调用的工具。name+description 会进入 LLM 上下文。"""
    name: str                 # 工具名（LLM 用这个名字调用）
    description: str          # 工具说明（必须清晰、可触发、边界明确）
    func: callable            # 实际执行的函数

    def call(self, **kwargs) -> str:
        """执行工具并返回字符串结果（喂回 LLM 上下文）。"""
        try:
            result = self.func(**kwargs)
            return result if isinstance(result, str) else str(result)
        except Exception as e:
            return f"[工具 {self.name} 执行失败: {e}]"


@dataclass
class AgentContext:
    """一次 Agent 调用的上下文。所有中间结果都放这里，供后续 Agent 使用。"""
    user_query: str = ""                    # 用户本轮完整提问
    history: list[dict] = field(default_factory=list)   # 会话历史
    retrieved: list = field(default_factory=list)       # 检索结果（RetrievedDoc 列表）
    references: list = field(default_factory=list)      # 引用来源
    events: list = field(default_factory=list)          # SSE 事件流
    final_answer: str = ""                  # Agent 给出的结论
    extra: dict = field(default_factory=dict)           # 其他中间产物（库存/风味/画像...）

    def add_event(self, evt: str) -> None:
        """往事件流追加一条（供 SSE 实时回传前端）。"""
        self.events.append(evt)


def build_debate_block(debate: dict) -> str:
    """构造"圆桌讨论"上下文，注入 Agent 的 system prompt。

    debate 结构（graph.debate_node 传给各 Agent 的讨论模式）:
    - prior_output:        该 Agent 上一轮的结论（可修订）
    - other_speeches:      其他 Agent 的发言记录 [{speaker, content}, ...]
    - revise_instructions: 审校给出的修正指令（必须逐条落实）

    目的：让 Agent 能看到"别人怎么说自己"，先回应质疑再给修订版结论，
    这是"自由对话"区别于单向流水线的关键。
    """
    lines = ["\n\n【圆桌讨论 · 请先回应再修订】"]
    instructions = debate.get("revise_instructions") or []
    if instructions:
        lines.append("审校修正要求（必须逐条落实，不能无视）：")
        lines += [f"- {i}" for i in instructions]
    others = debate.get("other_speeches") or []
    if others:
        lines.append("其他 Agent 的发言（先回应质疑：同意/反驳并给理由）：")
        # 其他 Agent 发言视为半可信输入：净化 + 注入检测，命中则不把原文喂给 LLM
        # （Agent 间内容隔离，REQUIREMENTS 9——防某 Agent 输出带指令性文本污染他人）
        from app.core.security import detect_injection, sanitize_input
        for m in others:
            content = sanitize_input(m.get("content") or "")
            if detect_injection(content):
                content = "（该发言疑似包含指令性内容，正文已忽略）"
            lines.append(f"- [{m['speaker']}] {content[:400]}")
    prior = debate.get("prior_output") or ""
    if prior:
        lines.append(f"你上一轮的结论（可修订）：{prior[:400]}")
    lines.append("回应要求：1) 先针对质疑/修正要求表态；2) 再给出修订后的结论；"
                 "3) 结论仍受本 Agent 铁律约束，不得编造。")
    return "\n".join(lines)
