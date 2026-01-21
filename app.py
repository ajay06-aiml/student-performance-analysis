"""
Student Performance Analysis - Flask Web Application
====================================================

INSTALLATION:
1. Install Python 3.7+ if not already installed
2. Install dependencies: pip install -r requirements.txt
3. Ensure Students_Performance_Dataset.csv is in the /data folder

HOW TO RUN:
1. Open terminal/command prompt in project root
2. Run: python app.py
3. Open browser and navigate to: http://localhost:5000

DEMO LOGINS:
- Admin: username=admin1, password=admin123, role=admin
- Teacher: username=teacher1, password=teacher123, role=teacher
- Student: username=student1, password=student123, role=student
- Additional students: student2, student3, etc. (all use password: student123)

NOTES:
- Database (app.db) will be auto-created in /db folder on first run
- CSV data will be imported automatically on first run
- If database exists, CSV will NOT be re-imported (to avoid duplicates)
- Set FORCE_REIMPORT=1 environment variable to force re-import
- Database migrations run automatically on startup
"""

import os
import sqlite3
import pandas as pd
import re
import json
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_file, flash
from werkzeug.utils import secure_filename
import io
import csv
import random

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-in-production-2024'

# Configuration
DB_PATH = os.path.join('db', 'app.db')
# Check CSV in both project root and /data folder
CSV_PATH = None
if os.path.exists('Students_Performance_Dataset.csv'):
    CSV_PATH = 'Students_Performance_Dataset.csv'
elif os.path.exists(os.path.join('data', 'Students_Performance_Dataset.csv')):
    CSV_PATH = os.path.join('data', 'Students_Performance_Dataset.csv')
FORCE_REIMPORT = os.environ.get('FORCE_REIMPORT', '0') == '1'
UPLOAD_FOLDER_STUDENTS = os.path.join('static', 'uploads', 'students')
UPLOAD_FOLDER_TEACHERS = os.path.join('static', 'uploads', 'teachers')
MAX_UPLOAD_SIZE = 2 * 1024 * 1024  # 2MB
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}

# Create uploads folders
os.makedirs(UPLOAD_FOLDER_STUDENTS, exist_ok=True)
os.makedirs(UPLOAD_FOLDER_TEACHERS, exist_ok=True)

# Fixed seed for reproducibility
random.seed(42)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Standardize column names (convert to snake_case)
def standardize_column_name(col):
    """Convert column names to snake_case, handling spaces and slashes"""
    col = re.sub(r'[/\s]+', '_', col)
    col = col.lower()
    col = re.sub(r'[^a-z0-9_]', '', col)
    col = re.sub(r'_+', '_', col)
    col = col.strip('_')
    return col

