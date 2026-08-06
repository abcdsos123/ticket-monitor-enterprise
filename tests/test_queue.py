from tixcraft_v17.notifier import NotificationQueue


def test_queue(tmp_path):
    queue = NotificationQueue(tmp_path / "queue.json")
    item_id = queue.enqueue("hello")
    assert len(queue.list()) == 1
    queue.remove(item_id)
    assert queue.list() == []
