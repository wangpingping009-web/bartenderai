# -*- coding: utf-8 -*-
from app.rag.hybrid import HybridRetriever
from app.services.deterministic_chat import (
    build_deterministic_answer,
    recommend_many_for_query,
    recommend_for_query,
    requested_recommendation_count,
    resolve_recipe_context,
)
from app.services.recipe_catalog import all_recipes, get_recipe, search_recipes


def test_sweet_not_sour_uses_hard_negative_filter():
    recipe = recommend_for_query("我喜欢甜的，不酸")
    assert recipe is not None
    ingredients = " ".join(item["name"].lower() for item in recipe["ingredients"])
    assert not any(marker in ingredients for marker in ("lemon", "lime", "sweet and sour", "sour mix"))
    assert recipe["flavor"]["sweet"] >= 5


def test_recipe_fallback_corrects_bad_lexical_candidate_and_has_full_steps():
    texas = get_recipe("15178")
    answer = build_deterministic_answer(
        "甜的，不酸", [HybridRetriever._cocktail_doc(texas, 1.0)],
    )
    assert answer.recipe is not None
    assert answer.recipe["name"] != "Texas Rattlesnake"
    assert len(answer.recipe["steps"]) >= 4
    assert "酸甜汁" in answer.answer
    assert "Connection error" not in answer.answer


def test_exact_recipe_keeps_source_ingredients():
    texas = get_recipe("15178")
    answer = build_deterministic_answer(
        "Texas Rattlesnake 怎么调？", [HybridRetriever._cocktail_doc(texas, 1.0)],
    )
    assert answer.recipe["name"] == "Texas Rattlesnake"
    assert [item["name"] for item in answer.recipe["ingredients"]][-1] == "酸甜汁"


def test_elliptical_followup_inherits_preferences_and_excludes_previous_recipe():
    first = recommend_for_query("甜的，不酸")
    history = [
        {"role": "user", "content": "甜的，不酸"},
        {"role": "assistant", "content": "这里是上一轮推荐",
         "metadata": {"recipe": {"id": first["id"]}}},
    ]

    context = resolve_recipe_context("还有吗", history)
    answer = build_deterministic_answer("还有吗", [], history)

    assert context.followup is True
    assert "甜的，不酸" in context.query
    assert str(first["id"]) in context.exclude_recipe_ids
    assert answer.recipe is not None
    assert str(answer.recipe["id"]) != str(first["id"])
    assert "我记得刚才的取向" in answer.answer
    assert "暂时没有" not in answer.answer
    ingredients = " ".join(item["name_en"].lower() for item in answer.recipe["ingredients"])
    assert not any(marker in ingredients for marker in ("lemon", "lime", "sweet and sour", "sour mix"))


def test_followup_router_does_not_need_model_connection():
    from app.agents.orchestrator_agent import Intent, plan_query

    history = [
        {"role": "user", "content": "甜的，不酸"},
        {"role": "assistant", "content": "推荐白俄罗斯",
         "metadata": {"recipe": {"id": "12528"}}},
    ]
    plan = plan_query("还有吗", history)

    assert plan.intent == Intent.RECOMMEND
    assert plan.need_retrieve is True
    assert plan.need_clarify is False


def test_multi_recommendation_inherits_preferences_and_returns_exact_count():
    first = recommend_for_query("甜的，不酸")
    history = [
        {"role": "user", "content": "甜的，不酸"},
        {"role": "assistant", "content": "上一轮推荐",
         "metadata": {"recipe": {"id": first["id"]}}},
    ]

    context = resolve_recipe_context("给我多推荐五个", history)
    answer = build_deterministic_answer("给我多推荐五个", [], history)

    assert requested_recommendation_count("给我多推荐五个") == 5
    assert context.followup is True
    assert context.recommendation_count == 5
    assert context.inherited_preference == "甜的，不酸"
    assert len(answer.recipes) == 5
    assert answer.recipe is None
    assert len({item["id"] for item in answer.recipes}) == 5
    assert str(first["id"]) not in {str(item["id"]) for item in answer.recipes}
    assert len(answer.docs) == 5
    assert len(answer.parts) == 2
    assert "第二杯怎么调" in answer.answer
    for recipe in answer.recipes:
        ingredients = " ".join(item["name_en"].lower() for item in recipe["ingredients"])
        assert not any(marker in ingredients for marker in ("lemon", "lime", "sweet and sour", "sour mix"))


