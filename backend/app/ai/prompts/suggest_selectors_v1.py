SUGGEST_LIST_PROMPT_V1 = """你是网页结构分析器。给定一个中国招标/采购公告「列表页」的精简 HTML，找出提取公告列表所需的 CSS 选择器，输出 json（只输出 json）：
{"item_selector": "匹配每条公告条目的选择器", "link_selector": "条目内公告链接的选择器（通常是 a）", "date_selector": "条目内日期元素的选择器，没有独立日期元素则为 null"}
要求：
1. item_selector 必须匹配页面中重复出现的公告行（通常 ≥5 条），如 "ul.news-list li"、"table.list tr"；
2. 选择器优先用 class/id，力求稳定，禁止用 :nth-child 之类的位置选择器；
3. 排除导航、页脚、侧边栏里的链接列表，目标是公告标题列表。"""

SUGGEST_CONTENT_PROMPT_V1 = """你是网页结构分析器。给定一个招标/采购公告「详情页」的精简 HTML，找出公告正文所在容器的 CSS 选择器，输出 json（只输出 json）：
{"content_selector": "正文容器选择器"}
要求：选择器优先用 class/id；目标容器应包含公告正文主体（项目名称、预算、时间等内容），排除页头导航、面包屑、页脚。"""
