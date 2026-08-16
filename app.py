import os
import json
import time
import re
import sqlite3
import urllib.request
import urllib.error
from functools import wraps
from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash, send_from_directory
from pypdf import PdfReader, PdfWriter
from google import genai
from google.genai import types
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "super-secret-eduvault-key-12345")

# Telegram Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL = os.getenv("TELEGRAM_CHANNEL_USERNAME", "@eduvault12")

# Database Configuration (Supabase PostgreSQL with SQLite fallback)
DATABASE_URL = os.getenv("DATABASE_URL")

# Configure Google's GenAI Client
gemini_key = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=gemini_key) if gemini_key else None
from init_db import init_db

# Server Render irratti yeroo boot ta'u hunda Supabase database fix akka godhuuf:
try:
    init_db()
except Exception as e:
    print(f"Database init error: {e}")

def get_db_connection():
    if DATABASE_URL:
        try:
            import psycopg2
            from psycopg2.extras import RealDictCursor
            return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        except Exception as e:
            print(f"DEBUG: PostgreSQL Connection Failed ({e}). Falling back to SQLite...")
    
    # Local SQLite Fallback
    conn = sqlite3.connect('exams.db')
    conn.row_factory = sqlite3.Row
    return conn

def is_postgres():
    return bool(DATABASE_URL)

# --- Authentication Decorators ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session or session.get('role') != 'admin':
            return jsonify({"error": "Forbidden: Admin access required"}), 403
        return f(*args, **kwargs)
    return decorated_function

# --- LaTeX Formula Sanitizer ---
def fix_latex_string(text):
    if not text or not isinstance(text, str):
        return text
    
    text = text.strip()
    
    # 1. Restore common stripped LaTeX backslashes from AI/JSON
    math_symbols = ['sqrt', 'frac', 'text', 'vec', 'theta', 'alpha', 'beta', 'pi', 'infty', 'cdot', 'times', 'pm', 'Delta', 'sum', 'int']
    for sym in math_symbols:
        text = re.sub(r'(?<!\\)\b' + sym + r'\{', r'\\' + sym + '{', text)

    # 2. Convert plain text fractions (e.g. A/(x+2)) into LaTeX \frac{A}{x+2}
    if '/' in text and '$' not in text and not text.startswith('http'):
        parts = text.split('/')
        if len(parts) == 2:
            num = parts[0].strip()
            den = parts[1].strip()
            if re.search(r'[a-zA-Z0-9()+^_-]', num):
                text = f"\\frac{{{num}}}{{{den}}}"

    # 3. Wrap math expressions with dollar signs if missing
    if ('\\' in text or '^' in text or '_' in text) and '$' not in text:
        text = f"${text}$"

    # 4. Fix unclosed dollar signs
    if text.count('$') == 1:
        text = text + '$'
        
    return text


# --- PDF Parser Functions ---

def parse_single_chunk_with_ai(chunk_path):
    if not client:
        raise ValueError("GEMINI_API_KEY is not configured on the server.")

    print(f"DEBUG: Uploading temporary chunk {chunk_path} to Google File API...")
    uploaded_file = client.files.upload(file=chunk_path)
    
    while uploaded_file.state.name == "PROCESSING":
        time.sleep(1.5)
        uploaded_file = client.files.get(name=uploaded_file.name)

    prompt = """
    Analyze the uploaded exam document segment and convert it strictly into a structured JSON object.
    CRITICAL: Convert ALL math formulas, fractions, roots, and physics units into standard LaTeX syntax enclosed in $ ... $.

    Format EXACTLY matching this JSON schema:
    {
        "school_name": "Institution name (or null)",
        "department": "Department or subject (or null)",
        "academic_year": "Academic year (or null)",
        "instructions": "Exam guidelines (or null)",
        "questions": [
            {
                "question": "The question text itself",
                "A": "Option A text",
                "B": "Option B text",
                "C": "Option C text",
                "D": "Option D text",
                "correct": "A, B, C, or D",
                "explanation": "A detailed explanation",
                "passage_text": "Reading passage for comprehension (or null)",
                "diagram_instruction": "Description of figure/diagram if applicable (or null)"
            }
        ]
    }
    """

    models_to_try = [
        "gemini-flash-latest",
        "gemini-3.5-flash",
        "gemini-3.1-flash-lite"
    ]
    last_error = None

    for model_name in models_to_try:
        max_retries = 3
        backoff_delay = 10
        for attempt in range(max_retries):
            try:
                print(f"DEBUG: Running model {model_name} on chunk (Attempt {attempt + 1}/{max_retries})")
                response = client.models.generate_content(
                    model=model_name,
                    contents=[uploaded_file, prompt],
                    config=types.GenerateContentConfig(response_mime_type="application/json"),
                )
                
                try:
                    client.files.delete(name=uploaded_file.name)
                except Exception as clean_err:
                    print(f"DEBUG: Storage cleanup warning: {clean_err}")

                if not response or not response.text:
                    raise ValueError("API returned an empty response.")

                return json.loads(response.text)

            except Exception as e:
                error_msg = str(e)
                last_error = e
                print(f"DEBUG: Model '{model_name}' failed on chunk. Error: {error_msg}")
                
                if any(err in error_msg for err in ["429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE"]):
                    match = re.search(r"Please retry in ([0-9.]+)s", error_msg)
                    wait_time = float(match.group(1)) + 1.5 if match else backoff_delay
                    print(f"DEBUG: Rate limit reached. Sleeping for {wait_time} seconds...")
                    time.sleep(wait_time)
                    backoff_delay *= 2
                    continue
                break

    try:
        client.files.delete(name=uploaded_file.name)
    except Exception:
        pass
    raise Exception(f"Failed to process PDF segment. Detail: {last_error}")