def test_complete_mood_request_starts_a_new_task_instead_of_inheriting_old_recipe():
    previous = recommend_for_query("甜的，不酸")
    history = [
        {"role": "user", "content": "甜的，不酸"},
        {"role": "assistant", "content": "上一轮推荐", "metadata": {
            "recipe": {"id": previous["id"]},
        }},
    ]
    query = "今天心情不好，想喝点清爽的、刺激一点的，不要太甜"

    context = resolve_recipe_context(query, history)
    answer = build_deterministic_answer(query, [], history)

    assert context.followup is False
    assert context.query == query
    assert context.inherited_preference == ""
    assert "继续按你刚才" not in answer.answer
    assert answer.recipe is not None
    assert answer.recipe["flavor"]["sweet"] <= 4


def test_plain_multi_count_is_new_but_more_count_is_a_followup():
    previous = recommend_for_query("甜的，不酸")
    history = [
        {"role": "user", "content": "甜的，不酸"},
        {"role": "assistant", "content": "上一轮推荐", "metadata": {
            "recipe": {"id": previous["id"]},
        }},
    ]

    assert resolve_recipe_context("给我推荐五个清爽低甜的", history).followup is False
    assert resolve_recipe_context("再多推荐五个", history).followup is True


def test_mood_and_flavor_request_routes_to_grounded_flavor_collaboration():
    from app.agents.orchestrator_agent import Intent, plan_query
    from app.graph.graph import _prefetch_retrieve

    previous = recommend_for_query("甜的，不酸")
    history = [
        {"role": "user", "content": "甜的，不酸"},
        {"role": "assistant", "content": "上一轮推荐", "metadata": {
            "recipe": {"id": previous["id"]},
        }},
    ]
    query = "今天心情不好，想喝点清爽的、刺激一点的，不要太甜"

    plan = plan_query(query, history)
    prefetch = _prefetch_retrieve(query, history)

    assert plan.intent == Intent.RECOMMEND
    assert plan.need_retrieve is True
    assert plan.need_flavor is True
    assert prefetch["contextual_followup"] is False
    assert prefetch["effective_query"] == query
    assert len(prefetch["docs"]) == 5


def test_ordinal_followup_resolves_recipe_from_previous_multi_result():
    recipes = recommend_many_for_query("甜的，不酸", 5)
    cards = [{"id": item["id"], "name": item["name"], "name_cn": item["name_cn"]}
             for item in recipes]
    history = [
        {"role": "user", "content": "给我推荐五个甜而不酸的"},
        {"role": "assistant", "content": "五款推荐", "metadata": {"recipes": cards}},
    ]

    context = resolve_recipe_context("第二个怎么调", history)
    answer = build_deterministic_answer("第二个怎么调", [], history)

    assert context.selected_recipe_id == str(recipes[1]["id"])
    assert answer.recipe["id"] == recipes[1]["id"]
    assert len(answer.recipe["steps"]) >= 4


def test_ordinal_feedback_recommends_a_new_recipe_instead_of_opening_old_one():
    recipes = recommend_many_for_query("推荐五个甜但不要太甜、酸但不要太酸、有酒味的金酒", 5)
    cards = [{"id": item["id"], "name": item["name"], "name_cn": item["name_cn"]}
             for item in recipes]
    history = [
        {"role": "user", "content": "推荐五个甜但不要太甜、酸但不要太酸、有酒味的金酒"},
        {"role": "assistant", "content": "五款推荐", "metadata": {"recipes": cards}},
    ]

    context = resolve_recipe_context("第二个还是太酸，换一个甜一点的", history)
    answer = build_deterministic_answer("第二个还是太酸，换一个甜一点的", [], history)

    assert context.followup is True
    assert context.selected_recipe_id is None
    assert str(recipes[1]["id"]) in context.exclude_recipe_ids
    assert "太酸" in context.query
    assert answer.recipe is not None
    assert str(answer.recipe["id"]) not in {str(item["id"]) for item in recipes}
    assert answer.recipe["flavor"]["sour"] <= 4


