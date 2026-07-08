"""公告阶段判定测试：可投标商机 vs 已结束/废标。"""

from app.opportunity import (
    STAGE_BIDDABLE,
    STAGE_CLOSED,
    STAGE_CORRECTION,
    STAGE_FAILED,
    announcement_stage,
    is_biddable,
)


def test_biddable_types():
    types = ["招标公告/资审公告", "公开招标", "采购公告", "竞争性磋商公告", "询价公告"]
    for t in types:
        assert announcement_stage(t) == STAGE_BIDDABLE
        assert is_biddable(t) is True


def test_closed_types_not_opportunity():
    for t in ["中标公告", "中标结果公告", "成交公告", "中标候选人公示"]:
        assert announcement_stage(t) == STAGE_CLOSED
        assert is_biddable(t) is False


def test_failed_types_not_opportunity():
    for t in ["废标公告", "流标公告", "终止公告"]:
        assert announcement_stage(t) == STAGE_FAILED
        assert is_biddable(t) is False


def test_correction_kept_as_opportunity():
    # 纯更正公告可能延长投标机会 → 保留
    assert announcement_stage("更正公告") == STAGE_CORRECTION
    assert is_biddable("更正公告") is True


def test_won_bid_priority_over_招标():
    # "招标代理机构中标公告" 同时含"招标"和"中标"，应判已结束（中标优先）
    assert announcement_stage("其他公告", "XX项目招标代理机构中标公告") == STAGE_CLOSED
    assert is_biddable("其他公告", "XX项目招标代理机构中标公告") is False


def test_result_correction_still_closed():
    # 结果类的更正仍算已结束（CLOSED 优先于 CORRECTION）
    assert announcement_stage("更正公告", "中标结果更正公告") == STAGE_CLOSED


def test_title_based_when_type_missing():
    # ann_type 缺失时靠标题判定
    assert is_biddable(None, "某某项目公开招标公告") is True
    assert is_biddable(None, "某某项目中标公告") is False


def test_real_case_from_db():
    # 库里真实那条被误推荐的
    assert is_biddable("中标公告", "东南大学科研院知识产权代理机构遴选项目中标公告") is False
    assert is_biddable("招标公告/资审公告", "江苏省苏州实验中学金山路校区改造工程") is True