def parse_pdf_with_ai(pdf_path):
    reader = PdfReader(pdf_path)
    total_pages = len(reader.pages)
    print(f"DEBUG: Initiating parser. Total pages detected: {total_pages}")
    
    chunk_size = 1
    all_questions = []
    school_name = None
    department = None
    academic_year = None
    instructions = None

    for start_page in range(0, total_pages, chunk_size):
        end_page = min(start_page + chunk_size, total_pages)
        print(f"DEBUG: Slicing PDF page {start_page + 1} of {total_pages}...")

        writer = PdfWriter()
        for page_num in range(start_page, end_page):
            writer.add_page(reader.pages[page_num])
            
        chunk_filename = f"temp_chunk_{start_page}_{end_page}.pdf"
        with open(chunk_filename, "wb") as f:
            writer.write(f)

        try:
            chunk_data = parse_single_chunk_with_ai(chunk_filename)
        except Exception as chunk_exc:
            print(f"DEBUG: Chunk processing failed at page {start_page + 1}: {chunk_exc}")
            chunk_data = None
        finally:
            if os.path.exists(chunk_filename):
                os.remove(chunk_filename)

        if chunk_data:
            if not school_name and chunk_data.get("school_name"):
                school_name = chunk_data.get("school_name")
            if not department and chunk_data.get("department"):
                department = chunk_data.get("department")
            if not academic_year and chunk_data.get("academic_year"):
                academic_year = chunk_data.get("academic_year")
            if not instructions and chunk_data.get("instructions"):
                instructions = chunk_data.get("instructions")

            questions_list = chunk_data.get("questions", [])
            print(f"DEBUG: Successfully extracted {len(questions_list)} questions from page {start_page + 1}.")
            all_questions.extend(questions_list)

        if end_page < total_pages:
            print("DEBUG: Pausing for 10 seconds to allow the rolling minute quota to reset...")
            time.sleep(10)

    return {
        "school_name": school_name,
        "department": department,
        "academic_year": academic_year,
        "instructions": instructions,
        "questions": all_questions
    }


# --- Telegram Membership Checking Helper ---
def check_telegram_channel_membership(user_id_or_handle):
    if not TELEGRAM_BOT_TOKEN:
        return True # Fallback if token not set in environment

    user_id_or_handle = str(user_id_or_handle).strip().replace("@", "")
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getChatMember?chat_id={TELEGRAM_CHANNEL}&user_id={user_id_or_handle}"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as response:
            res_data = json.loads(response.read().decode('utf-8'))
            if res_data.get("ok"):
                status = res_data['result']['status']
                return status in ['member', 'administrator', 'creator']
    except Exception as e:
        print(f"DEBUG: Telegram API Check Warning: {e}")
    return False


# --- Static Service Worker Route ---
@app.route('/sw.js')
def service_worker():
    return send_from_directory('static', 'sw.js', mimetype='application/javascript')

@app.route('/ping')
def ping():
    return "OK", 200