def test_rejecting_an_ordinal_is_feedback_not_a_recipe_open_request():
    recipes = recommend_many_for_query("推荐五个甜而不酸的", 5)
    history = [
        {"role": "user", "content": "推荐五个甜而不酸的"},
        {"role": "assistant", "content": "五款推荐", "metadata": {
            "recipes": [{"id": item["id"], "name": item["name"],
                         "name_cn": item["name_cn"]} for item in recipes],
        }},
    ]

    context = resolve_recipe_context("不要第二个，换个清爽一点的", history)

    assert context.followup is True
    assert context.selected_recipe_id is None
    assert str(recipes[1]["id"]) in context.exclude_recipe_ids
    assert "清爽一点" in context.query


def test_explicit_chat_feedback_updates_profile_without_model():
    from app.services.profile import deterministic_profile_delta

    delta = deterministic_profile_delta("这个太甜，也有点太酸，换个清爽一点的，不要蛋清")

    assert delta["sweetness"] == 3
    assert delta["sourness"] == 3
    assert delta["style_notes"] == ["清爽"]
    assert delta["disliked_ingredients"] == ["egg white"]
    assert delta["feedback"]


def test_degree_phrases_apply_to_inventory_scoring():
    recipes = recommend_many_for_query("金酒，甜但不要太甜，酸但不要太酸，有酒味", 5)

    assert recipes
    assert all(3 <= item["flavor"]["sweet"] <= 5 for item in recipes)
    assert all(2 <= item["flavor"]["sour"] <= 4 for item in recipes)
    assert all(item["flavor"]["strong"] >= 4 for item in recipes)


def test_degree_preferences_and_base_spirit_are_hard_constraints():
    recipes = recommend_many_for_query(
        "想喝甜但不是很甜、酸但不是很酸、有酒味的金酒", 5,
    )

    assert recipes
    for recipe in recipes:
        ingredients = {item["canonical"] for item in recipe["ingredients"]}
        assert "gin" in ingredients
        assert 3 <= recipe["flavor"]["sweet"] <= 5
        assert 2 <= recipe["flavor"]["sour"] <= 4
        assert recipe["flavor"]["strong"] >= 4


def test_opaque_catalog_codes_have_descriptive_display_names():
    assert get_recipe("17222")["name_cn"] == "柑橘石榴金酒"
    assert get_recipe("13501")["name_cn"] == "杏仁奶油干邑"
    assert get_recipe("14610")["name_cn"] == "双桶烈焰"
    assert get_recipe("11014")["name_cn"] == "亚历山大"


def test_single_fact_why_question_uses_one_retrieval_path():
    from app.agents.orchestrator_agent import Intent, plan_query

    plan = plan_query("为什么含蛋清的鸡尾酒通常需要干摇？")

    assert plan.intent == Intent.QUERY
    assert plan.need_retrieve is True
    assert plan.need_teach is False
    assert plan.need_stock is False
    assert plan.need_flavor is False


def test_collaborative_creation_goal_outranks_recipe_recommendation(monkeypatch):
    from app.agents.orchestrator_agent import Intent, plan_query
    from app.services.creative_dialogue import CreativeDialogueDecision

    captured = {}

    def fake_dialogue(query, history, stock):
        captured["query"] = query
        return CreativeDialogueDecision(
            active=True,
            ready=False,
            preferences="中低甜；中低酸；保留酒感；使用金酒",
            base_spirits=["gin"],
            confirmed=["中低甜", "中低酸", "保留酒感", "使用金酒"],
            missing=["饮用形态"],
            response="我理解了这些要求。你想做成长饮还是短饮？",
        )

    monkeypatch.setattr("app.services.creative_dialogue.plan_creative_dialogue", fake_dialogue)
    query = "想喝点甜又不是很甜，酸又不是很酸，自己创作，有酒味，现在有金酒，你带我一起创作，先确定需求"
    plan = plan_query(query)

    assert captured["query"] == query
    assert plan.intent == Intent.CREATE
    assert plan.need_clarify is True
    assert plan.need_retrieve is False
    assert "白俄罗斯" not in plan.clarify_question
    assert plan.creative_base_spirits == ["gin"]