def get_db_connection():
    """Get database connection"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def run_migrations():
    """Run database migrations to add new tables and columns"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Create teacher_section_map table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS teacher_section_map (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                teacher_user_id INTEGER NOT NULL,
                grade_level INTEGER NOT NULL,
                section TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                UNIQUE(grade_level, section),
                FOREIGN KEY (teacher_user_id) REFERENCES users(id)
            )
        ''')
        
        # Check and add columns to users table
        cursor.execute("PRAGMA table_info(users)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'is_active' not in columns:
            cursor.execute('ALTER TABLE users ADD COLUMN is_active INTEGER DEFAULT 1')
        if 'photo_filename' not in columns:
            cursor.execute('ALTER TABLE users ADD COLUMN photo_filename TEXT')
        
        # Check and add columns to students table
        cursor.execute("PRAGMA table_info(students)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'photo_filename' not in columns:
            cursor.execute('ALTER TABLE students ADD COLUMN photo_filename TEXT')
        
        conn.commit()
        print("Database migrations completed successfully.")
    except Exception as e:
        print(f"Migration error: {str(e)}")
        conn.rollback()
    finally:
        conn.close()

def get_teacher_assignment(user_id):
    """Get teacher's assigned grade and section from teacher_section_map"""
    conn = get_db_connection()
    mapping = conn.execute(
        '''SELECT grade_level, section FROM teacher_section_map 
           WHERE teacher_user_id = ? AND is_active = 1''',
        (user_id,)
    ).fetchone()
    conn.close()
    
    if mapping:
        return mapping['grade_level'], mapping['section']
    return None, None

def check_teacher_access(student_grade, student_section, user_id):
    """Check if teacher has access to this student"""
    if session.get('role') == 'admin':
        return True
    if session.get('role') != 'teacher':
        return False
    
    teacher_grade, teacher_section = get_teacher_assignment(user_id)
    if not teacher_grade or not teacher_section:
        return False
    
    return teacher_grade == student_grade and teacher_section == student_section

def get_next_student_id():
    """Get next sequential student ID"""
    conn = get_db_connection()
    result = conn.execute(
        'SELECT student_id FROM students ORDER BY student_id DESC LIMIT 1'
    ).fetchone()
    conn.close()
    
    if result:
        last_id = result['student_id']
        if last_id and last_id.startswith('S'):
            try:
                num = int(last_id[1:])
                return f'S{num+1:04d}'
            except:
                pass
    
    return 'S0001'

def init_database():
    """Initialize database and import CSV data"""
    db_exists = os.path.exists(DB_PATH)
    
    if db_exists and not FORCE_REIMPORT:
        print("Database exists. Skipping import. Set FORCE_REIMPORT=1 to re-import.")
        run_migrations()
        seed_default_data()
        return
    
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Create users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL,
            student_id TEXT,
            is_active INTEGER DEFAULT 1,
            photo_filename TEXT
        )
    ''')
    
    # Create teacher_section_map table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS teacher_section_map (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            teacher_user_id INTEGER NOT NULL,
            grade_level INTEGER NOT NULL,
            section TEXT NOT NULL,
            is_active INTEGER DEFAULT 1,
            UNIQUE(grade_level, section),
            FOREIGN KEY (teacher_user_id) REFERENCES users(id)
        )
    ''')
    
    # Create students table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS students (
            student_id TEXT PRIMARY KEY,
            student_name TEXT,
            grade_level INTEGER,
            section TEXT,
            gender TEXT,
            race_ethnicity TEXT,
            parental_education TEXT,
            lunch TEXT,
            test_prep TEXT,
            attendance_percent REAL,
            days_present INTEGER,
            days_absent INTEGER,
            total_days INTEGER,
            math_unit_test_score REAL,
            math_midterm_score REAL,
            math_final_score REAL,
            reading_unit_test_score REAL,
            reading_midterm_score REAL,
            reading_final_score REAL,
            writing_unit_test_score REAL,
            writing_midterm_score REAL,
            writing_final_score REAL,
            science_unit_test_score REAL,
            science_midterm_score REAL,
            science_final_score REAL,
            social_science_unit_test_score REAL,
            social_science_midterm_score REAL,
            social_science_final_score REAL,
            computer_science_unit_test_score REAL,
            computer_science_midterm_score REAL,
            computer_science_final_score REAL,
            final_total_score REAL,
            final_average_score REAL,
            final_performance_level TEXT,
            photo_filename TEXT
        )
    ''')
    
    # Import CSV data
    if not CSV_PATH or not os.path.exists(CSV_PATH):
        print(f"ERROR: CSV file not found. Please ensure Students_Performance_Dataset.csv exists in project root or /data folder.")
        conn.close()
        return
    
    try:
        df = pd.read_csv(CSV_PATH)
        df.columns = [standardize_column_name(col) for col in df.columns]
        
        name_list = [
            'Aarav Singh', 'Kavya Khan', 'Avni Mehta', 'Priya Ahuja', 'Ananya Jain',
            'Rahul Verma', 'Aarav Gupta', 'Ishaan Khan', 'Saanvi Roy', 'Aarav Ahuja',
            'Ishaan Ahuja', 'Rahul Khan', 'Riya Jain', 'Krishna Sharma', 'Yash Nair',
            'Siddharth Kulkarni', 'Neha Singh', 'Avni Reddy', 'Yash Das', 'Arjun Gupta',
            'Pooja Mehta', 'Nikhil Chatterjee', 'Vikram Singh', 'Simran Verma', 'Tanvi Bose',
            'Sakshi Mehta', 'Naina Joshi', 'Ananya Ahuja', 'Meera Roy', 'Harsh Chatterjee',
            'Shreya Reddy', 'Siddharth Gupta', 'Aditi Khan', 'Yash Patel', 'Ananya Khan',
            'Ira Mehta', 'Pooja Singh', 'Riya Chatterjee', 'Diya Chatterjee', 'Nikhil Reddy',
            'Priya Singh', 'Siddharth Gupta T.', 'Zara Nair', 'Sakshi Khan', 'Diya Bose',
            'Pooja Singh U.', 'Siddharth Ahuja', 'Kavya Das', 'Zara Mehta'
        ]
        
        students_data = []
        student_ids_seen = set()
        
        for idx, row in df.iterrows():
            student_id = str(row.get('student_id', f'S{idx+1:04d}')).strip()
            if not student_id or student_id == 'nan':
                student_id = f'S{idx+1:04d}'
            if student_id in student_ids_seen:
                student_id = f'S{idx+1:04d}'
            student_ids_seen.add(student_id)
            
            student_name = str(row.get('student_name', '')).strip()
            if not student_name or student_name == 'nan':
                student_name = name_list[idx % len(name_list)]
            
            grade_level = row.get('grade_level', None)
            if pd.isna(grade_level):
                grade_level = random.randint(9, 12)
            else:
                grade_level = int(grade_level)
            
            section = str(row.get('section', '')).strip()
            if not section or section == 'nan':
                section = random.choice(['A', 'B', 'C', 'D'])
            
            gender = str(row.get('gender', '')).strip()
            if not gender or gender == 'nan':
                gender = random.choice(['male', 'female'])
            
            race_ethnicity = str(row.get('race_ethnicity', row.get('raceethnicity', ''))).strip()
            if not race_ethnicity or race_ethnicity == 'nan':
                race_ethnicity = random.choice(['group A', 'group B', 'group C', 'group D', 'group E'])
            
            parental_education = str(row.get('parental_education', row.get('parentallevelofeducation', ''))).strip()
            if not parental_education or parental_education == 'nan':
                parental_education = random.choice(['high school', 'some high school', 'some college', 
                                                   "associate's degree", "bachelor's degree", "master's degree"])
            
            lunch = str(row.get('lunch', '')).strip()
            if not lunch or lunch == 'nan':
                lunch = random.choice(['standard', 'free/reduced'])
            
            test_prep = str(row.get('test_prep', row.get('testpreparationcourse', ''))).strip()
            if not test_prep or test_prep == 'nan':
                test_prep = random.choice(['none', 'completed'])
            
            attendance_percent = row.get('attendance_percent', None)
            if pd.isna(attendance_percent):
                attendance_percent = round(random.uniform(60, 100), 2)
            else:
                attendance_percent = float(attendance_percent)
            
            total_days = row.get('total_days', None)
            if pd.isna(total_days):
                total_days = 200
            else:
                total_days = int(total_days)
            
            days_present = int((attendance_percent / 100) * total_days)
            days_absent = total_days - days_present
            
            math_base = row.get('math_score', row.get('mathscore', None))
            reading_base = row.get('reading_score', row.get('readingscore', None))
            writing_base = row.get('writing_score', row.get('writingscore', None))
            science_base = row.get('science_score', row.get('sciencescore', None))
            social_science_base = row.get('social_science_score', row.get('socialsciencescore', None))
            computer_science_base = row.get('computer_science_score', row.get('computersciencescore', None))
            
            subjects = {
                'math': math_base,
                'reading': reading_base,
                'writing': writing_base,
                'science': science_base,
                'social_science': social_science_base,
                'computer_science': computer_science_base
            }
            
            exam_scores = {}
            for subject, base_score in subjects.items():
                if pd.isna(base_score) or base_score is None:
                    base_score = random.randint(30, 100)
                
                base_score = float(base_score)
                
                for exam in ['unit_test', 'midterm', 'final']:
                    col_name = f'{subject}_{exam}_score'
                    existing_score = row.get(col_name, None)
                    
                    if pd.isna(existing_score) or existing_score is None:
                        noise = random.uniform(-10, 10)
                        score = max(0, min(100, base_score + noise))
                        exam_scores[col_name] = round(score, 2)
                    else:
                        exam_scores[col_name] = float(existing_score)
            
            final_scores = [
                exam_scores.get('math_final_score', 0),
                exam_scores.get('reading_final_score', 0),
                exam_scores.get('writing_final_score', 0),
                exam_scores.get('science_final_score', 0),
                exam_scores.get('social_science_final_score', 0),
                exam_scores.get('computer_science_final_score', 0)
            ]
            
            final_total_score = sum(final_scores)
            final_average_score = final_total_score / len(final_scores) if final_scores else 0
            
            if final_average_score >= 80:
                final_performance_level = 'Excellent'
            elif final_average_score >= 65:
                final_performance_level = 'Good'
            elif final_average_score >= 50:
                final_performance_level = 'Average'
            else:
                final_performance_level = 'Needs Improvement'
            
            student_record = {
                'student_id': student_id,
                'student_name': student_name,
                'grade_level': grade_level,
                'section': section,
                'gender': gender,
                'race_ethnicity': race_ethnicity,
                'parental_education': parental_education,
                'lunch': lunch,
                'test_prep': test_prep,
                'attendance_percent': attendance_percent,
                'days_present': days_present,
                'days_absent': days_absent,
                'total_days': total_days,
                **exam_scores,
                'final_total_score': round(final_total_score, 2),
                'final_average_score': round(final_average_score, 2),
                'final_performance_level': final_performance_level,
                'photo_filename': None
            }
            
            students_data.append(student_record)
        
        if students_data:
            if FORCE_REIMPORT:
                cursor.execute('DELETE FROM students')
            
            for student in students_data:
                placeholders = ', '.join(['?' for _ in student])
                columns = ', '.join(student.keys())
                values = list(student.values())
                cursor.execute(f'INSERT OR REPLACE INTO students ({columns}) VALUES ({placeholders})', values)
        
        conn.commit()
        print(f"Successfully imported {len(students_data)} students.")
    
    except Exception as e:
        print(f"Error importing CSV: {str(e)}")
        import traceback
        traceback.print_exc()
    
    finally:
        conn.close()
    
    # Seed default data
    seed_default_data()

