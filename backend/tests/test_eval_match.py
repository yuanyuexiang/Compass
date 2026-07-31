"""匹配评测指标测试：覆盖多画像宏平均、排序召回和高价值漏报。"""

from scripts.eval_match import calculate_metrics, dataset_summary


def test_calculate_metrics_for_multiple_profiles():
    rows = [
        {
            "profile_id": "a",
            "expected_star": 5,
            "expected_advice": "建议参与",
            "got_star": 5,
            "got_score": 92,
            "got_advice": "建议参与",
        },
        {
            "profile_id": "a",
            "expected_star": 1,
            "expected_advice": "不建议参与",
            "got_star": 2,
            "got_score": 55,
            "got_advice": "不建议参与",
        },
        {
            "profile_id": "b",
            "expected_star": 4,
            "expected_advice": "建议参与",
            "got_star": 2,
            "got_score": 60,
            "got_advice": "不建议参与",
        },
    ]
    metrics = calculate_metrics(rows)
    assert metrics["profiles"] == 2
    assert metrics["positive_count"] == 2
    assert metrics["high_value_missed"] == 1
    assert metrics["star_exact"] == 1 / 3
    assert metrics["recall_at_10"] == 1


def test_dataset_summary_exposes_label_imbalance():
    items = [
        {"profile_id": "a", "expected_star": 1},
        {"profile_id": "a", "expected_star": 1},
        {"profile_id": "b", "expected_star": 5},
    ]
    summary = dataset_summary(items)
    assert summary == {
        "profiles": 2,
        "samples": 3,
        "stars": {1: 2, 5: 1},
        "positive_count": 1,
    }