def test_llm_balance_error_is_non_retryable_and_observable():
    from app.core.llm import (
        is_non_retryable_llm_error, llm_error_reason,
        llm_runtime_health, record_llm_failure,
    )

    error = RuntimeError("Error code: 402 - Insufficient Balance")
    record_llm_failure(error)

    assert llm_error_reason(error) == "insufficient_balance"
    assert is_non_retryable_llm_error(error) is True
    assert llm_runtime_health()["available"] is False
    from app.core.llm import record_llm_success
    record_llm_success()


def test_creation_fallback_preserves_explicit_degree_words():
    from app.services.creative_dialogue import _fallback

    decision = _fallback("一起创作一杯中低甜、中低酸、有酒感的金酒", [], [],
                         reason="insufficient_balance")

    assert "中低甜" in decision.confirmed[0]
    assert any("中低酸" in item for item in decision.confirmed)
    assert decision.capability == "local_parser"
    assert "智能模型额度不足" in decision.response
    assert "没有把固定规则包装成完整的智能理解" in decision.response
    assert "白俄罗斯" not in decision.response


def test_creation_fallback_understands_original_request_and_asks_for_materials():
    from app.services.creative_dialogue import _fallback

    query = ("想喝点甜有不是很甜，酸有不是很酸，自己创作的酒，有酒味，"
             "现在有金酒等，你带我一起创作，确定我的需求")
    decision = _fallback(query, [], [], reason="insufficient_balance")

    assert decision.ready is False
    assert decision.base_spirits == ["gin"]
    assert decision.brief["sweetness"].startswith("中低甜")
    assert decision.brief["acidity"].startswith("中低酸")
    assert decision.brief["alcohol"] == "保留清晰酒感"
    assert decision.missing == ["可用与禁用材料"]
    assert "除基酒外还有哪些材料" in decision.response
    assert "智能模型" in decision.response
    assert "白俄罗斯" not in decision.response


