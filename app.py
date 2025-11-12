from datetime import datetime, timedelta
from io import BytesIO
import base64
import os

from flask import Flask, render_template, request, jsonify, redirect, url_for, send_file
from flask_sqlalchemy import SQLAlchemy

from models import db, Person, Setting
import qrcode

app = Flask(__name__)
# Use DATABASE_URL from environment (Railway/Postgres). Fall back to local SQLite for dev.
database_url = os.environ.get('DATABASE_URL') or 'sqlite:///queue.db'
# SQLAlchemy expects postgresql://; some providers return postgres://
if database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)
# We will call init_db() after the function definition to ensure it's defined

# Utility functions

def init_db():
    with app.app_context():
        db.create_all()
        if Setting.query.get(1) is None:
            s = Setting(id=1, tour_length_seconds=300, timer_paused=False, start_time=None, time_remaining_on_pause=None)
            db.session.add(s)
            db.session.commit()


# Ensure DB tables exist and default settings are created when the app is imported (e.g. by Gunicorn)
with app.app_context():
    init_db()


def get_setting():
    s = Setting.query.get(1)
    if not s:
        init_db()
        s = Setting.query.get(1)
    return s


def get_waiting():
    return Person.query.filter_by(status='waiting').order_by(Person.position).all()


def get_passed():
    return Person.query.filter_by(status='passed').order_by(Person.passed_at.desc()).all()


def compute_time_remaining_seconds(setting):
    if setting.timer_paused:
        return setting.time_remaining_on_pause
    start = setting.start_time
    if not start:
        return None
    elapsed = (datetime.utcnow() - start).total_seconds()
    return max(int(setting.tour_length_seconds - elapsed), 0)


def process_timer_advances():
    """Check if one or more tours have passed and advance the queue accordingly.
    This function is idempotent and called on every status request.
    """
    s = get_setting()
    if s.timer_paused or not s.start_time:
        return
    tour_len = s.tour_length_seconds
    # While enough time has passed and we have waiting people, advance
    while True:
        if not s.start_time:
            break
        now = datetime.utcnow()
        elapsed = (now - s.start_time).total_seconds()
        if elapsed < tour_len:
            break
        # Pop first waiting
        first = Person.query.filter_by(status='waiting').order_by(Person.position).first()
        if not first:
            s.start_time = None
            s.time_remaining_on_pause = None
            db.session.commit()
            break
        # Mark passed
        first.status = 'passed'
        first.passed_at = s.start_time + timedelta(seconds=tour_len)
        # Remove from queue: shift positions
        waiting = Person.query.filter(Person.status == 'waiting').order_by(Person.position).all()
        # Now waiting contains list where first is the current; update positions
        # After moving the first, shift positions: decrement position by 1 for all others
        for w in waiting:
            if w.id == first.id:
                continue
            # If waiting position > first.position, shift up
            if w.position and w.position > first.position:
                w.position -= 1
        first.position = None
        db.session.add(first)
        db.session.commit()
        # Move start_time forward by one tour length; if no more waiting, clear start_time
        waiting_after = Person.query.filter_by(status='waiting').order_by(Person.position).all()
        if waiting_after:
            s.start_time = s.start_time + timedelta(seconds=tour_len)
        else:
            s.start_time = None
        db.session.commit()
        # Loop again in case multiple intervals have passed


def add_person(name):
    waiting = get_waiting()
    if waiting:
        max_pos = waiting[-1].position or len(waiting)
    else:
        max_pos = 0
    new_person = Person(name=name, status='waiting', position=max_pos + 1, added_at=datetime.utcnow())
    db.session.add(new_person)
    # If no start_time, set start_time to now
    s = get_setting()
    if not s.start_time and not s.timer_paused:
        s.start_time = datetime.utcnow()
    elif not s.start_time and s.timer_paused:
        # if paused, keep settings but do not set start_time, but keep a full ticket length
        if s.time_remaining_on_pause is None:
            s.time_remaining_on_pause = s.tour_length_seconds
    db.session.commit()
    return new_person


def advance_next():
    """Manual advance to next: move first waiting person to passed and reset timer."""
    s = get_setting()
    first = Person.query.filter_by(status='waiting').order_by(Person.position).first()
    if not first:
        return None
    # Mark passed
    now = datetime.utcnow()
    first.status = 'passed'
    first.passed_at = now
    # Shift positions
    waiting = Person.query.filter(Person.status == 'waiting').order_by(Person.position).all()
    for w in waiting:
        if w.id == first.id:
            continue
        if w.position and w.position > first.position:
            w.position -= 1
    first.position = None
    # Set new start_time
    waiting_after = Person.query.filter_by(status='waiting').order_by(Person.position).all()
    if waiting_after:
        s.start_time = now
    else:
        s.start_time = None
    # If paused, set time_remaining to full length
    if s.timer_paused:
        s.time_remaining_on_pause = s.tour_length_seconds
    db.session.commit()
    return first


