# -*- coding: utf-8 -*-
"""Fixed retrieval validation set. Generated from immutable case constants."""
from __future__ import annotations

RECIPE_CASES = [
    ("11007", "Margarita", "玛格丽特"), ("11000", "Mojito", "莫吉托"),
    ("11001", "Old Fashioned", "古典鸡尾酒"), ("11003", "Negroni", "内格罗尼"),
    ("11008", "Manhattan", "曼哈顿"), ("11006", "Daiquiri", "得其利"),
    ("11004", "Whiskey Sour", "威士忌酸"), ("11410", "Gin Fizz", "金菲士"),
    ("11009", "Moscow Mule", "莫斯科骡子"), ("17196", "Cosmopolitan", "大都会"),
    ("12196", "Sidecar", "边车"), ("17180", "Aviation", "Aviation"),
    ("17207", "Pina Colada", "椰林飘香"), ("11690", "Mai Tai", "迈泰"),
    ("11005", "Dry Martini", "干马天尼"), ("17197", "French 75", "法国75"),
    ("12402", "Tom Collins", "汤姆柯林斯"), ("12528", "White Russian", "白俄罗斯"),
    ("17195", "Bellini", "Bellini"), ("13621", "Tequila Sunrise", "龙舌兰日出"),
    ("11288", "Cuba Libre", "自由古巴"), ("13971", "Irish Coffee", "爱尔兰咖啡"),
]

KNOWLEDGE_CASES = [
    ("sub_acid_lime_lemon", "青柠汁没有了，可以用柠檬汁替代吗"),
    ("sub_sweet_syrup", "简单糖浆能不能换成蜂蜜"),
    ("sub_bitters", "没有安格斯图拉苦精怎么办"),
    ("sub_gin_vodka", "金酒和伏特加能互换吗"),
    ("sub_white_dark_rum", "白朗姆能换成黑朗姆吗"),
    ("sub_soda_tonic", "苏打水与汤力水有什么区别"),
    ("sub_egg_foam", "不使用生蛋清怎么做泡沫"),
    ("sub_vermouth", "甜味美思能直接换干味美思吗"),
    ("tech_shake", "什么样的鸡尾酒应该摇和"),
    ("tech_stir", "什么时候应该使用搅拌法"),
    ("tech_muddle", "薄荷应该怎样捣压才不发苦"),
    ("tech_layer", "分层鸡尾酒怎么制作"),
    ("tech_rim", "杯沿盐边怎么做"),
    ("guide_tools", "新手调酒需要哪些工具"),
]

NO_ANSWER_CASES = [
    "火星蓝藻发酵液的 ISO 编号是什么", "量子泡沫摇壶由谁在 1842 年发明",
    "给我一份不存在的银河 77 号配方", "月球重力下酒液表面张力的精确常数",
    "BartenderAI 创始人的身份证号码", "预测明年某品牌威士忌的准确股票价格",
    "用未知化学品 ZQ-19 调酒的官方安全剂量", "查询虚构酒吧午夜鲸的实时座位",
    "证明鸡尾酒可以治疗感冒", "未成年人每天喝多少烈酒最健康",
    "蓝鲸声波给鸡尾酒增甜的标准比例是多少", "用云层颜色判断摇和完成的公式",
    "编造一份不存在的深海极光官方配方", "Python 字典和金酒的共同发明人是谁",
    "下一届世界杯决赛时应该使用哪种滤冰器", "用手机电量预测马天尼稀释率",
    "告诉我某位陌生顾客昨晚喝了什么", "把任意清洁剂当苦精的安全用量",
    "鸡尾酒能保证治好失眠吗", "给儿童设计一杯高度烈酒",
]


def fixed_eval_set() -> list[dict]:
    records = []
    for recipe_id, english, chinese in RECIPE_CASES:
        records.extend([
            {"query": f"{chinese}的经典配方", "relevant": [f"cocktails:{recipe_id}"]},
            {"query": f"{english} 怎么调", "relevant": [f"cocktails:{recipe_id}"]},
            {"query": f"做{chinese}需要什么材料和用量", "relevant": [f"cocktails:{recipe_id}"]},
        ])
    records.extend({"query": query, "relevant": [f"knowledge:{doc_id}"]}
                   for doc_id, query in KNOWLEDGE_CASES)
    records.extend({"query": query, "relevant": []} for query in NO_ANSWER_CASES)
    return records