# --- Authentication Routes ---

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form['username'].strip().lower()
        password = request.form['password']
        telegram_id = request.form.get('telegram_id', '').strip()

        if not username or not password:
            flash("All fields are required", "error")
            return render_template('signup.html')
        
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            param = "%s" if is_postgres() else "?"
            cursor.execute(
                f'INSERT INTO users (username, password_hash, telegram_id, is_verified) VALUES ({param}, {param}, {param}, {param})', 
                (username, generate_password_hash(password), telegram_id, 1)
            )
            conn.commit()
            flash("Signup success! Please login.", "success")
            return redirect(url_for('login'))
        except Exception as e:
            flash("Username already taken", "error")
        finally:
            cursor.close()
            conn.close()
    return render_template('signup.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip().lower()
        password = request.form['password']
        
        conn = get_db_connection()
        cursor = conn.cursor()
        param = "%s" if is_postgres() else "?"
        cursor.execute(f'SELECT * FROM users WHERE username = {param}', (username,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            return redirect(url_for('index'))
        flash("Invalid credentials", "error")
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# --- Main Web Page Routes ---

@app.route('/')
@login_required
def index():
    return render_template('index.html', username=session.get('username'), role=session.get('role'))
@app.route('/worksheets')
@app.route('/resources')
def worksheets():
    return render_template('worksheet.html', role=session.get('role', 'student'))

@app.route('/subject/<name>')
@login_required
def subject_page(name):
    return render_template('subject.html', subject_name=name)

@app.route('/chapters/<subject>')
@login_required
def chapters_page(subject):
    return render_template('chapter.html', subject=subject)

@app.route('/exam/<int:exam_id>')
@login_required
def exam_page(exam_id):
    return render_template('exam.html', exam_id=exam_id)

@app.route('/result/<int:result_id>')
@login_required
def result_page(result_id):
    return render_template('result.html', result_id=result_id)

@app.route('/tutor')
@login_required
def tutor_page():
    return render_template('tutor.html')

@app.route('/admin')
@admin_required
def admin_page():
    return render_template('admin.html')

@app.route('/resources')
@login_required
def resources_hub():
    return render_template('resources.html', username=session.get('username'))

@app.route('/study/<int:material_id>')
@login_required
def study_material_console(material_id):
    return render_template('study_material.html', material_id=material_id)


# --- API Endpoints ---

@app.route('/api/verify-task', methods=['POST'])
def verify_social_task():
    data = request.get_json(silent=True) or {}
    telegram_id = (data.get("telegram_id") or "").strip()
    task_type = (data.get("task_type") or "").strip()
    if not telegram_id:
        return jsonify({
            "success": False,
            "error": "Telegram User ID/Handle required."
        }), 400
    allowed_tasks = ["channel", "bot", "youtube", "group_invites"]
    if task_type not in allowed_tasks:
        return jsonify({
            "success": False,
            "error": "Invalid task type"
        }), 400
    # Server-side 10 second verification timer
    now = time.time()
    session_key = f"verify_started_{task_type}"
    started_at = session.get(session_key)
    # First verification request starts the timer
    if started_at is None:
        session[session_key] = now
        session.modified = True
        return jsonify({
            "success": False,
            "waiting": True,
            "remaining": 10,
            "error": "Please wait 10 seconds before verification."
        }), 202
    elapsed = now - float(started_at)
    # Do not verify before 10 seconds
    if elapsed < 10:
        remaining = max(1, int(10 - elapsed + 0.999))
        return jsonify({
            "success": False,
            "waiting": True,
            "remaining": remaining,
            "error": f"Please wait {remaining} more seconds."
        }), 202

    # Task 1: Telegram Channel
    if task_type == "channel":
        is_member = check_telegram_channel_membership(telegram_id)

        if not is_member:
            session.pop(session_key, None)
            session.modified = True
            return jsonify({
                "success": False,
                "error": "Telegram channel membership could not be verified yet."
            }), 400
        message = "Channel join verified!"
    # Task 2: Telegram Bot
    elif task_type == "bot":
        message = "Bot task verified!"
    # Task 3 YouTube
    elif task_type == "youtube":
        message = "YouTube task verified!"
    # Task 4: Group Invites
    elif task_type == "group_invites":
        message = "Group invite task verified!"
    # Clear timer after successful verification
    session.pop(session_key, None)
    session.modified = True
    return jsonify({
        "success": True,
        "message": message
    })

    return jsonify({"success": False, "error": "Invalid task type"}), 400


@app.route('/api/exams', methods=['GET'])
@login_required
def get_exams():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM exams ORDER BY id DESC')
    exams = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify([dict(exam) for exam in exams])


@app.route('/api/exams/<int:exam_id>/questions', methods=['GET'])
@login_required
def get_questions(exam_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    param = "%s" if is_postgres() else "?"
    cursor.execute(f'SELECT * FROM questions WHERE exam_id = {param} ORDER BY id ASC', (exam_id,))
    questions = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify([dict(q) for q in questions])


@app.route('/api/chapters/<subject>', methods=['GET'])
@login_required
def get_chapters(subject):
    conn = get_db_connection()
    cursor = conn.cursor()
    param = "%s" if is_postgres() else "?"
    cursor.execute(f'SELECT * FROM chapters WHERE LOWER(subject) = LOWER({param}) ORDER BY id ASC', (subject,))
    chaps = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify([dict(c) for c in chaps])


@app.route('/api/questions/chapter/<int:chapter_id>', methods=['GET'])
@login_required
def get_chapter_questions(chapter_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    param = "%s" if is_postgres() else "?"
    cursor.execute(f'SELECT * FROM questions WHERE chapter_id = {param} ORDER BY id ASC', (chapter_id,))
    questions = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify([dict(q) for q in questions])


@app.route('/api/results/submit', methods=['POST'])
@login_required
def submit_exam_results():
    data = request.json or {}
    conn = get_db_connection()
    cursor = conn.cursor()
    
    score = int(data['score'])
    total = int(data['total_questions'])
    accuracy = float(data['accuracy'])
    
    rec_prompt = f"The student scored {score}/{total} ({accuracy}% accuracy) in an exam. Provide a brief, supportive, 2-sentence study plan."
    try:
        response = client.models.generate_content(model="gemini-3.5-flash", contents=rec_prompt)
        recommendation = response.text
    except Exception:
        recommendation = "Focus on weak chapters and review explanations for incorrect attempts."

    param = "%s" if is_postgres() else "?"
    sql = f'''
        INSERT INTO user_results (user_id, exam_id, score, total_questions, time_used_seconds, accuracy, date_attempted, ai_recommendation)
        VALUES ({param}, {param}, {param}, {param}, {param}, {param}, {param}, {param})
    '''
    if is_postgres():
        sql += " RETURNING id"
        cursor.execute(sql, (session['user_id'], data['exam_id'], score, total, data['time_used'], accuracy, time.strftime("%Y-%m-%d %H:%M"), recommendation))
        result_id = cursor.fetchone()['id']
    else:
        cursor.execute(sql, (session['user_id'], data['exam_id'], score, total, data['time_used'], accuracy, time.strftime("%Y-%m-%d %H:%M"), recommendation))
        result_id = cursor.lastrowid

    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"success": True, "result_id": result_id})


@app.route('/api/results/<int:result_id>', methods=['GET'])
@login_required
def get_result_details(result_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    param = "%s" if is_postgres() else "?"
    cursor.execute(f'''
        SELECT r.*, e.title as exam_title, e.category as exam_category
        FROM user_results r
        JOIN exams e ON r.exam_id = e.id
        WHERE r.id = {param} AND r.user_id = {param}
    ''', (result_id, session['user_id']))
    result = cursor.fetchone()
    cursor.close()
    conn.close()
    if not result:
        return jsonify({"error": "Result not found"}), 404
    return jsonify(dict(result))


# --- SMART UPLOAD ENGINE (Worksheets, Entrance Exams, Subject & Chapter Categorization) ---

@app.route('/api/upload', methods=['POST'])
@admin_required
def upload_engine():
    title = request.form.get('title', 'Untitled Resource').strip()
    resource_type = request.form.get('resource_type', 'Exam').strip() # 'Exam' or 'Worksheet'
    category = request.form.get('category', 'General').strip() # 'National Entrance (EUEE)', 'Model Exam', 'Chapter Worksheet'
    subject = request.form.get('subject', 'Mathematics').strip()
    grade = int(request.form.get('grade', 12))
    chapter_name = request.form.get('chapter_name', '').strip()
    academic_year = request.form.get('academic_year', '').strip()

    file = request.files.get('json_file') or request.files.get('pdf_file')
    if not file:
        return jsonify({"success": False, "error": "No file uploaded"}), 400

    try:
        # 1. Parse JSON or PDF
        if file.filename.endswith('.json') or 'json' in file.mimetype:
            ai_data = json.load(file)
        else:
            filepath = os.path.join('uploads', file.filename)
            file.save(filepath)
            try:
                ai_data = parse_pdf_with_ai(filepath)
            finally:
                if os.path.exists(filepath):
                    os.remove(filepath)

        conn = get_db_connection()
        cursor = conn.cursor()
        param = "%s" if is_postgres() else "?"

        # 2. Resolve or Create Chapter (Subject -> Chapter linkage)
        chapter_id = None
        if chapter_name:
            cursor.execute(f'''
                SELECT id FROM chapters WHERE LOWER(subject) = LOWER({param}) AND LOWER(name) = LOWER({param}) AND grade = {param}
            ''', (subject, chapter_name, grade))
            row = cursor.fetchone()
            if row:
                chapter_id = row['id']
            else:
                if is_postgres():
                    cursor.execute(f'''
                        INSERT INTO chapters (subject, name, grade) VALUES ({param}, {param}, {param}) RETURNING id
                    ''', (subject, chapter_name, grade))
                    chapter_id = cursor.fetchone()['id']
                else:
                    cursor.execute(f'''
                        INSERT INTO chapters (subject, name, grade) VALUES ({param}, {param}, {param})
                    ''', (subject, chapter_name, grade))
                    chapter_id = cursor.lastrowid

        # 3. Insert into Exams/Resources Table
        sql_exam = f'''
            INSERT INTO exams (title, category, resource_type, subject, grade, academic_year, instructions)
            VALUES ({param}, {param}, {param}, {param}, {param}, {param}, {param})
        '''
        if is_postgres():
            sql_exam += " RETURNING id"
            cursor.execute(sql_exam, (title, category, resource_type, subject, grade, academic_year, ai_data.get('instructions')))
            exam_id = cursor.fetchone()['id']
        else:
            cursor.execute(sql_exam, (title, category, resource_type, subject, grade, academic_year, ai_data.get('instructions')))
            exam_id = cursor.lastrowid

        # 4. Insert Questions and Auto-Fix LaTeX Formulas
        questions = ai_data.get('questions', [])
        for q in questions:
            q_text = fix_latex_string(q.get('question') or q.get('question_text', ''))
            opt_a  = fix_latex_string(q.get('A') or q.get('option_a', ''))
            opt_b  = fix_latex_string(q.get('B') or q.get('option_b', ''))
            opt_c  = fix_latex_string(q.get('C') or q.get('option_c', ''))
            opt_d  = fix_latex_string(q.get('D') or q.get('option_d', ''))
            expl   = fix_latex_string(q.get('explanation', ''))

            cursor.execute(f'''
                INSERT INTO questions (
                    exam_id, chapter_id, question_text, option_a, option_b, option_c, option_d,
                    correct_answer, explanation, passage_text, diagram_instruction
                )
                VALUES ({param}, {param}, {param}, {param}, {param}, {param}, {param}, {param}, {param}, {param}, {param})
            ''', (
                exam_id, chapter_id, q_text, opt_a, opt_b, opt_c, opt_d,
                q.get('correct') or q.get('correct_answer', 'A'),
                expl, q.get('passage_text'), q.get('diagram_instruction')
            ))

        # 5. Update Chapter Question Count
        if chapter_id:
            cursor.execute(f'''
                UPDATE chapters SET question_count = question_count + {param} WHERE id = {param}
            ''', (len(questions), chapter_id))

        conn.commit()
        cursor.close()
        conn.close()

        target_section = "Worksheets" if resource_type == "Worksheet" else ("Entrance Exams" if "entrance" in category.lower() else "Exams Available")
        return jsonify({
            "success": True,
            "message": f"Successfully placed '{title}' under {subject} Grade {grade} ➔ {target_section} ({len(questions)} questions linked)!"
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/tutor/chat', methods=['POST'])
@login_required
def tutor_chat():
    data = request.get_json(silent=True) or {}
    user_message = (data.get("message") or "").strip()

    if not user_message:
        return jsonify({"error": "Message is required"}), 400

    if not client:
        return jsonify({"error": "GEMINI_API_KEY is not configured on the server."}), 500

    tutor_prompt = f"""
You are EduVault's empathetic, world-class academic tutor.

Answer the student's question clearly and accurately:
- Explain step-by-step when necessary.
- Use simple, friendly English.
- For science and mathematics, include formulas or examples.
- Be supportive and clear.

Student's query:
{user_message}
"""

    tutor_models = [
        "gemini-flash-latest",
        "gemini-3.5-flash",
        "gemini-3.1-flash-lite"
    ]

    last_error = None

    for model_name in tutor_models:
        try:
            print(f"DEBUG: AI Tutor query model: {model_name}")
            response = client.models.generate_content(
                model=model_name,
                contents=tutor_prompt
            )

            if response and response.text:
                return jsonify({
                    "response": response.text,
                    "model": model_name
                })

            last_error = f"{model_name} returned an empty response."

        except Exception as error:
            last_error = error
            print(f"DEBUG: AI Tutor model {model_name} failed: {error}")
            continue

    return jsonify({
        "error": "AI Tutor is temporarily unavailable.",
        "details": str(last_error)
    }), 503


if __name__ == '__main__':
    if not os.path.exists('uploads'):
        os.makedirs('uploads')
    app.run(debug=True, port=5000)