def go_back():
    """Move last passed person back to the front of the queue."""
    s = get_setting()
    last_passed = Person.query.filter_by(status='passed').order_by(Person.passed_at.desc()).first()
    if not last_passed:
        return None
    # Change status and insert at front position 1
    # Increment position of existing waiting
    waiting = Person.query.filter(Person.status == 'waiting').order_by(Person.position).all()
    for w in waiting:
        w.position = (w.position or 0) + 1
    last_passed.status = 'waiting'
    last_passed.position = 1
    last_passed.passed_at = None
    now = datetime.utcnow()
    # Set start_time to now or if paused keep pause
    if not s.timer_paused:
        s.start_time = now
    else:
        s.time_remaining_on_pause = s.tour_length_seconds
    db.session.commit()
    return last_passed


def reorder_waiting(new_order_ids):
    """new_order_ids is a list of person IDs representing desired order front-to-back"""
    waiting = Person.query.filter(Person.status == 'waiting').all()
    # Validate that ids match
    waiting_ids = {p.id for p in waiting}
    for _id in new_order_ids:
        if _id not in waiting_ids:
            raise ValueError('Invalid id in reorder')
    # Update positions
    for idx, pid in enumerate(new_order_ids):
        p = Person.query.get(pid)
        p.position = idx + 1
    # Set start_time to now on reorder (front may have changed)
    s = get_setting()
    now = datetime.utcnow()
    if not s.timer_paused:
        s.start_time = now
    else:
        s.time_remaining_on_pause = s.tour_length_seconds
    db.session.commit()


def estimate_wait_minutes(person):
    s = get_setting()
    if not person.position:
        return 0
    return int((person.position - 1) * s.tour_length_seconds / 60)


@app.route('/')
def index():
    s = get_setting()
    # Generate QR code for register URL
    register_url = url_for('register', _external=True)
    img = qrcode.make(register_url)
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    img_b64 = base64.b64encode(buffer.read()).decode('ascii')
    return render_template('index.html', qr_img=img_b64)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        data = request.form or request.json
        name = data.get('name')
        if not name:
            return jsonify({'error': 'name required'}), 400
        newp = add_person(name)
        return jsonify(newp.to_dict()), 201
    # GET: return a small page (popup) with a form
    return render_template('register.html')


@app.route('/api/status')
def api_status():
    # On status request, process any automatic advances
    process_timer_advances()
    waiting = get_waiting()
    passed = get_passed()
    s = get_setting()
    time_remaining = compute_time_remaining_seconds(s)
    data = {
        'waiting': [p.to_dict() for p in waiting],
        'passed': [p.to_dict() for p in passed],
        'tour_length_seconds': s.tour_length_seconds,
        'timer_paused': s.timer_paused,
        'time_remaining_seconds': time_remaining,
    }
    return jsonify(data)


@app.route('/api/next', methods=['POST'])
def api_next():
    p = advance_next()
    if p is None:
        return jsonify({'message': 'No one to advance'}), 400
    return jsonify({'message': 'advanced', 'person': p.to_dict()})


@app.route('/api/back', methods=['POST'])
def api_back():
    p = go_back()
    if p is None:
        return jsonify({'message': 'No one to go back'}), 400
    return jsonify({'message': 'backed', 'person': p.to_dict()})


@app.route('/api/pause', methods=['POST'])
def api_pause():
    s = get_setting()
    if s.timer_paused:
        # resume
        if s.time_remaining_on_pause is None:
            s.time_remaining_on_pause = s.tour_length_seconds
        # Compute new start_time: start_time = now - (L - R)
        now = datetime.utcnow()
        s.start_time = now - timedelta(seconds=(s.tour_length_seconds - s.time_remaining_on_pause))
        s.time_remaining_on_pause = None
        s.timer_paused = False
        db.session.commit()
        return jsonify({'message': 'resumed'})
    else:
        # pause
        now = datetime.utcnow()
        if s.start_time is None:
            s.time_remaining_on_pause = s.tour_length_seconds
        else:
            elapsed = (now - s.start_time).total_seconds()
            rem = max(int(s.tour_length_seconds - elapsed), 0)
            s.time_remaining_on_pause = rem
        s.timer_paused = True
        db.session.commit()
        return jsonify({'message': 'paused', 'time_remaining_seconds': s.time_remaining_on_pause})


