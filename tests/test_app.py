import pytest
import json
from datetime import datetime, timedelta
from app import app, init_db
from models import db, Person, Setting

@pytest.fixture(autouse=True)
def setup_and_teardown():
    # Clean database for each test
    with app.app_context():
        db.drop_all()
        db.create_all()
        init_db()
    yield
    with app.app_context():
        db.drop_all()


def test_register_and_status():
    client = app.test_client()
    # Register a person
    res = client.post('/register', json={'name': 'Alice'})
    assert res.status_code == 201
    data = res.get_json()
    assert data['name'] == 'Alice'

    # Check status contains Alice
    res = client.get('/api/status')
    assert res.status_code == 200
    data = res.get_json()
    names = [p['name'] for p in data['waiting']]
    assert 'Alice' in names


def test_next_and_back_operations():
    client = app.test_client()
    # Add people
    client.post('/register', json={'name':'Alice'})
    client.post('/register', json={'name':'Bob'})
    client.post('/register', json={'name':'Carla'})

    # Next: should move Alice to passed
    res = client.post('/api/next')
    assert res.status_code == 200
    data = client.get('/api/status').get_json()
    waiting_names = [p['name'] for p in data['waiting']]
    assert 'Alice' not in waiting_names
    passed_names = [p['name'] for p in data['passed']]
    assert 'Alice' in passed_names

    # Back: should move Alice back to front
    res = client.post('/api/back')
    assert res.status_code == 200
    data = client.get('/api/status').get_json()
    waiting_names = [p['name'] for p in data['waiting']]
    assert waiting_names[0] == 'Alice'


def test_reorder():
    client = app.test_client()
    # Add people
    client.post('/register', json={'name':'A'})
    client.post('/register', json={'name':'B'})
    client.post('/register', json={'name':'C'})
    res = client.get('/api/status')
    ids = [p['id'] for p in res.get_json()['waiting']]
    # re-order to [C, B, A]
    ids_reordered = list(reversed(ids))
    res = client.post('/api/reorder', json={'ids': ids_reordered})
    assert res.status_code == 200
    res = client.get('/api/status')
    names = [p['name'] for p in res.get_json()['waiting']]
    assert names[0] == 'C' and names[1] == 'B' and names[2] == 'A'


def test_set_tour_length():
    client = app.test_client()
    # set to 2 minutes
    res = client.post('/api/set-tour-length', json={'minutes': 2})
    assert res.status_code == 200
    data = res.get_json()
    assert data['tour_length_seconds'] == 120


def test_change_tour_length_preserves_remaining():
    client = app.test_client()
    # Add two people so that we have a current person
    client.post('/register', json={'name':'P1'})
    client.post('/register', json={'name':'P2'})
    with app.app_context():
        s = Setting.query.get(1)
        # use longer intervals to avoid timing flakiness
        s.tour_length_seconds = 60
        s.start_time = datetime.utcnow() - timedelta(seconds=20)  # 20s elapsed -> remaining = 40s
        s.timer_paused = False
        db.session.commit()
        from app import compute_time_remaining_seconds
        old_remaining = compute_time_remaining_seconds(s)
    assert abs(old_remaining - 40) <= 1
    # Now change tour length to 10 seconds and ensure remaining stays same (3s)
    res = client.post('/api/set-tour-length', json={'seconds': 120})
    assert res.status_code == 200
    # check compute_time_remaining_seconds
    with app.app_context():
        from app import compute_time_remaining_seconds
        s2 = Setting.query.get(1)
        rem_after = compute_time_remaining_seconds(s2)
    assert abs(rem_after - 40) <= 2


def test_move_endpoint():
    client = app.test_client()
    client.post('/register', json={'name':'Alice'})
    client.post('/register', json={'name':'Bob'})
    # move Alice to passed
    client.post('/api/next')
    res = client.get('/api/status')
    passed = res.get_json()['passed']
    assert len(passed) == 1
    pid = passed[0]['id']
    # move back using api/move
    r = client.post('/api/move', json={'id': pid, 'toStatus': 'waiting', 'toPosition': 1})
    assert r.status_code == 200
    res2 = client.get('/api/status')
    waiting = res2.get_json()['waiting']
    assert waiting[0]['id'] == pid


def test_auto_advance():
    client = app.test_client()
    # Add two persons
    client.post('/register', json={'name':'Alex'})
    client.post('/register', json={'name':'Bea'})
    # Set start_time to beyond the tour length so auto-advance occurs
    with app.app_context():
        s = Setting.query.get(1)
        s.tour_length_seconds = 1  # one second for quick test
        s.start_time = datetime.utcnow() - timedelta(seconds=2)
        s.timer_paused = False
        db.session.commit()
    # Status call should process automatic advancing
    res = client.get('/api/status')
    data = res.get_json()
    assert len(data['passed']) >= 1


def test_delete_passed_person():
    client = app.test_client()
    # Add two people and advance first
    client.post('/register', json={'name':'Alpha'})
    client.post('/register', json={'name':'Beta'})
    client.post('/api/next')
    res = client.get('/api/status')
    data = res.get_json()
    passed = data['passed']
    assert len(passed) >= 1
    pid = passed[0]['id']
    # Delete passed person
    r = client.delete(f'/api/person/{pid}')
    assert r.status_code == 200
    res2 = client.get('/api/status')
    data2 = res2.get_json()
    passed2 = data2['passed']
    assert all(p['id'] != pid for p in passed2)


def test_reset_clears_all():
    client = app.test_client()
    client.post('/register', json={'name':'One'})
    client.post('/register', json={'name':'Two'})
    # reset
    res = client.post('/api/clear')
    assert res.status_code == 200
    res2 = client.get('/api/status')
    data = res2.get_json()
    assert data['waiting'] == [] and data['passed'] == []
    # default setting exists
    with app.app_context():
        s = Setting.query.get(1)
        assert s is not None
        assert s.tour_length_seconds == 300


def test_clear_persons_only():
    client = app.test_client()
    client.post('/register', json={'name':'One'})
    client.post('/register', json={'name':'Two'})
    # modify setting
    with app.app_context():
        s = Setting.query.get(1)
        s.tour_length_seconds = 120
        s.timer_paused = False
        db.session.commit()
    # clear persons
    res = client.post('/api/clear-persons')
    assert res.status_code == 200
    # persons cleared
    res2 = client.get('/api/status')
    data = res2.get_json()
    assert data['waiting'] == [] and data['passed'] == []
    # setting remains
    with app.app_context():
        s2 = Setting.query.get(1)
        assert s2.tour_length_seconds == 120


if __name__ == '__main__':
    pytest.main(['-q'])
