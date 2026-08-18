from app.notify.dispatcher import _deliver


class RecordingSession:
    def __init__(self) -> None:
        self.added = []

    def add(self, item) -> None:
        self.added.append(item)


def test_deliver_preserves_all_digest_match_ids():
    session = RecordingSession()

    _deliver(
        session,
        tenant_id=7,
        title="商机日报：今日推荐 2 条",
        body="two opportunities",
        channels={},
        related_match_ids=[101, 102],
    )

    assert len(session.added) == 1
    notification = session.added[0]
    assert notification.related_match_id is None
    assert notification.related_match_ids == [101, 102]


def test_deliver_keeps_single_match_compatibility():
    session = RecordingSession()

    _deliver(
        session,
        tenant_id=7,
        title="新商机",
        body="one opportunity",
        channels={},
        related_match_id=101,
    )

    notification = session.added[0]
    assert notification.related_match_id == 101
    assert notification.related_match_ids == []
