from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class Person(db.Model):
    __tablename__ = 'persons'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    status = db.Column(db.String(32), nullable=False, default='waiting')  # 'waiting' or 'passed'
    position = db.Column(db.Integer, nullable=True)  # 1-based position in waiting queue
    added_at = db.Column(db.DateTime, default=datetime.utcnow)
    passed_at = db.Column(db.DateTime, nullable=True)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'status': self.status,
            'position': self.position,
            'added_at': self.added_at.isoformat() if self.added_at else None,
            'passed_at': self.passed_at.isoformat() if self.passed_at else None,
        }

class Setting(db.Model):
    __tablename__ = 'settings'
    id = db.Column(db.Integer, primary_key=True)
    tour_length_seconds = db.Column(db.Integer, nullable=False, default=300)  # 5 minutes
    timer_paused = db.Column(db.Boolean, nullable=False, default=False)
    start_time = db.Column(db.DateTime, nullable=True)  # start time of current person's tour
    time_remaining_on_pause = db.Column(db.Integer, nullable=True)  # in seconds

    def to_dict(self):
        return {
            'id': self.id,
            'tour_length_seconds': self.tour_length_seconds,
            'timer_paused': self.timer_paused,
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'time_remaining_on_pause': self.time_remaining_on_pause,
        }