def seed_default_data():
    """Seed default users and teacher assignments"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Create default admin
        cursor.execute('''
            INSERT OR IGNORE INTO users (username, password, role, is_active)
            VALUES (?, ?, ?, ?)
        ''', ('admin1', 'admin123', 'admin', 1))
        
        # Create default teacher
        cursor.execute('''
            INSERT OR IGNORE INTO users (username, password, role, is_active)
            VALUES (?, ?, ?, ?)
        ''', ('teacher1', 'teacher123', 'teacher', 1))
        
        # Get teacher1 user_id
        teacher1 = cursor.execute('SELECT id FROM users WHERE username = ?', ('teacher1',)).fetchone()
        
        # Create default student accounts (first 5)
        students = cursor.execute('SELECT student_id FROM students LIMIT 5').fetchall()
        for i, student_row in enumerate(students, 1):
            student_id = student_row['student_id']
            cursor.execute('''
                INSERT OR IGNORE INTO users (username, password, role, student_id, is_active)
                VALUES (?, ?, ?, ?, ?)
            ''', (f'student{i}', 'student123', 'student', student_id, 1))
        
        # Assign teacher1 to Grade 9 Section A if no mapping exists
        if teacher1:
            existing = cursor.execute(
                'SELECT id FROM teacher_section_map WHERE teacher_user_id = ?',
                (teacher1['id'],)
            ).fetchone()
            
            if not existing:
                # Check if Grade 9 Section A is already assigned
                section_taken = cursor.execute(
                    'SELECT id FROM teacher_section_map WHERE grade_level = ? AND section = ?',
                    (9, 'A')
                ).fetchone()
                
                if not section_taken:
                    cursor.execute('''
                        INSERT INTO teacher_section_map (teacher_user_id, grade_level, section, is_active)
                        VALUES (?, ?, ?, ?)
                    ''', (teacher1['id'], 9, 'A', 1))
        
        conn.commit()
        print("Default data seeded successfully.")
    except Exception as e:
        print(f"Error seeding data: {str(e)}")
        conn.rollback()
    finally:
        conn.close()

# Decorators
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        conn = get_db_connection()
        user = conn.execute('SELECT is_active FROM users WHERE id = ?', (session['user_id'],)).fetchone()
        conn.close()
        if not user or not user['is_active']:
            session.clear()
            flash('Your account has been deactivated.', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def role_required(role):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                return redirect(url_for('login'))
            if session.get('role') != role:
                flash('Access denied.', 'error')
                return redirect(url_for('login'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# Routes
@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        role = request.form.get('role')
        
        conn = get_db_connection()
        user = conn.execute(
            'SELECT * FROM users WHERE username = ? AND password = ? AND role = ? AND is_active = 1',
            (username, password, role)
        ).fetchone()
        conn.close()
        
        if user:
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            session['student_id'] = user['student_id']
            
            if role == 'student':
                return redirect(url_for('student_dashboard'))
            elif role == 'teacher':
                return redirect(url_for('teacher_dashboard'))
            elif role == 'admin':
                return redirect(url_for('admin_dashboard'))
        else:
            flash('Invalid credentials', 'error')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/student')
@login_required
@role_required('student')
def student_dashboard():
    student_id = session.get('student_id')
    if not student_id:
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    student = conn.execute(
        'SELECT * FROM students WHERE student_id = ?',
        (student_id,)
    ).fetchone()
    conn.close()
    
    if not student:
        return render_template('student_dashboard.html', error='Student record not found')
    
    student_dict = dict(student)
    return render_template('student_dashboard.html', student=student_dict)

@app.route('/teacher')
@login_required
@role_required('teacher')
def teacher_dashboard():
    user_id = session.get('user_id')
    teacher_grade, teacher_section = get_teacher_assignment(user_id)
    
    # Get teacher photo
    conn = get_db_connection()
    teacher = conn.execute('SELECT photo_filename FROM users WHERE id = ?', (user_id,)).fetchone()
    teacher_photo = teacher['photo_filename'] if teacher else None
    conn.close()
    
    if not teacher_grade or not teacher_section:
        return render_template('teacher_dashboard.html',
                             students=[],
                             total_students=0,
                             overall_avg=0,
                             pass_rate=0,
                             at_risk_count=0,
                             unique_genders=[],
                             unique_performance=[],
                             unique_test_prep=[],
                             current_filters={},
                             no_assignment=True,
                             teacher_grade=None,
                             teacher_section=None,
                             teacher_photo=teacher_photo,
                             subject_avg_scores={},
                             performance_dist={},
                             attendance_data=[],
                             exam_avg={'unit_test': 0, 'midterm': 0, 'final': 0})
    
    # Get filter parameters
    gender = request.args.get('gender', '')
    performance_level = request.args.get('performance_level', '')
    test_prep = request.args.get('test_prep', '')
    attendance_min = request.args.get('attendance_min', '')
    attendance_max = request.args.get('attendance_max', '')
    
    conn = get_db_connection()
    
    # Build query - ALWAYS filter by teacher's assignment
    query = 'SELECT * FROM students WHERE grade_level = ? AND section = ?'
    params = [teacher_grade, teacher_section]
    
    if gender:
        query += ' AND gender = ?'
        params.append(gender)
    if performance_level:
        query += ' AND final_performance_level = ?'
        params.append(performance_level)
    if test_prep:
        query += ' AND test_prep = ?'
        params.append(test_prep)
    if attendance_min:
        query += ' AND attendance_percent >= ?'
        params.append(float(attendance_min))
    if attendance_max:
        query += ' AND attendance_percent <= ?'
        params.append(float(attendance_max))
    
    students = conn.execute(query, params).fetchall()
    
    # Calculate KPIs
    total_students = len(students)
    if total_students > 0:
        final_avg_sum = sum([float(s['final_average_score']) for s in students])
        overall_avg = final_avg_sum / total_students
        
        pass_count = sum([1 for s in students if float(s['final_average_score']) >= 50])
        pass_rate = (pass_count / total_students) * 100
        
        at_risk_count = sum([1 for s in students 
                           if float(s['final_average_score']) < 50 or float(s['attendance_percent']) < 75])
    else:
        overall_avg = 0
        pass_rate = 0
        at_risk_count = 0
    
    # Get unique values for filters
    section_students = conn.execute(
        'SELECT * FROM students WHERE grade_level = ? AND section = ?',
        (teacher_grade, teacher_section)
    ).fetchall()
    unique_genders = sorted(set([s['gender'] for s in section_students]))
    unique_performance = sorted(set([s['final_performance_level'] for s in section_students]))
    unique_test_prep = sorted(set([s['test_prep'] for s in section_students]))
    
    conn.close()
    
    # Prepare graph data
    subjects = ['math', 'reading', 'writing', 'science', 'social_science', 'computer_science']
    subject_avg_scores = {}
    for subject in subjects:
        scores = [float(s[f'{subject}_final_score']) for s in students if s[f'{subject}_final_score']]
        subject_avg_scores[subject] = sum(scores) / len(scores) if scores else 0
    
    performance_dist = {}
    for s in students:
        level = s['final_performance_level']
        performance_dist[level] = performance_dist.get(level, 0) + 1
    
    attendance_data = [(float(s['attendance_percent']), float(s['final_average_score'])) for s in students]
    
    # Exam progression data
    exam_avg = {}
    for exam in ['unit_test', 'midterm', 'final']:
        scores = []
        for subject in subjects:
            for s in students:
                score = s[f'{subject}_{exam}_score']
                if score is not None:
                    scores.append(float(score))
        exam_avg[exam] = sum(scores) / len(scores) if scores else 0
    
    return render_template('teacher_dashboard.html',
                         students=students,
                         total_students=total_students,
                         overall_avg=round(overall_avg, 2),
                         pass_rate=round(pass_rate, 2),
                         at_risk_count=at_risk_count,
                         unique_genders=unique_genders,
                         unique_performance=unique_performance,
                         unique_test_prep=unique_test_prep,
                         current_filters={
                             'gender': gender,
                             'performance_level': performance_level,
                             'test_prep': test_prep,
                             'attendance_min': attendance_min,
                             'attendance_max': attendance_max
                         },
                         no_assignment=False,
                         teacher_grade=teacher_grade,
                         teacher_section=teacher_section,
                         teacher_photo=teacher_photo,
                         subject_avg_scores=subject_avg_scores,
                         performance_dist=performance_dist,
                         attendance_data=attendance_data,
                         exam_avg=exam_avg)

@app.route('/teacher/add_student', methods=['GET', 'POST'])
@login_required
@role_required('teacher')
def teacher_add_student():
    user_id = session.get('user_id')
    teacher_grade, teacher_section = get_teacher_assignment(user_id)
    
    if not teacher_grade or not teacher_section:
        flash('You must be assigned to a grade and section to add students.', 'error')
        return redirect(url_for('teacher_dashboard'))
    
    if request.method == 'POST':
        # Check capacity (60 students max per grade+section)
        conn = get_db_connection()
        count = conn.execute(
            'SELECT COUNT(*) as cnt FROM students WHERE grade_level = ? AND section = ?',
            (teacher_grade, teacher_section)
        ).fetchone()
        
        if count['cnt'] >= 60:
            flash('Section capacity limit reached (60 students). Cannot add more students.', 'error')
            conn.close()
            return render_template('teacher_add_student.html', 
                                 teacher_grade=teacher_grade, 
                                 teacher_section=teacher_section)
        
        student_name = request.form.get('student_name', '').strip()
        gender = request.form.get('gender', '')
        race_ethnicity = request.form.get('race_ethnicity', '')
        parental_education = request.form.get('parental_education', '')
        lunch = request.form.get('lunch', '')
        test_prep = request.form.get('test_prep', '')
        attendance_percent = float(request.form.get('attendance_percent', 100))
        
        if not student_name:
            flash('Student name is required.', 'error')
            conn.close()
            return render_template('teacher_add_student.html',
                                 teacher_grade=teacher_grade,
                                 teacher_section=teacher_section)
        
        student_id = get_next_student_id()
        total_days = 200
        days_present = int((attendance_percent / 100) * total_days)
        days_absent = total_days - days_present
        
        # Generate default exam scores
        subjects = ['math', 'reading', 'writing', 'science', 'social_science', 'computer_science']
        exam_scores = {}
        for subject in subjects:
            for exam in ['unit_test', 'midterm', 'final']:
                score = round(random.uniform(50, 90), 2)
                exam_scores[f'{subject}_{exam}_score'] = score
        
        final_scores = [exam_scores.get(f'{s}_final_score', 0) for s in subjects]
        final_total_score = sum(final_scores)
        final_average_score = final_total_score / len(final_scores)
        
        if final_average_score >= 80:
            final_performance_level = 'Excellent'
        elif final_average_score >= 65:
            final_performance_level = 'Good'
        elif final_average_score >= 50:
            final_performance_level = 'Average'
        else:
            final_performance_level = 'Needs Improvement'
        
        try:
            cursor = conn.cursor()
            columns = ['student_id', 'student_name', 'grade_level', 'section', 'gender',
                      'race_ethnicity', 'parental_education', 'lunch', 'test_prep',
                      'attendance_percent', 'days_present', 'days_absent', 'total_days',
                      'final_total_score', 'final_average_score', 'final_performance_level']
            columns.extend(exam_scores.keys())
            
            placeholders = ', '.join(['?' for _ in columns])
            columns_str = ', '.join(columns)
            values = [student_id, student_name, teacher_grade, teacher_section, gender,
                     race_ethnicity, parental_education, lunch, test_prep,
                     attendance_percent, days_present, days_absent, total_days,
                     final_total_score, final_average_score, final_performance_level]
            values.extend([exam_scores[k] for k in exam_scores.keys()])
            
            cursor.execute(f'INSERT INTO students ({columns_str}) VALUES ({placeholders})', values)
            conn.commit()
            flash(f'Student {student_name} added successfully!', 'success')
            conn.close()
            return redirect(url_for('teacher_dashboard'))
        except Exception as e:
            conn.rollback()
            conn.close()
            flash(f'Error adding student: {str(e)}', 'error')
    
    return render_template('teacher_add_student.html',
                         teacher_grade=teacher_grade,
                         teacher_section=teacher_section)

@app.route('/teacher/student/<student_id>')
@login_required
@role_required('teacher')
def teacher_student_detail(student_id):
    conn = get_db_connection()
    student = conn.execute(
        'SELECT * FROM students WHERE student_id = ?',
        (student_id,)
    ).fetchone()
    conn.close()
    
    if not student:
        flash('Student not found.', 'error')
        return redirect(url_for('teacher_dashboard'))
    
    # Check access
    if not check_teacher_access(student['grade_level'], student['section'], session.get('user_id')):
        flash('Access denied. You can only view students from your assigned section.', 'error')
        return redirect(url_for('teacher_dashboard'))
    
    student_dict = dict(student)
    
    # Prepare graph data
    subjects = ['math', 'reading', 'writing', 'science', 'social_science', 'computer_science']
    subject_scores = {}
    for subject in subjects:
        subject_scores[subject] = {
            'unit_test': float(student_dict.get(f'{subject}_unit_test_score', 0)),
            'midterm': float(student_dict.get(f'{subject}_midterm_score', 0)),
            'final': float(student_dict.get(f'{subject}_final_score', 0))
        }
    
    final_scores = {s: float(student_dict.get(f'{s}_final_score', 0)) for s in subjects}
    
    # Calculate insights
    weak_subjects = []
    for subject in subjects:
        score = float(student_dict.get(f'{subject}_final_score', 0))
        if score < 50:
            weak_subjects.append(subject.replace('_', ' ').title())
    
    attendance_warning = float(student_dict.get('attendance_percent', 0)) < 75
    
    # Exam progression averages
    exam_progression = {}
    for exam in ['unit_test', 'midterm', 'final']:
        scores = [float(student_dict.get(f'{s}_{exam}_score', 0)) for s in subjects]
        exam_progression[exam] = sum(scores) / len(scores) if scores else 0
    
    return render_template('teacher_student_detail.html', 
                         student=student_dict,
                         subject_scores=subject_scores,
                         final_scores=final_scores,
                         weak_subjects=weak_subjects,
                         attendance_warning=attendance_warning,
                         exam_progression=exam_progression)

@app.route('/upload_student_photo/<student_id>', methods=['POST'])
@login_required
def upload_student_photo(student_id):
    if 'file' not in request.files:
        flash('No file selected.', 'error')
        return redirect(request.referrer or url_for('teacher_dashboard'))
    
    file = request.files['file']
    if file.filename == '':
        flash('No file selected.', 'error')
        return redirect(request.referrer or url_for('teacher_dashboard'))
    
    # Check access
    conn = get_db_connection()
    student = conn.execute('SELECT * FROM students WHERE student_id = ?', (student_id,)).fetchone()
    conn.close()
    
    if not student:
        flash('Student not found.', 'error')
        return redirect(request.referrer or url_for('teacher_dashboard'))
    
    role = session.get('role')
    if role == 'admin':
        pass
    elif role == 'teacher':
        if not check_teacher_access(student['grade_level'], student['section'], session.get('user_id')):
            flash('Access denied.', 'error')
            return redirect(request.referrer or url_for('teacher_dashboard'))
    else:
        flash('Access denied.', 'error')
        return redirect(request.referrer or url_for('login'))
    
    if file and allowed_file(file.filename):
        # Check file size
        file.seek(0, os.SEEK_END)
        file_size = file.tell()
        file.seek(0)
        
        if file_size > MAX_UPLOAD_SIZE:
            flash('File size exceeds 2MB limit.', 'error')
            return redirect(request.referrer or url_for('teacher_dashboard'))
        
        filename = secure_filename(f'{student_id}_{file.filename}')
        filepath = os.path.join(UPLOAD_FOLDER_STUDENTS, filename)
        file.save(filepath)
        
        # Update database
        conn = get_db_connection()
        conn.execute(
            'UPDATE students SET photo_filename = ? WHERE student_id = ?',
            (filename, student_id)
        )
        conn.commit()
        conn.close()
        
        flash('Photo uploaded successfully!', 'success')
    else:
        flash('Invalid file type. Only JPG, JPEG, and PNG are allowed.', 'error')
    
    return redirect(request.referrer or url_for('teacher_dashboard'))

@app.route('/upload_teacher_photo', methods=['POST'])
@login_required
def upload_teacher_photo():
    """Upload photo for current teacher"""
    if session.get('role') not in ['teacher', 'admin']:
        flash('Access denied.', 'error')
        return redirect(url_for('login'))
    
    if 'file' not in request.files:
        flash('No file selected.', 'error')
        return redirect(request.referrer or url_for('teacher_dashboard'))
    
    file = request.files['file']
    if file.filename == '':
        flash('No file selected.', 'error')
        return redirect(request.referrer or url_for('teacher_dashboard'))
    
    user_id = session.get('user_id')
    
    if file and allowed_file(file.filename):
        file.seek(0, os.SEEK_END)
        file_size = file.tell()
        file.seek(0)
        
        if file_size > MAX_UPLOAD_SIZE:
            flash('File size exceeds 2MB limit.', 'error')
            return redirect(request.referrer or url_for('teacher_dashboard'))
        
        filename = secure_filename(f'teacher_{user_id}_{file.filename}')
        filepath = os.path.join(UPLOAD_FOLDER_TEACHERS, filename)
        file.save(filepath)
        
        # Update database
        conn = get_db_connection()
        conn.execute(
            'UPDATE users SET photo_filename = ? WHERE id = ?',
            (filename, user_id)
        )
        conn.commit()
        conn.close()
        
        flash('Photo uploaded successfully!', 'success')
    else:
        flash('Invalid file type. Only JPG, JPEG, and PNG are allowed.', 'error')
    
    return redirect(request.referrer or url_for('teacher_dashboard'))

@app.route('/admin/upload_teacher_photo/<int:teacher_user_id>', methods=['POST'])
@login_required
@role_required('admin')
def admin_upload_teacher_photo(teacher_user_id):
    """Admin upload photo for any teacher"""
    if 'file' not in request.files:
        flash('No file selected.', 'error')
        return redirect(request.referrer or url_for('admin_teachers'))
    
    file = request.files['file']
    if file.filename == '':
        flash('No file selected.', 'error')
        return redirect(request.referrer or url_for('admin_teachers'))
    
    if file and allowed_file(file.filename):
        file.seek(0, os.SEEK_END)
        file_size = file.tell()
        file.seek(0)
        
        if file_size > MAX_UPLOAD_SIZE:
            flash('File size exceeds 2MB limit.', 'error')
            return redirect(request.referrer or url_for('admin_teachers'))
        
        filename = secure_filename(f'teacher_{teacher_user_id}_{file.filename}')
        filepath = os.path.join(UPLOAD_FOLDER_TEACHERS, filename)
        file.save(filepath)
        
        # Update database
        conn = get_db_connection()
        conn.execute(
            'UPDATE users SET photo_filename = ? WHERE id = ?',
            (filename, teacher_user_id)
        )
        conn.commit()
        conn.close()
        
        flash('Photo uploaded successfully!', 'success')
    else:
        flash('Invalid file type. Only JPG, JPEG, and PNG are allowed.', 'error')
    
    return redirect(request.referrer or url_for('admin_teachers'))

@app.route('/admin')
@login_required
@role_required('admin')
def admin_dashboard():
    return render_template('admin_dashboard.html')

@app.route('/admin/students')
@login_required
@role_required('admin')
def admin_students():
    # Get filter parameters
    grade_level = request.args.get('grade_level', '')
    section = request.args.get('section', '')
    gender = request.args.get('gender', '')
    performance_level = request.args.get('performance_level', '')
    
    conn = get_db_connection()
    
    # Build query
    query = 'SELECT * FROM students WHERE 1=1'
    params = []
    
    if grade_level:
        query += ' AND grade_level = ?'
        params.append(int(grade_level))
    if section:
        query += ' AND section = ?'
        params.append(section)
    if gender:
        query += ' AND gender = ?'
        params.append(gender)
    if performance_level:
        query += ' AND final_performance_level = ?'
        params.append(performance_level)
    
    students = conn.execute(query, params).fetchall()
    
    # Get unique values for filters
    all_students = conn.execute('SELECT * FROM students').fetchall()
    unique_grades = sorted(set([s['grade_level'] for s in all_students]))
    unique_sections = sorted(set([s['section'] for s in all_students]))
    unique_genders = sorted(set([s['gender'] for s in all_students]))
    unique_performance = sorted(set([s['final_performance_level'] for s in all_students]))
    
    conn.close()
    
    return render_template('admin_students.html',
                         students=students,
                         unique_grades=unique_grades,
                         unique_sections=unique_sections,
                         unique_genders=unique_genders,
                         unique_performance=unique_performance,
                         current_filters={
                             'grade_level': grade_level,
                             'section': section,
                             'gender': gender,
                             'performance_level': performance_level
                         })

@app.route('/admin/teachers')
@login_required
@role_required('admin')
def admin_teachers():
    conn = get_db_connection()
    teachers = conn.execute('''
        SELECT u.id, u.username, u.photo_filename, u.is_active,
               tsm.grade_level, tsm.section
        FROM users u
        LEFT JOIN teacher_section_map tsm ON u.id = tsm.teacher_user_id AND tsm.is_active = 1
        WHERE u.role = 'teacher'
        ORDER BY u.username
    ''').fetchall()
    conn.close()
    
    return render_template('admin_teachers.html', teachers=teachers)

@app.route('/admin/add_teacher', methods=['POST'])
@login_required
@role_required('admin')
def admin_add_teacher():
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    assigned_grade_level = request.form.get('assigned_grade_level', '')
    assigned_section = request.form.get('assigned_section', '').strip()
    
    if not username or not password:
        flash('Username and password are required.', 'error')
        return redirect(url_for('admin_teachers'))
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Create teacher user
        cursor.execute('''
            INSERT INTO users (username, password, role, is_active)
            VALUES (?, ?, ?, ?)
        ''', (username, password, 'teacher', 1))
        
        teacher_user_id = cursor.lastrowid
        
        # Assign to section if provided
        if assigned_grade_level and assigned_section:
            # Check if section is already taken
            existing = cursor.execute(
                'SELECT id FROM teacher_section_map WHERE grade_level = ? AND section = ?',
                (int(assigned_grade_level), assigned_section)
            ).fetchone()
            
            if existing:
                flash(f'Grade {assigned_grade_level} Section {assigned_section} is already assigned to another teacher.', 'error')
            else:
                cursor.execute('''
                    INSERT INTO teacher_section_map (teacher_user_id, grade_level, section, is_active)
                    VALUES (?, ?, ?, ?)
                ''', (teacher_user_id, int(assigned_grade_level), assigned_section, 1))
                flash(f'Teacher {username} added and assigned to Grade {assigned_grade_level} Section {assigned_section}!', 'success')
        else:
            flash(f'Teacher {username} added successfully!', 'success')
        
        conn.commit()
        conn.close()
    except sqlite3.IntegrityError:
        flash('Username already exists.', 'error')
    except Exception as e:
        flash(f'Error adding teacher: {str(e)}', 'error')
    
    return redirect(url_for('admin_teachers'))

@app.route('/admin/assign_teacher', methods=['POST'])
@login_required
@role_required('admin')
def admin_assign_teacher():
    teacher_user_id = int(request.form.get('teacher_user_id'))
    grade_level = int(request.form.get('grade_level'))
    section = request.form.get('section').strip()
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check if section is already taken
        existing = cursor.execute(
            'SELECT id FROM teacher_section_map WHERE grade_level = ? AND section = ? AND is_active = 1',
            (grade_level, section)
        ).fetchone()
        
        if existing:
            flash(f'Grade {grade_level} Section {section} is already assigned to another teacher.', 'error')
        else:
            # Deactivate old mapping if exists
            cursor.execute('''
                UPDATE teacher_section_map SET is_active = 0 
                WHERE teacher_user_id = ?
            ''', (teacher_user_id,))
            
            # Create new mapping
            cursor.execute('''
                INSERT INTO teacher_section_map (teacher_user_id, grade_level, section, is_active)
                VALUES (?, ?, ?, ?)
            ''', (teacher_user_id, grade_level, section, 1))
            
            conn.commit()
            flash('Teacher assigned successfully!', 'success')
        
        conn.close()
    except Exception as e:
        flash(f'Error assigning teacher: {str(e)}', 'error')
    
    return redirect(url_for('admin_teachers'))

@app.route('/admin/toggle_teacher/<int:teacher_id>')
@login_required
@role_required('admin')
def toggle_teacher(teacher_id):
    conn = get_db_connection()
    teacher = conn.execute('SELECT is_active FROM users WHERE id = ?', (teacher_id,)).fetchone()
    if teacher:
        new_status = 0 if teacher['is_active'] else 1
        conn.execute('UPDATE users SET is_active = ? WHERE id = ?', (new_status, teacher_id))
        conn.commit()
        flash('Teacher status updated.', 'success')
    conn.close()
    return redirect(url_for('admin_teachers'))

@app.route('/export')
@login_required
def export_students():
    role = session.get('role')
    
    if role == 'admin':
        conn = get_db_connection()
        students = conn.execute('SELECT * FROM students').fetchall()
        conn.close()
    elif role == 'teacher':
        user_id = session.get('user_id')
        teacher_grade, teacher_section = get_teacher_assignment(user_id)
        if not teacher_grade or not teacher_section:
            flash('You must be assigned to a grade and section.', 'error')
            return redirect(url_for('teacher_dashboard'))
        
        conn = get_db_connection()
        students = conn.execute(
            'SELECT * FROM students WHERE grade_level = ? AND section = ?',
            (teacher_grade, teacher_section)
        ).fetchall()
        conn.close()
    else:
        flash('Access denied.', 'error')
        return redirect(url_for('login'))
    
    output = io.StringIO()
    if students:
        fieldnames = ['student_id', 'student_name', 'grade_level', 'section', 'gender',
                     'attendance_percent', 'final_average_score', 'final_performance_level']
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for student in students:
            writer.writerow({
                'student_id': student['student_id'],
                'student_name': student['student_name'],
                'grade_level': student['grade_level'],
                'section': student['section'],
                'gender': student['gender'],
                'attendance_percent': student['attendance_percent'],
                'final_average_score': student['final_average_score'],
                'final_performance_level': student['final_performance_level']
            })
    
    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8')),
        mimetype='text/csv',
        as_attachment=True,
        download_name='students_export.csv'
    )

if __name__ == '__main__':
    init_database()
    run_migrations()
    seed_default_data()
    app.run(debug=True, host='0.0.0.0', port=5000)
