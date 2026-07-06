NL_SEARCH_PROMPT_V1 = """把用户的招标商机查询解析为 json 过滤条件，结构：
{"keyword": 核心关键词字符串或null, "region": 省份或城市或null, "budget_min": 预算下限数字（元）或null, "budget_max": 预算上限数字（元）或null, "category_main": "IT类"/"软件类"/"工程类"/"货物类"/"服务类"或null}
例：「查找江苏省预算超过300万的 AI 项目」→ {"keyword": "AI", "region": "江苏", "budget_min": 3000000, "budget_max": null, "category_main": null}
只输出 json。"""