@app.route('/api/reorder', methods=['POST'])
def api_reorder():
    data = request.get_json() or {}
    ids = data.get('ids')
    if not ids or not isinstance(ids, list):
        return jsonify({'error': 'ids list required'}), 400
    try:
        reorder_waiting(ids)
        return jsonify({'message': 'reordered'})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


def move_person_to(person_id, to_status, to_position=None):
    p = Person.query.get(person_id)
    if not p:
        raise ValueError('person not found')
    s = get_setting()
    now = datetime.utcnow()

    # moving to waiting queue
    if to_status == 'waiting':
        if p.status == 'passed':
            # insert at specified position or at front
            waiting = Person.query.filter(Person.status == 'waiting').order_by(Person.position).all()
            if to_position is None or to_position < 1:
                insert_pos = 1
            else:
                insert_pos = min(len(waiting) + 1, to_position)
            # shift positions
            for w in waiting:
                if w.position and w.position >= insert_pos:
                    w.position += 1
            p.status = 'waiting'
            p.position = insert_pos
            p.passed_at = None
        elif p.status == 'waiting':
            # just reposition in waiting list
            waiting = [w for w in Person.query.filter(Person.status == 'waiting').order_by(Person.position).all()]
            # if position not provided, do nothing
            if to_position is None:
                return
            to_pos = max(1, min(len(waiting), to_position))
            # move within waiting
            old_pos = p.position
            if old_pos == to_pos:
                return
            if old_pos > to_pos:
                # shift others down
                for w in waiting:
                    if w.position >= to_pos and w.position < old_pos:
                        w.position += 1
            else:
                # shift others up
                for w in waiting:
                    if w.position <= to_pos and w.position > old_pos:
                        w.position -= 1
            p.position = to_pos
    elif to_status == 'passed':
        # Move to passed (either from waiting or already passed), mark passed_at
        if p.status == 'waiting':
            # remove from waiting and shift positions
            waiting = Person.query.filter(Person.status == 'waiting').order_by(Person.position).all()
            for w in waiting:
                if w.position and w.position > p.position:
                    w.position -= 1
            p.position = None
        p.status = 'passed'
        p.passed_at = now
    else:
        raise ValueError('invalid target status')

    # if change affects front person, reset timer
    # get current first
    first = Person.query.filter_by(status='waiting').order_by(Person.position).first()
    if not s.timer_paused:
        if first:
            s.start_time = now
        else:
            s.start_time = None
    else:
        s.time_remaining_on_pause = s.tour_length_seconds
    db.session.commit()


@app.route('/api/move', methods=['POST'])
def api_move():
    data = request.get_json() or {}
    pid = data.get('id')
    to_status = data.get('toStatus')
    to_pos = data.get('toPosition')
    if not pid or not to_status:
        return jsonify({'error': 'id and toStatus required'}), 400
    try:
        move_person_to(int(pid), to_status, to_pos)
        return jsonify({'message':'moved'})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/set-tour-length', methods=['POST'])
def api_set_tour_length():
    data = request.get_json() or {}
    value = data.get('seconds') or data.get('minutes')
    s = get_setting()
    if 'minutes' in data and isinstance(data['minutes'], (int, float)):
        s.tour_length_seconds = int(data['minutes'] * 60)
    elif 'seconds' in data and isinstance(data['seconds'], (int, float)):
        s.tour_length_seconds = int(data['seconds'])
    else:
        return jsonify({'error': 'seconds or minutes required'}), 400
    # Reset timer for new interval: if running, set start_time to now; if paused, set pause remaining to full
    if not s.timer_paused:
        s.start_time = datetime.utcnow()
    else:
        s.time_remaining_on_pause = s.tour_length_seconds
    db.session.commit()
    return jsonify({'message': 'tour length set', 'tour_length_seconds': s.tour_length_seconds})


@app.route('/qrcode')
def qrcode_image():
    # Return QR code for the register page as image/png
    register_url = url_for('register', _external=True)
    img = qrcode.make(register_url)
    buffer = BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)
    return send_file(buffer, mimetype='image/png')


# Small convenience API to clear the queue - for tests/admin
@app.route('/api/clear', methods=['POST'])
def api_clear():
    num = 0
    Person.query.delete()
    Setting.query.delete()
    db.session.commit()
    init_db()
    return jsonify({'message': 'cleared'})


if __name__ == '__main__':
    init_db()
    # Local dev: use PORT env var if present
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
