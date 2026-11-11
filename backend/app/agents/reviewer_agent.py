# -*- coding: utf-8 -*-
"""审校整合 Agent：一致性检查 + 引用真实性校验 + 反思自纠（回炉修正）。

职责（对应六 Agent 里的"审校整合"，也是"反思自纠"核心原则的落地）:
1. **一致性检查**：上游各 Agent 的结论是否互相矛盾
   （如库存推荐说"缺朗姆"，风味分析却在讨论朗姆配方）
2. **引用真实性校验**（防幻觉）：答案里提到的配方/知识点，
   是否真的在检索结果的引用里？防止 LLM 编造来源
3. **反思自纠**：发现问题 → 返回给上游 Agent 修正 → 重新提交。
   这是"单向校验"的升级：不是只报错，而是驱动修正闭环。

本模块提供两个层：
- `check_and_revise()`: 单次审校（发现问题则建议修正）
- 反思自纠循环在 LangGraph 状态图（M3.4）里编排：
  审校发现 issue → 状态打回 → 相关 Agent 重跑 → 再审校（限轮数）
"""
from __future__ import annotations

import json
from enum import Enum

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from app.core.llm import get_llm
from app.core.registry import get_prompt


class ReviewVerdict(str, Enum):
    PASS = "pass"            # 通过
    REVISE = "revise"        # 需要修正（回炉）
    CLARIFY = "clarify"      # 需要向用户反问


class ReviewResult(BaseModel):
    """一次审校的结论。"""
    verdict: ReviewVerdict = Field(description="通过/需修正/需反问")
    issues: list[str] = Field(default_factory=list, description="发现的问题列表")
    revise_instructions: list[str] = Field(default_factory=list,
                                           description="给上游 Agent 的修正指令（具体到哪部分怎么改）")
    revise_agents: list[str] = Field(default_factory=list,
                                     description="需要回炉重跑的 Agent 名单（只点被点名者，不要连累无关 Agent 重跑）")
    final_answer: str = Field(default="", description="整合后的最终答案（pass 时有效）")
    review_mode: str = Field(default="unavailable", description="model 或 unavailable")


# 系统提示词来自 Prompt 注册中心（M6）
_SYSTEM_PROMPT = get_prompt("reviewer")["system"]

_parser = PydanticOutputParser(pydantic_object=ReviewResult)

_PROMPT = ChatPromptTemplate.from_messages([
    ("system", _SYSTEM_PROMPT),
    ("human", """用户问题：{query}

各 Agent 结论：
{agent_outputs}

引用来源（必须是答案事实的依据）：
{references}

总控共享约束交接单（所有结论都必须满足）：
{constraints}

{format_instructions}"""),
])


def check_and_revise(query: str, agent_outputs: list[tuple[str, str]],
                     references: list[str], retries: int = 1,
                     constraints: dict | None = None) -> ReviewResult:
    """审校各 Agent 的输出，返回结论（pass 或修正指令）。

    Args:
        query:         用户问题
        agent_outputs: [(agent名, 该 Agent 的结论), ...]
        references:    检索到的引用来源列表
        retries:       LLM 调用失败时的重试次数（默认 1 次）

    失败兜底：重试仍失败时，不再"静默拼接"——返回带明确标注的整合答案
    （issues 里说明审校未完成），让用户/前端知道这次回答未经一致性校验。
    """
    outputs_text = "\n\n".join(f"[{name}]\n{text}" for name, text in agent_outputs)
    refs_text = "\n".join(references) if references else "(无引用)"
    from app.services.mixology_constraints import constraint_prompt_block
    constraints_text = constraint_prompt_block(constraints)

    last_err: Exception | None = None
    for _ in range(retries + 1):
        try:
            llm = get_llm(temperature=0, max_tokens=1500)
            chain = _PROMPT | llm | _parser
            result = chain.invoke({
                "query": query,
                "agent_outputs": outputs_text,
                "references": refs_text,
                "constraints": constraints_text,
                "format_instructions": _parser.get_format_instructions(),
            })
            result.review_mode = "model"
            return result
        except Exception as e:
            last_err = e
            continue

    # 重试仍失败：明确标注"未经审校"，而非静默拼接
    conclusions = [text for name, text in agent_outputs if name != "retriever"]
    merged = "\n\n".join(conclusions or [text for _, text in agent_outputs])
    return ReviewResult(
        verdict=ReviewVerdict.PASS,
        issues=[f"审校 LLM 调用失败（{type(last_err).__name__ if last_err else 'unknown'}），"
                "答案未经一致性/引用校验"],
        final_answer=f"{merged}\n\n（本次模型复核暂未完成，建议仅依据已匹配的真实配方。）",
        review_mode="unavailable",
    )


