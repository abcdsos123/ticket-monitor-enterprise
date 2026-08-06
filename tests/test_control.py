from tixcraft_v17.monitor import ControlQueue
def test_control_queue(tmp_path):
    q=ControlQueue(tmp_path/'control.json'); q.request('check',event_code='abc'); xs=q.pop_all()
    assert xs[0]['action']=='check'; assert q.pop_all()==[]
