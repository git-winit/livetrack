from flask import Flask, render_template, request, redirect, url_for, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import requests
import logging

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///employees.db'
app.config['SECRET_KEY'] = 'your_secret_key'  # Needed for session management
db = SQLAlchemy(app)

class Employee(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)

class WorkSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'), nullable=False)
    clock_in = db.Column(db.DateTime, nullable=False)
    clock_out = db.Column(db.DateTime)
    clock_in_location = db.Column(db.String(100))
    clock_out_location = db.Column(db.String(100))
    total_hours = db.Column(db.Float, default=0.0)
    locations = db.relationship('Location', backref='session', lazy=True)
    breaks = db.relationship('Break', backref='session', lazy=True)

class Break(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('work_session.id'), nullable=False)
    start = db.Column(db.DateTime, nullable=False)
    end = db.Column(db.DateTime)

class Location(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('work_session.id'), nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False)
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    address = db.Column(db.String(255))

def get_address(latitude, longitude):
    try:
        response = requests.get(f'https://nominatim.openstreetmap.org/reverse?format=json&lat={latitude}&lon={longitude}', headers={'User-Agent': 'Mozilla/5.0'})
        response.raise_for_status()  # Raises an HTTPError for bad responses
        data = response.json()
        return data.get('display_name', 'Unknown location')
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching address for {latitude}, {longitude}: {e}")
        return 'Unknown location'
def calculate_total_hours(session):
    if not session.clock_out:
        return 0.0
    total_time = session.clock_out - session.clock_in
    break_time = timedelta(0)
    for br in session.breaks:
        if br.end:
            break_time += br.end - br.start
    worked_time = total_time - break_time
    return round(worked_time.total_seconds() / 3600, 2)

@app.route('/')
def index():
    if 'user_id' in session:
        employee = Employee.query.get(session['user_id'])
        current_time = datetime.now().strftime("%H:%M:%S")
        return render_template('dashboard.html', employee=employee, current_time=current_time)
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        username = request.form['username']
        password = generate_password_hash(request.form['password'])
        new_employee = Employee(name=name, username=username, password=password)
        db.session.add(new_employee)
        db.session.commit()
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        employee = Employee.query.filter_by(username=username).first()
        if employee and check_password_hash(employee.password, password):
            session['user_id'] = employee.id
            return redirect(url_for('index'))
        return 'Invalid credentials'
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('session_id', None)  # Clear session_id on logout
    return redirect(url_for('login'))

@app.route('/clockin', methods=['POST'])
def clockin():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    employee_id = session['user_id']
    latitude, longitude = map(float, request.form['location'].split(','))
    address = get_address(latitude, longitude)
    work_session = WorkSession(employee_id=employee_id, clock_in=datetime.now(), clock_in_location=address)
    db.session.add(work_session)
    db.session.commit()
    session['session_id'] = work_session.id  # Store session ID in the user's session
    return redirect(url_for('index'))

@app.route('/clockout', methods=['POST'])
def clockout():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    session_id = session.pop('session_id', None)  # Get session ID from user's session
    if not session_id:
        return 'No active session'
    latitude, longitude = map(float, request.form['location'].split(','))
    address = get_address(latitude, longitude)
    work_session = WorkSession.query.get(session_id)
    if work_session:
        work_session.clock_out = datetime.now()
        work_session.clock_out_location = address
        work_session.total_hours = calculate_total_hours(work_session)
        db.session.commit()
    return redirect(url_for('index'))

@app.route('/break/start', methods=['POST'])
def start_break():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    session_id = session.get('session_id')
    if not session_id:
        return 'No active session'
    work_break = Break(session_id=session_id, start=datetime.now())
    db.session.add(work_break)
    db.session.commit()
    session['break_id'] = work_break.id  # Store break ID in the user's session
    return redirect(url_for('index'))

@app.route('/break/end', methods=['POST'])
def end_break():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    break_id = session.pop('break_id', None)  # Get break ID from user's session
    if not break_id:
        return 'No active break'
    work_break = Break.query.get(break_id)
    if work_break:
        work_break.end = datetime.now()
        db.session.commit()
    return redirect(url_for('index'))

@app.route('/update_location', methods=['POST'])
def update_location():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    session_id = session.get('session_id')
    if not session_id:
        return 'No active session'
    latitude, longitude = map(float, request.form['location'].split(','))
    address = get_address(latitude, longitude)
    location = Location(session_id=session_id, timestamp=datetime.now(), latitude=latitude, longitude=longitude, address=address)
    db.session.add(location)
    db.session.commit()
    return 'Location updated'

@app.route('/sessions/<int:employee_id>')
def get_sessions(employee_id):
    sessions = WorkSession.query.filter_by(employee_id=employee_id).all()
    return jsonify([{
        'id': session.id,
        'clock_in': session.clock_in,
        'clock_out': session.clock_out,
        'clock_in_location': session.clock_in_location,
        'clock_out_location': session.clock_out_location,
        'total_hours': session.total_hours,
        'breaks': [{'start': br.start, 'end': br.end} for br in session.breaks],
        'locations': [{'timestamp': loc.timestamp, 'latitude': loc.latitude, 'longitude': loc.longitude, 'address': loc.address} for loc in session.locations]
    } for session in sessions])

@app.route('/total_hours/<int:employee_id>')
def total_hours(employee_id):
    sessions = WorkSession.query.filter_by(employee_id=employee_id).all()
    total_hours = sum(calculate_total_hours(session) for session in sessions)
    return jsonify({'total_hours': round(total_hours, 2)})

if __name__ == '__main__':
    db.create_all()
    app.run(debug=True)