# 流式最终答案生成的系统提示词（v2.1：答案边生成边推给前端，ChatGPT 式体验）
_STREAM_SYSTEM = """你是调酒助手 BartenderAI 的首席调酒师 Leo。你不是客服，也不是配方说明书；你像一个认真听人说话、懂酒、愿意陪用户把选择想明白的朋友。

基于下方【各 Agent 分析结论】【审校意见】【引用来源】，直接给用户一个连贯、有人味的最终回答。
要求：
1. 直接回答用户，绝不提"Agent/检索/审校/知识库"等内部词（可以说"我查了下经典做法"这类自然表述）
2. 开头先回应本轮话里最具体的一点，而不是套用“按你的偏好”“根据你的需求”“当然可以”等万能开场。用户提到心情时，用一句克制、真诚的话接住即可，不扮演心理咨询师
3. 像真实对话一样有取舍：明确说“我会选哪杯、为什么是它、哪里可能不完全符合”，必要时给一个调整建议。不要把候选数据逐条念给用户
4. 不要复述用户整句话，不要引用内部拼接出的旧需求；只有用户明确说“还有吗/换一个/刚才那杯”时，才自然承接上一轮
5. 回答节奏要有变化：两三句自然短段落为主，材料很多时才分点。禁止“推荐1/推荐2”式清单、模板化小标题、客服腔和连续感叹号，不堆 emoji
6. 如果配方卡会在下方出现，正文负责解释选择和关键提醒，不要再机械抄一遍卡片里的全部材料、度数和步骤；用户明确问做法时才概括关键操作
7. 用户是在共同创作时，要像搭档一样确认已经确定的取向，再问一个最有价值的问题；不能突然塞给用户一杯现成经典配方
8. 【铁律】只用下方结论与引用里的事实；没有的具体用量/度数不编数字，用定性描述
9. 当前用户消息是最高优先级。最近对话只用于理解真正的指代，不得用旧话题覆盖本轮新表达
10. 结尾只在确实有助于继续交流时问一个具体、容易回答的问题；不要每次都用“还需要什么吗”收尾
11. 篇幅适中：讲清楚即可，不重复、不说空话"""


def stream_final_answer(query: str, agent_outputs: list[tuple[str, str]],
                        references: list[str], issues: list[str],
                        writer, temperature: float = 0.3,
                        constraints: dict | None = None,
                        history: list[dict] | None = None,
                        resolved_query: str = "") -> str:
    """流式生成最终答案：逐 chunk 回调 writer({"kind": "partial", "text": ...})。

    writer 是 LangGraph 的 stream writer（SSE 场景下把 partial 事件实时推给前端，
    invoke 场景下是 no-op）。返回完整答案文本（前端同时用 partial 流与最终结果）。

    Args:
        query:         用户问题
        agent_outputs: [(agent名, 结论), ...]
        references:    引用来源
        issues:        审校意见（空 = 通过）
        writer:        callable(dict)，LangGraph 节点内 writer
    """
    outputs_text = "\n\n".join(f"[{name}]\n{text}" for name, text in agent_outputs)
    refs_text = "\n".join(references) if references else "(无引用)"
    issues_text = "\n".join(f"- {i}" for i in issues) if issues else "（审校通过，无问题）"
    from app.services.mixology_constraints import constraint_prompt_block
    constraints_text = constraint_prompt_block(constraints)
    history_rows = []
    for item in list(history or [])[-4:]:
        role = "用户" if item.get("role") == "user" else "调酒师"
        history_rows.append(f"{role}：{str(item.get('content') or '')[:500]}")
    history_text = "\n".join(history_rows) or "（无）"
    messages = [
        ("system", _STREAM_SYSTEM),
        ("human", f"【本轮用户原话，回答对象】\n{query}\n\n"
                  f"【最近对话，仅用于解析明确指代】\n{history_text}\n\n"
                  f"【内部解析后的任务，不得原样复述】\n{resolved_query or query}\n\n"
                  f"【各 Agent 分析结论】\n{outputs_text}\n\n"
                  f"【共享约束交接单】\n{constraints_text}\n\n"
                  f"【审校意见】\n{issues_text}\n\n【引用来源】\n{refs_text}"),
    ]
    llm = get_llm(temperature=temperature, max_tokens=1200)
    full: list[str] = []
    try:
        for chunk in llm.stream(messages):
            text = chunk.content or ""
            if text:
                full.append(text)
                try:
                    writer({"kind": "partial", "text": text})
                except Exception:
                    pass  # 非 SSE 上下文 writer 可能抛错，忽略
    except Exception:
        return ""
    return "".join(full)