def test_original_creation_request_streams_constraints_and_never_recommends_classic(monkeypatch):
    import json

    from app.services.streaming import stream_agent_response

    monkeypatch.setattr(
        "app.services.creative_dialogue.iter_configured_llms",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    query = (
        "想喝点甜有不是很甜，酸有不是很酸，自己创作的酒，有酒味，"
        "现在有金酒等，你带我一起创作，确定我的需求"
    )
    events = []
    for chunk in stream_agent_response(query, history=[]):
        if chunk.startswith("data: "):
            events.append(json.loads(chunk[6:]))

    partials = [event["text"] for event in events if event.get("type") == "partial"]
    done = next(event for event in events if event.get("type") == "done")

    assert len(partials) >= 2
    assert "中低甜" in done["answer"]
    assert "中低酸" in done["answer"]
    assert "金酒" in done["answer"]
    assert "除基酒外还有哪些材料" in done["answer"]
    assert "白俄罗斯" not in done["answer"]
    assert done["recipe"] is None
    assert done["capability_mode"] == "local_parser"


def test_creation_brief_persists_and_does_not_treat_forbidden_material_as_available():
    from app.services.creative_dialogue import _fallback

    first = _fallback("一起创作中低甜、中低酸、有酒感的金酒，手边有金酒等", [], [],
                      reason="insufficient_balance")
    history = [
        {"role": "user", "content": "一起创作中低甜、中低酸、有酒感的金酒，手边有金酒等"},
        {"role": "assistant", "content": first.response,
         "metadata": {"creative_brief": first.brief}},
    ]
    second = _fallback("还有汤力水、蜂蜜和罗勒，就这些，不要蛋清", history, [],
                       reason="insufficient_balance")

    assert second.brief["sweetness"].startswith("中低甜")
    assert "egg white" in second.brief["avoid_ingredients"]
    assert "egg white" not in second.brief["available_ingredients"]
    assert "basil" in second.brief["available_ingredients"]
    assert "不用蛋清" in second.response
    assert second.missing == ["饮用形态"]
    assert "长饮" in second.response and "短饮" in second.response


def test_creation_brief_applies_current_corrections_instead_of_merging_conflicts():
    from app.services.creative_dialogue import _fallback

    first = _fallback(
        "一起创作中低甜、中低酸、有酒感的金酒，有蜂蜜和汤力水",
        [], [], reason="connection_failed",
    )
    history = [
        {"role": "user", "content": "一起创作一杯金酒"},
        {"role": "assistant", "content": first.response,
         "metadata": {"creative_brief": first.brief}},
    ]
    corrected = _fallback(
        "刚才说错了，不要金酒，换成朗姆；不要蜂蜜，改成不酸，做短饮，餐后喝",
        history, [], reason="connection_failed",
    )

    assert corrected.brief["base_spirits"] == ["rum"]
    assert set(corrected.brief["avoid_ingredients"]) >= {"gin", "honey"}
    assert "honey" not in corrected.brief["available_ingredients"]
    assert corrected.brief["acidity"] == "避免明显酸味"
    assert corrected.brief["serve_style"] == "集中短饮"
    assert corrected.brief["occasion"] == "餐后"
    assert "可使用金酒" not in corrected.preferences
    assert "可使用朗姆酒" in corrected.preferences


def test_model_brief_cannot_undo_explicit_current_turn_corrections():
    from app.services.creative_dialogue import _reconcile_model_brief

    history = [{
        "role": "assistant", "content": "上一轮简报",
        "metadata": {"creative_brief": {
            "base_spirits": ["gin"], "available_ingredients": ["honey"],
            "avoid_ingredients": [], "acidity": "中低酸，有明亮感但不尖锐",
        }},
    }]
    stale_model_brief = {
        "base_spirits": ["gin"], "available_ingredients": ["honey"],
        "avoid_ingredients": [], "acidity": "中低酸，有明亮感但不尖锐",
    }

    result = _reconcile_model_brief(
        "不要金酒，换成朗姆；不要蜂蜜；改成不酸",
        history, [], stale_model_brief,
    )

    assert result["base_spirits"] == ["rum"]
    assert set(result["avoid_ingredients"]) >= {"gin", "honey"}
    assert "honey" not in result["available_ingredients"]
    assert result["acidity"] == "避免明显酸味"


def test_creative_model_prompt_receives_persisted_brief():
    from app.services.creative_dialogue import _PROMPT

    messages = _PROMPT.format_messages(
        query="改成短饮", history="用户: 改成短饮", stock="金酒",
        existing_brief="{'base_spirits': ['gin'], 'sweetness': '中低甜'}",
        format_instructions="输出 JSON",
    )

    assert "服务端保存的上一轮创作简报" in messages[-1].content
    assert "'base_spirits': ['gin']" in messages[-1].content


def test_creation_brief_can_restore_material_and_override_flavor_targets():
    from app.services.creative_dialogue import _fallback

    history = [{
        "role": "assistant", "content": "上一轮简报",
        "metadata": {"creative_brief": {
            "sweetness": "中低甜，能尝到甜味但不腻",
            "acidity": "中低酸，有明亮感但不尖锐",
            "alcohol": "保留清晰酒感",
            "base_spirits": ["gin"],
            "available_ingredients": ["tonic water"],
            "avoid_ingredients": ["egg white"],
            "inventory_complete": True,
        }},
    }]
    corrected = _fallback(
        "现在可以用蛋清，还是不想要甜味，酒味轻一点",
        history, [], reason="connection_failed",
    )

    assert "egg white" not in corrected.brief["avoid_ingredients"]
    assert "egg white" in corrected.brief["available_ingredients"]
    assert corrected.brief["sweetness"] == "不甜，保持干爽"
    assert corrected.brief["alcohol"] == "低酒精感"


def test_natural_confirmation_starts_creation_from_persisted_brief(monkeypatch):
    from app.agents.orchestrator_agent import Intent, plan_query
    from app.services.creative_dialogue import _fallback

    monkeypatch.setattr(
        "app.services.creative_dialogue.iter_configured_llms",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    first = _fallback(
        "一起创作一杯中低甜、中低酸、有酒感的金酒，手边只有汤力水、蜂蜜和罗勒",
        [], [], reason="connection_failed",
    )
    first.brief.update({"serve_style": "清爽长饮", "occasion": "聚会",
                        "inventory_complete": True})
    history = [
        {"role": "user", "content": "一起创作一杯金酒"},
        {"role": "assistant", "content": first.response,
         "metadata": {"creative_brief": first.brief}},
    ]

    plan = plan_query("按这版开始", history=history)

    assert plan.intent == Intent.CREATE
    assert plan.creation_ready is True
    assert plan.need_clarify is False
    assert "basil" in plan.creative_brief["available_ingredients"]


def test_inventory_fallback_uses_inline_materials_and_taste_without_model():
    from app.services.deterministic_chat import build_inventory_answer

    result = build_inventory_answer(
        "我有金酒、汤力水和柠檬，想喝清爽、有酒味，但不要太酸，能调什么？", [], 3,
    )

    assert result.recipes
    assert len(result.recipes) <= 3
    assert "模型推理不可用" in result.answer
    assert "金酒" in result.answer and "汤力水" in result.answer
    assert "库存覆盖" in result.answer or "可以直接调" in result.answer
    assert all(doc.collection == "cocktails" for doc in result.docs)
    assert result.recipes[0]["name"] == "Gin Tonic"


def test_inventory_profile_dislikes_are_hard_filters():
    from app.services.deterministic_chat import build_inventory_answer
    from app.services.recipe_catalog import canonical, get_recipe

    result = build_inventory_answer(
        "按我的库存推荐三杯", ["伏特加", "咖啡利口酒", "淡奶油"], 3,
        profile={"disliked_ingredients": ["淡奶油"]},
    )

    assert result.docs
    for doc in result.docs:
        recipe = get_recipe(doc.pk)
        ingredients = {
            canonical(item.get("canonical") or item.get("name") or "")
            for item in recipe.get("ingredients") or []
        }
        assert "cream" not in ingredients


def test_saved_profile_is_applied_to_normal_recommendations():
    recipes = recommend_many_for_query(
        "给我推荐五杯",
        5,
        profile={
            "preferred_spirits": ["gin"],
            "disliked_ingredients": ["egg white"],
            "sweetness": 4,
        },
    )

    assert len(recipes) == 5
    assert "gin" in {item["canonical"] for item in recipes[0]["ingredients"]}
    assert all(
        "egg white" not in {item["canonical"] for item in recipe["ingredients"]}
        for recipe in recipes
    )


def test_current_taste_request_overrides_saved_numeric_profile():
    recipes = recommend_many_for_query(
        "推荐五杯甜但不要太甜、酸但不要太酸、有酒味的金酒",
        5,
        profile={"sweetness": 9, "sourness": 9, "preferred_spirits": ["vodka"]},
    )

    assert len(recipes) == 5
    for recipe in recipes:
        assert "gin" in {item["canonical"] for item in recipe["ingredients"]}
        assert 3 <= recipe["flavor"]["sweet"] <= 5
        assert 2 <= recipe["flavor"]["sour"] <= 4
        assert recipe["flavor"]["strong"] >= 4


def test_inventory_mentions_keep_longest_overlapping_ingredient():
    from app.services.deterministic_chat import extract_inventory_mentions

    assert extract_inventory_mentions("我有伏特加、咖啡利口酒和淡奶油") == [
        "vodka", "coffee liqueur", "light cream",
    ]


def test_shared_constraint_handoff_merges_history_and_current_correction():
    from app.services.deterministic_chat import recommend_many_for_query
    from app.services.mixology_constraints import build_mixology_constraints

    recipes = recommend_many_for_query(
        "推荐五个甜但不要太甜、酸但不要太酸、有酒味的金酒", 5,
    )
    history = [
        {"role": "user", "content": "推荐五个甜但不要太甜、酸但不要太酸、有酒味的金酒"},
        {"role": "assistant", "content": "五款推荐", "metadata": {
            "recipes": [{"id": item["id"], "name": item["name"],
                         "name_cn": item["name_cn"]} for item in recipes],
        }},
    ]

    handoff = build_mixology_constraints(
        "第二个太酸，换个清爽一点的，不要蛋清", history,
        stock=["金酒", "汤力水", "青柠汁"],
        profile={"disliked_ingredients": ["淡奶油"], "sweetness": 4},
    )

    assert handoff.contextual_followup is True
    assert "甜但不要太甜" in handoff.effective_query
    assert "第二个太酸" in handoff.effective_query
    assert handoff.required_base_spirits == ["gin"]
    assert handoff.hard_flavor_ranges["甜度"] == [3.0, 5.0]
    assert handoff.hard_flavor_ranges["酸度"] == [0.0, 3.0]
    assert set(handoff.excluded_ingredients) >= {"egg white", "light cream"}
    assert handoff.style_preferences == ["清爽"]
    assert set(handoff.excluded_recipe_ids) == {str(item["id"]) for item in recipes}


def test_stock_agent_uses_shared_exclusions_on_followup(monkeypatch):
    from app.agents.base import AgentContext
    from app.agents.stock_agent import run_stock_agent
    from app.core.context import reset_current_session, set_current_session
    from app.services.deterministic_chat import build_inventory_answer
    from app.services.mixology_constraints import build_mixology_constraints

    stock = ["金酒", "汤力水", "青柠汁", "柠檬汁", "糖浆", "橙汁"]
    first = build_inventory_answer("按库存推荐三杯清爽的", stock, count=3)
    assert first.recipes
    history = [
        {"role": "user", "content": "按库存推荐三杯清爽的"},
        {"role": "assistant", "content": "三款推荐", "metadata": {
            "recipes": [{"id": item["id"], "name": item["name"],
                         "name_cn": item["name_cn"]} for item in first.recipes],
        }},
    ]
    handoff = build_mixology_constraints("换一个，不要之前的", history, stock=stock)
    monkeypatch.setattr(
        "app.agents.stock_agent.get_llm",
        lambda **_: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    token = set_current_session(stock=stock, profile={})
    try:
        ctx = run_stock_agent(AgentContext(
            user_query=handoff.effective_query,
            history=history,
            extra={"constraints": handoff.model_dump()},
        ))
    finally:
        reset_current_session(token)

    returned = {str(item["id"]) for item in ctx.extra["recipes"]}
    assert len(returned) == 1
    assert not returned & set(handoff.excluded_recipe_ids)


def test_inventory_route_keeps_stock_and_flavor_when_model_is_down(monkeypatch):
    from app.agents.orchestrator_agent import Intent, plan_query

    monkeypatch.setattr("app.agents.orchestrator_agent.get_llm",
                        lambda **_: (_ for _ in ()).throw(RuntimeError("model down")))
    plan = plan_query("我有金酒和汤力，想喝清爽但别太酸的，能调什么")

    assert plan.intent == Intent.RECOMMEND
    assert plan.need_stock is True
    assert plan.need_flavor is True
    assert plan.need_retrieve is True


def test_every_catalog_recipe_has_executable_steps_and_method():
    recipes = all_recipes()
    assert len(recipes) == 441
    assert all(len(recipe["steps"]) >= 4 for recipe in recipes)
    assert all(recipe["method"] and recipe["equipment"] for recipe in recipes)
    assert any(recipe["timer_seconds"] > 0 for recipe in recipes)


def test_catalog_multi_keyword_search_and_sort():
    results = search_recipes(q="gin lemon", sort="abv_asc")
    assert results
    assert [float(item["abv"] or 0) for item in results] == sorted(float(item["abv"] or 0) for item in results)
