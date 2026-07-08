"""公告阶段判定：区分「可投标商机」与「已结束/无效」公告。

「寻标」只推荐还能投标的项目。中标/成交/废标类公告仍采集入库、可在商机查询检索
（供 V3 历史中标分析、竞争对手分析用），但不进入匹配推荐、不发通知。

判定基于公告类型（ann_type）+ 标题关键词，纯规则、零成本。判定从严拦截「已结束」，
其余从宽保留（宁可多推、不漏真商机）。
"""

# 已结束：已定中标人/成交，投不了了
CLOSED_KW = ("中标", "成交", "中选", "中标结果", "结果公告", "中标候选人", "成交结果", "评标结果")
# 废标/流标/终止：本轮无效（可能重新招标，是信号但非当前可投商机）
FAILED_KW = ("废标", "流标", "终止公告", "采购失败")
# 更正/变更/答疑：可能延长投标机会，保留为商机（结果类更正已被 CLOSED 优先拦截）
CORRECTION_KW = ("更正", "变更", "答疑", "澄清", "延期", "补充公告")

STAGE_BIDDABLE = "biddable"   # 可投标（招标/采购/资审/询价/磋商…）
STAGE_CLOSED = "closed"       # 已结束（中标/成交）
STAGE_FAILED = "failed"       # 废标/流标/终止
STAGE_CORRECTION = "correction"  # 更正/变更


def announcement_stage(ann_type: str | None, title: str | None = None) -> str:
    """判定公告处于招投标的哪个阶段。优先级：已结束 > 废标 > 更正 > 默认可投标。"""
    text = f"{ann_type or ''} {title or ''}"
    if any(kw in text for kw in CLOSED_KW):
        return STAGE_CLOSED
    if any(kw in text for kw in FAILED_KW):
        return STAGE_FAILED
    if any(kw in text for kw in CORRECTION_KW):
        return STAGE_CORRECTION
    return STAGE_BIDDABLE


def is_biddable(ann_type: str | None, title: str | None = None) -> bool:
    """是否为「还能投标」的商机——只有这类才进入匹配推荐与通知。"""
    return announcement_stage(ann_type, title) not in (STAGE_CLOSED, STAGE_FAILED)
