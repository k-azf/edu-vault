import os
import json
import hashlib
import time
import re
import sqlite3
import urllib.request
import urllib.error
import tempfile
import uuid
import secrets
import shutil
import smtplib
from email.message import EmailMessage
from functools import wraps
from flask import Flask, abort, render_template, request, jsonify, redirect, url_for, session, flash, send_from_directory, send_file
from google import genai
from google.genai import types
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from PIL import Image
import speech_recognition as sr
from io import BytesIO
import base64
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, '.env'))

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "super-secret-eduvault-key-12345")

# --- Configuration ---
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
PROFILE_PHOTO_FOLDER = os.path.join(UPLOAD_FOLDER, 'profile_photos')
TEXTBOOK_FOLDER = os.path.join(UPLOAD_FOLDER, 'textbooks')
EXAM_EXPLANATION_FOLDER = os.path.join(UPLOAD_FOLDER, 'exam_explanations')
MAX_FILE_SIZE = 16 * 1024 * 1024  # 16 MB
SQLITE_BUSY_TIMEOUT_MS = 30_000
ALLOWED_EXTENSIONS = {'pdf', 'json', 'png', 'jpg', 'jpeg', 'gif', 'txt', 'docx', 'mp3', 'wav', 'ogg', 'm4a'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(PROFILE_PHOTO_FOLDER, exist_ok=True)
os.makedirs(TEXTBOOK_FOLDER, exist_ok=True)
os.makedirs(EXAM_EXPLANATION_FOLDER, exist_ok=True)

# Telegram Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL = os.getenv("TELEGRAM_CHANNEL_USERNAME", "@eduvault12")

# Database Configuration
DATABASE_URL = os.getenv("DATABASE_URL")

# Gemini Client
gemini_key = os.getenv("GEMINI_API_KEY")
client = None


def get_gemini_client():
    """Create the Gemini client only when an AI feature actually needs it."""
    global client
    if client is None and gemini_key:
        client = genai.Client(api_key=gemini_key)
    return client


classification_retry_after = 0.0

from init_db import init_db
from ranking import calculate_exam_system_entrance_top_performers, calculate_exam_system_mock_top_performers, calculate_exam_top_performers, calculate_rankings
from exam_classification import EXAMINATION_TYPES, examination_destination, normalize_examination_type
from exam_logic import remaining_exam_seconds, score_saved_answers

try:
    init_db()
except Exception as e:
    def get_curriculum_outline(subject_name, grade_number):
        conn = get_db_connection()
        cursor = conn.cursor()
        param = get_param_style()
        cursor.execute(f"""
            SELECT u.unit_number, u.title AS unit_title,
                   s.section_number, s.title AS section_title
            FROM curriculum_units u
            JOIN curriculum_subjects cs ON cs.id = u.subject_id
            JOIN curriculum_grades cg ON cg.id = u.grade_id
            LEFT JOIN curriculum_sections s ON s.unit_id = u.id
            WHERE cs.name = {param} AND cg.number = {param}
            ORDER BY u.unit_number, s.section_number
        """, (subject_name, grade_number))
        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        return [dict(row) for row in rows]

    '''
    def parse_pdf_with_ai(pdf_path, subject_name, grade_number):
        if not get_gemini_client():
            raise ValueError("GEMINI_API_KEY is not configured on the server.")

        curriculum = get_curriculum_outline(subject_name, grade_number)
        if not curriculum:
            raise ValueError(f"No textbook curriculum JSON has been uploaded for {subject_name} Grade {grade_number}.")

        uploaded_file = client.files.upload(file=pdf_path)
        while uploaded_file.state.name == "PROCESSING":
            time.sleep(1.5)
            uploaded_file = client.files.get(name=uploaded_file.name)

        prompt = f"""
    Read this complete Ethiopian entrance exam PDF and return JSON only. Extract every question (including 100-200
    
    math_symbols = ['sqrt', 'frac', 'text', 'vec', 'theta', 'alpha', 'beta', 'pi', 'infty', 'cdot', 'times', 'pm', 'Delta', 'sum', 'int', 'left', 'right', 'sin', 'cos', 'tan', 'log', 'ln']
    for sym in math_symbols:
        text = re.sub(r'(?<!\\)\b' + sym + r'\\{', r'\\' + sym + '{', text)
        text = re.sub(r'(?<!\\)\b' + sym + r'\b', r'\\' + sym, text)

    if '/' in text and '$' not in text and not text.startswith('http'):
        parts = text.split('/')
        if len(parts) == 2:
            num = parts[0].strip()
            den = parts[1].strip()
            if re.search(r'[a-zA-Z0-9()+^_-]', num) and re.search(r'[a-zA-Z0-9()+^_-]', den):
                text = f"\\frac{{{num}}}{{{den}}}"

    if ('\\' in text or '^' in text or '_' in text) and '$' not in text:
        text = f"${text}$"

    if text.count('$') == 1:
        text = text + '$'
        
    text = text.replace('\\\\', '\\')
    
    return text

# ============================================
# PDF PARSER FUNCTIONS
# ============================================
    '''

'''
def parse_single_chunk_with_ai(chunk_path):
    if not get_gemini_client():
        raise ValueError("GEMINI_API_KEY is not configured on the server.")

    print(f"DEBUG: Uploading temporary chunk {chunk_path} to Google File API...")
    uploaded_file = client.files.upload(file=chunk_path)

        try:
            response = client.models.generate_content(
                model="gemini-flash-latest",
                contents=[uploaded_file, prompt],
                config=types.GenerateContentConfig(response_mime_type="application/json")
            )
            if not response or not response.text:
                raise ValueError("AI returned an empty response.")
            return json.loads(response.text)
        finally:
            try:
                client.files.delete(name=uploaded_file.name)
            except Exception:
                pass
    
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
        "gemini-2.0-flash-exp",
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

'''
def parse_single_chunk_with_ai(chunk_path):
    """Parse one legacy PDF page chunk with Gemini and return its JSON payload."""
    gemini = get_gemini_client()
    if not gemini:
        raise ValueError("GEMINI_API_KEY is not configured on the server.")

    uploaded_file = gemini.files.upload(file=chunk_path)
    try:
        while uploaded_file.state.name == "PROCESSING":
            time.sleep(1.5)
            uploaded_file = gemini.files.get(name=uploaded_file.name)

        prompt = """
        Extract the exam questions from this PDF page and return JSON only using this schema:
        {"school_name": null, "department": null, "academic_year": null,
         "instructions": null, "questions": [{"question": "", "A": "", "B": "",
         "C": "", "D": "", "correct": "A", "explanation": "",
         "passage_text": null, "diagram_instruction": null}]}
        Preserve the question and choices accurately. Do not invent missing answers.
        """
        response = gemini.models.generate_content(
            model="gemini-flash-latest",
            contents=[uploaded_file, prompt],
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )
        if not response or not response.text:
            raise ValueError("AI returned an empty response.")
        return json.loads(response.text)
    finally:
        try:
            gemini.files.delete(name=uploaded_file.name)
        except Exception:
            app.logger.warning("Could not delete temporary Gemini PDF upload", exc_info=True)


def parse_pdf_with_ai_legacy(pdf_path):
    from pypdf import PdfReader, PdfWriter

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


def get_db_connection():
    if DATABASE_URL:
        try:
            import psycopg2
            from psycopg2.extras import RealDictCursor
            return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor, connect_timeout=10)
        except Exception as error:
            # Never silently fall back to a separate local database when cloud storage is configured.
            app.logger.exception("Configured PostgreSQL connection failed")
            raise RuntimeError(
                "DATABASE_URL is configured, but PostgreSQL could not be reached. "
                "Check the connection string, network access, and Supabase pooler settings; "
                "EduVault will not silently switch to a separate SQLite database."
            ) from error
    conn = sqlite3.connect(
        os.path.join(BASE_DIR, 'data', 'exams.db'),
        timeout=SQLITE_BUSY_TIMEOUT_MS / 1000,
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    conn.execute(f'PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}')
    conn.execute('PRAGMA journal_mode = WAL')
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


def is_postgres():
    return bool(DATABASE_URL)


def get_param_style():
    return "%s" if is_postgres() else "?"


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def fix_latex_string(value):
    """Normalize common AI math output for MathJax rendering."""
    text = '' if value is None else str(value).strip()
    if not text:
        return text

    math_symbols = (
        'sqrt', 'frac', 'text', 'vec', 'theta', 'alpha', 'beta', 'pi', 'infty',
        'cdot', 'times', 'pm', 'Delta', 'sum', 'int', 'left', 'right', 'sin',
        'cos', 'tan', 'log', 'ln'
    )
    for symbol in math_symbols:
        text = re.sub(r'(?<!\\)\\b' + symbol + r'\\{', r'\\' + symbol + '{', text)
        text = re.sub(r'(?<!\\)\\b' + symbol + r'\\b', r'\\' + symbol, text)

    if '/' in text and '$' not in text and not text.startswith('http'):
        parts = text.split('/')
        if len(parts) == 2:
            numerator, denominator = (part.strip() for part in parts)
            if re.search(r'[a-zA-Z0-9()+^_-]', numerator) and re.search(
                r'[a-zA-Z0-9()+^_-]', denominator
            ):
                text = f"\\frac{{{numerator}}}{{{denominator}}}"

    if ('\\' in text or '^' in text or '_' in text) and '$' not in text:
        text = f'${text}$'

    if text.count('$') == 1:
        text += '$'

    return text.replace('\\\\', '\\')


def login_required(function):
    @wraps(function)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return function(*args, **kwargs)
    return decorated_function


def portal_or_unified_required(function):
    """Allow signed-in main-portal and Unified Exam students to browse resources."""
    @wraps(function)
    def decorated_function(*args, **kwargs):
        if not session.get('user_id') and not session.get('unified_account_id'):
            return redirect(url_for('login'))
        return function(*args, **kwargs)
    return decorated_function


def admin_required(function):
    @wraps(function)
    def decorated_function(*args, **kwargs):
        if session.get('role') != 'admin':
            return jsonify({"error": "Forbidden: Admin access required"}), 403
        return function(*args, **kwargs)
    return decorated_function


def unified_account_required(function):
    @wraps(function)
    def decorated_function(*args, **kwargs):
        if not session.get('unified_account_id'):
            return jsonify({"error": "Unified System login is required."}), 401
        return function(*args, **kwargs)
    return decorated_function


def unified_admin_required(function):
    @wraps(function)
    def decorated_function(*args, **kwargs):
        if session.get('unified_role') != 'admin':
            return jsonify({"error": "Unified System administrator access is required."}), 403
        return function(*args, **kwargs)
    return decorated_function


def normalize_person_name(value):
    return re.sub(r"\s+", " ", (value or "").strip())


def valid_person_name(value):
    return bool(re.fullmatch(r"[A-Za-z][A-Za-z' -]{1,49}", value or ""))


def valid_username(value):
    return isinstance(value, str) and 1 <= len(value) <= 100 and bool(value.strip())


def unified_account_dict(row):
    account = dict(row)
    account.pop('password_hash', None)
    account['name'] = normalize_person_name(
        f"{account.get('first_name') or ''} {account.get('last_name') or ''}"
    )
    account['code'] = account.get('student_code') or ''
    account['studentCode'] = account.get('student_code') or ''
    account['studentName'] = account['name']
    account['photo'] = url_for('profile_photo', filename=account['profile_photo']) if account.get('profile_photo') else ''
    return account


def get_user_by_id(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    param = get_param_style()
    cursor.execute(f"SELECT * FROM users WHERE id = {param}", (user_id,))
    user = cursor.fetchone()
    cursor.close()
    conn.close()
    return user


def is_active_student(user):
    return user and user['role'] == 'student' and user['account_status'] == 'ACTIVE' and user['student_code']


def exam_access_allowed(exam_id=None):
    if session.get('role') == 'admin':
        return True
    user = get_user_by_id(session.get('user_id'))
    if not is_active_student(user):
        return False
    verified_user_id = session.get('exam_verified_user_id')
    verified_exam_id = session.get('exam_verified_exam_id')
    verified = verified_user_id == user['id'] and (exam_id is None or verified_exam_id == exam_id)
    if not verified or exam_id is None:
        return verified
    conn = get_db_connection()
    cur = conn.cursor()
    p = get_param_style()
    cur.execute(f"""
        SELECT e.category, o.status AS owner_status
        FROM exams e LEFT JOIN generated_exam_owners o ON o.exam_id = e.id AND o.user_id = {p}
        WHERE e.id = {p}
    """, (user['id'], exam_id))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if row and row['category'] == 'AI Generated Practice':
        return row['owner_status'] == 'active'
    return True


def exam_access_required(function):
    @wraps(function)
    def decorated_function(*args, **kwargs):
        exam_id = kwargs.get('exam_id')
        if not exam_access_allowed(exam_id):
            if request.path.startswith('/api/'):
                return jsonify({"error": "Full name and student code verification is required."}), 403
            return redirect(url_for('exam_page', exam_id=exam_id, verify='required'))
        return function(*args, **kwargs)
    return decorated_function


def next_student_code(cursor):
    used = set()
    for table in ('users', 'unified_accounts'):
        cursor.execute(f"SELECT student_code FROM {table} WHERE student_code IS NOT NULL")
        used.update(str(row['student_code'] or '').upper() for row in cursor.fetchall())
    highest = 0
    for value in used:
        match = re.fullmatch(r"ST(\d+)", value)
        if match:
            highest = max(highest, int(match.group(1)))
    while f"ST{highest + 1:03d}" in used:
        highest += 1
    return f"ST{highest + 1:03d}"


def normalize_ethiopian_phone(value):
    digits = re.sub(r"[\s().-]", "", str(value or ''))
    if digits.startswith('+'):
        digits = digits[1:]
    if digits.startswith('00251'):
        digits = digits[2:]
    if digits.startswith('251'):
        national = digits[3:]
    elif digits.startswith('0'):
        national = digits[1:]
    else:
        national = digits
    if not re.fullmatch(r'[79]\d{8}', national):
        raise ValueError("Enter a valid Ethiopian mobile number, such as 09xxxxxxxx or 07xxxxxxxx.")
    return '+251' + national


def normalize_email(value):
    address = str(value or '').strip().lower()
    if not address:
        return None
    if len(address) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", address):
        raise ValueError('Enter a valid email address.')
    return address


def send_student_code_email(email_address, student_code):
    host = os.getenv('SMTP_HOST', 'smtp.gmail.com').strip()
    username = os.getenv('SMTP_USERNAME', '').strip()
    password = os.getenv('SMTP_PASSWORD', '')
    sender = os.getenv('SMTP_FROM_EMAIL', username).strip()
    if not all((host, username, password, sender)):
        raise RuntimeError('Email delivery is not configured. Set SMTP_HOST, SMTP_USERNAME, SMTP_PASSWORD, and SMTP_FROM_EMAIL.')
    message = EmailMessage()
    message['Subject'] = 'Your EduVault Student Code'
    message['From'] = sender
    message['To'] = email_address
    message.set_content(
        f"Your EduVault account is approved. Your Student Code is {student_code}. "
        "Use this same code for the Entrance Exam and EduVault Examination System. Keep it private."
    )
    try:
        port = int(os.getenv('SMTP_PORT', '587'))
        use_ssl = os.getenv('SMTP_USE_SSL', '').strip().lower() in ('1', 'true', 'yes')
        use_tls = os.getenv('SMTP_USE_TLS', 'true').strip().lower() in ('1', 'true', 'yes')
        client_class = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
        with client_class(host, port, timeout=20) as client:
            if use_tls and not use_ssl:
                client.starttls()
            client.login(username, password)
            client.send_message(message)
    except Exception as exc:
        raise RuntimeError(f'Could not send the Student Code email: {exc}') from exc


def send_password_reset_email(email_address, reset_code):
    host = os.getenv('SMTP_HOST', 'smtp.gmail.com').strip()
    username = os.getenv('SMTP_USERNAME', '').strip()
    password = os.getenv('SMTP_PASSWORD', '')
    sender = os.getenv('SMTP_FROM_EMAIL', username).strip()
    if not all((host, username, password, sender)):
        raise RuntimeError('Email delivery is not configured.')
    message = EmailMessage()
    message['Subject'] = 'EduVault password reset code'
    message['From'] = sender
    message['To'] = email_address
    message.set_content(
        f'Your EduVault password reset code is {reset_code}. It expires in 10 minutes. '
        'If you did not request this change, ignore this email.'
    )
    port = int(os.getenv('SMTP_PORT', '587'))
    use_ssl = os.getenv('SMTP_USE_SSL', '').strip().lower() in ('1', 'true', 'yes')
    use_tls = os.getenv('SMTP_USE_TLS', 'true').strip().lower() in ('1', 'true', 'yes')
    client_class = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
    with client_class(host, port, timeout=20) as client:
        if use_tls and not use_ssl:
            client.starttls()
        client.login(username, password)
        client.send_message(message)


@app.route('/api/password-reset/request', methods=['POST'])
def request_password_reset():
    data = request.get_json(silent=True) or request.form
    username = str(data.get('username') or '').strip().lower()
    account_type = str(data.get('account_type') or '').strip().lower()
    if not username or account_type not in ('eduvault', 'examination'):
        return jsonify({'success': False, 'error': 'Enter your username and choose the correct login.'}), 400

    table = 'users' if account_type == 'eduvault' else 'unified_accounts'
    conn = get_db_connection()
    cursor = conn.cursor()
    param = get_param_style()
    try:
        cursor.execute(f'SELECT id, email FROM {table} WHERE username = {param}', (username,))
        account = cursor.fetchone()
        if account and account['email']:
            code = f'{secrets.randbelow(1_000_000):06d}'
            cursor.execute(
                f'DELETE FROM password_reset_codes WHERE account_type = {param} AND account_id = {param}',
                (account_type, account['id']),
            )
            cursor.execute(
                f'''INSERT INTO password_reset_codes (account_type, account_id, code_hash, expires_at, attempts)
                    VALUES ({param}, {param}, {param}, {param}, 0)''',
                (account_type, account['id'], generate_password_hash(code), int(time.time()) + 600),
            )
            conn.commit()
            try:
                send_password_reset_email(account['email'], code)
            except Exception:
                app.logger.exception('Password reset email could not be sent')
                cursor.execute(
                    f'DELETE FROM password_reset_codes WHERE account_type = {param} AND account_id = {param}',
                    (account_type, account['id']),
                )
                conn.commit()
    except Exception:
        conn.rollback()
        app.logger.exception('Password reset request failed')
    finally:
        cursor.close()
        conn.close()
    return jsonify({'success': True, 'message': 'If that username has a registered email, a reset code has been sent.'})


@app.route('/api/password-reset/confirm', methods=['POST'])
def confirm_password_reset():
    data = request.get_json(silent=True) or request.form
    username = str(data.get('username') or '').strip().lower()
    account_type = str(data.get('account_type') or '').strip().lower()
    code = str(data.get('code') or '').strip()
    new_password = str(data.get('new_password') or '')
    if not username or account_type not in ('eduvault', 'examination') or not re.fullmatch(r'\d{6}', code):
        return jsonify({'success': False, 'error': 'Enter the username and six-digit email code.'}), 400
    if len(new_password) < 8:
        return jsonify({'success': False, 'error': 'Use a password with at least 8 characters.'}), 400

    table = 'users' if account_type == 'eduvault' else 'unified_accounts'
    conn = get_db_connection()
    cursor = conn.cursor()
    param = get_param_style()
    try:
        cursor.execute(f'SELECT id FROM {table} WHERE username = {param}', (username,))
        account = cursor.fetchone()
        if not account:
            return jsonify({'success': False, 'error': 'The code is invalid or expired. Request a new one.'}), 400
        cursor.execute(
            f'''SELECT code_hash, expires_at, attempts FROM password_reset_codes
                WHERE account_type = {param} AND account_id = {param}''',
            (account_type, account['id']),
        )
        reset = cursor.fetchone()
        if not reset or int(reset['expires_at']) < int(time.time()) or int(reset['attempts']) >= 5:
            cursor.execute(
                f'DELETE FROM password_reset_codes WHERE account_type = {param} AND account_id = {param}',
                (account_type, account['id']),
            )
            conn.commit()
            return jsonify({'success': False, 'error': 'The code is invalid or expired. Request a new one.'}), 400
        if not check_password_hash(reset['code_hash'], code):
            cursor.execute(
                f'''UPDATE password_reset_codes SET attempts = attempts + 1
                    WHERE account_type = {param} AND account_id = {param}''',
                (account_type, account['id']),
            )
            conn.commit()
            return jsonify({'success': False, 'error': 'The code is invalid or expired. Request a new one.'}), 400
        cursor.execute(
            f'UPDATE {table} SET password_hash = {param} WHERE id = {param}',
            (generate_password_hash(new_password), account['id']),
        )
        cursor.execute(
            f'DELETE FROM password_reset_codes WHERE account_type = {param} AND account_id = {param}',
            (account_type, account['id']),
        )
        conn.commit()
        return jsonify({'success': True, 'message': 'Password updated. Sign in with your new password.'})
    except Exception:
        conn.rollback()
        app.logger.exception('Password reset confirmation failed')
        return jsonify({'success': False, 'error': 'Could not reset the password. Try again.'}), 500
    finally:
        cursor.close()
        conn.close()


def phone_is_registered(cursor, phone_number):
    if not phone_number:
        return False
    param = get_param_style()
    for table in ('users', 'unified_accounts'):
        cursor.execute(f"SELECT 1 FROM {table} WHERE phone_number = {param} LIMIT 1", (phone_number,))
        if cursor.fetchone():
            return True
    return False


def email_is_registered(cursor, email_address):
    if not email_address:
        return False
    param = get_param_style()
    for table in ('users', 'unified_accounts'):
        cursor.execute(f"SELECT 1 FROM {table} WHERE LOWER(email) = {param} LIMIT 1", (email_address,))
        if cursor.fetchone():
            return True
    return False


def sync_user_to_unified_student(cursor, user_id, first_name, last_name, student_code, phone_number, email_address,
                                account_status='ACTIVE'):
    """Keep a student mirror for the Unified Exam UI using the portal's single issued code."""
    param = get_param_style()
    username = f"ev_student_{user_id}"
    cursor.execute(f"SELECT id FROM unified_accounts WHERE username = {param}", (username,))
    existing = cursor.fetchone()
    if existing:
        cursor.execute(f"""UPDATE unified_accounts SET first_name = {param}, last_name = {param},
            student_code = {param}, phone_number = {param}, email = {param}, account_status = {param},
            updated_at = CURRENT_TIMESTAMP WHERE username = {param}""",
            (first_name, last_name, student_code, phone_number, email_address, account_status, username))
    else:
        cursor.execute(f"""INSERT INTO unified_accounts
            (username, password_hash, role, first_name, last_name, student_code, phone_number, email, account_status)
            VALUES ({param}, {param}, 'student', {param}, {param}, {param}, {param}, {param}, {param})""",
            (username, generate_password_hash(uuid.uuid4().hex), first_name, last_name,
             student_code, phone_number, email_address, account_status))


def save_profile_photo(file):
    if not file or not file.filename:
        raise ValueError("A 3x4 profile photograph is required.")
    if (file.mimetype or '').lower() not in {'image/jpeg', 'image/png', 'image/webp'}:
        raise ValueError("Profile photo must be a JPG, PNG, or WEBP image.")
    if request.content_length and request.content_length > 6 * 1024 * 1024:
        raise ValueError("Profile photo upload is too large.")
    try:
        image = Image.open(file.stream)
        image.verify()
        file.stream.seek(0)
        image = Image.open(file.stream)
        width, height = image.size
    except Exception as error:
        raise ValueError("The uploaded profile photo is not a valid image.") from error
    if width < 150 or height < 200 or not 0.68 <= width / height <= 0.82:
        raise ValueError("Profile photo must have a portrait 3x4 shape and be at least 150x200 pixels.")
    extension = {'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp'}[file.mimetype.lower()]
    filename = f"{uuid.uuid4().hex}{extension}"
    file.save(os.path.join(PROFILE_PHOTO_FOLDER, filename))
    return filename


def get_curriculum_outline(subject_name, grade_number):
    conn = get_db_connection()
    cursor = conn.cursor()
    param = get_param_style()
    cursor.execute(f"""
        SELECT u.unit_number, u.title AS unit_title,
               s.section_number, s.title AS section_title
        FROM curriculum_units u
        JOIN curriculum_subjects cs ON cs.id = u.subject_id
        JOIN curriculum_grades cg ON cg.id = u.grade_id
        LEFT JOIN curriculum_sections s ON s.unit_id = u.id
        WHERE cs.name = {param} AND cg.number = {param}
        ORDER BY u.unit_number, s.section_number
    """, (subject_name, grade_number))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return [dict(row) for row in rows]


def parse_pdf_with_ai(pdf_path, subject_name, grade_number):
    if not get_gemini_client():
        raise ValueError("GEMINI_API_KEY is not configured on the server.")
    curriculum = get_curriculum_outline(subject_name, grade_number)
    if not curriculum:
        raise ValueError(f"No curriculum records exist in the database for {subject_name} Grade {grade_number}.")

    uploaded_file = client.files.upload(file=pdf_path)
    try:
        while uploaded_file.state.name == "PROCESSING":
            time.sleep(1.5)
            uploaded_file = client.files.get(name=uploaded_file.name)
        prompt = f"""
Read the complete Ethiopian exam PDF. Return JSON only and extract every question in original order.
Preserve question_number and source_year exactly as printed. Do not classify questions in this extraction step;
set all curriculum classification fields to null. Classification is performed afterward in small batches against
our official curriculum, so the extraction remains focused and supports exams with around 100 questions.
Subject: {subject_name}; Grade: {grade_number}
Schema: {{"school_name": null, "department": "{subject_name}", "academic_year": null,
"instructions": null, "questions": [{{"question_number": 1, "source_year": null, "question": "",
"A": "", "B": "", "C": "", "D": "", "correct": "A", "explanation": "",
"passage_text": null, "diagram_instruction": null, "unit_number": null, "unit_title": null,
"section_number": null, "section_title": null,
"confidence": "Low", "reason": ""}}]}}
"""
        last_error = None
        for model_name in ("gemini-flash-latest", "gemini-2.0-flash"):
            for attempt in range(2):
                try:
                    response = client.models.generate_content(
                        model=model_name,
                        contents=[uploaded_file, prompt],
                        config=types.GenerateContentConfig(response_mime_type="application/json")
                    )
                    if not response or not response.text:
                        raise ValueError("AI returned an empty response.")
                    return json.loads(response.text)
                except Exception as error:
                    last_error = error
                    error_text = str(error).upper()
                    transient = any(code in error_text for code in (
                        "503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED"
                    ))
                    if not transient:
                        raise
                    wait_seconds = 2 ** (attempt + 1)
                    print(
                        f"DEBUG: {model_name} unavailable (attempt {attempt + 1}/2); "
                        f"retrying in {wait_seconds}s."
                    )
                    time.sleep(wait_seconds)
        raise RuntimeError(
            f"Gemini models are temporarily unavailable after retries: {last_error}"
        )
    finally:
        try:
            client.files.delete(name=uploaded_file.name)
        except Exception:
            pass

# ============================================
# AI CLASSIFICATION HELPER
# ============================================

def classify_question_with_curriculum(question_text, subject_name, grade_number):
    global classification_retry_after

    if not get_gemini_client():
        return {
            "error": "Gemini API not configured.",
            "confidence": "Low",
            "reason": "API unavailable"
        }

    if time.time() < classification_retry_after:
        return {
            "error": "Gemini classification temporarily unavailable due to quota limits.",
            "confidence": "Low",
            "reason": "Classification skipped during Gemini quota cooldown"
        }

    conn = get_db_connection()
    cursor = conn.cursor()
    param = get_param_style()
    
    cursor.execute(f"""
        SELECT u.unit_number, u.title,
               s.section_number, s.title as section_title
        FROM curriculum_units u
        JOIN curriculum_subjects cs ON u.subject_id = cs.id
        JOIN curriculum_grades cg ON u.grade_id = cg.id
        LEFT JOIN curriculum_sections s ON u.id = s.unit_id
        WHERE cs.name = {param} AND cg.number = {param}
        ORDER BY u.unit_number, s.section_number
    """, (subject_name, grade_number))
    
    curriculum_data = cursor.fetchall()
    cursor.close()
    conn.close()

    curriculum_context = "Available curriculum units:\n"
    current_unit = None
    for row in curriculum_data:
        if row['unit_number'] != current_unit:
            current_unit = row['unit_number']
            curriculum_context += f"\nUnit {row['unit_number']}: {row['title']}\n"
        if row['section_number']:
            curriculum_context += f"  Section {row['section_number']}: {row['section_title']}\n"

    prompt = f"""
You are an expert Ethiopian curriculum specialist.

Your task is to classify the following exam question into the correct Unit and Section of the Ethiopian New Curriculum for {subject_name} Grade {grade_number}.

**Question:**
{question_text}

**Official Curriculum Reference:**
{curriculum_context}

**Instructions:**
1.  Identify the most specific Unit and Section from the official curriculum provided above.
2.  You MUST select from the official curriculum items listed. Do NOT invent units or sections.
3.  Provide a confidence level: "High", "Medium", or "Low".
4.  Explain your reasoning briefly.
5.  Output the result in the following JSON format ONLY:

{{
    "unit_number": "Unit number (e.g., 1)",
    "unit_title": "Title of the unit from curriculum",
    "section_number": "Section number (e.g., 1.2)",
    "section_title": "Title of the section from curriculum",
    "confidence": "High/Medium/Low",
    "reason": "Brief reasoning for the classification."
}}

If the question does not clearly match any specific unit, select the most relevant one and set confidence to "Low".
"""
    try:
        response = client.models.generate_content(
            model="gemini-3.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.3
            )
        )
        if response.text:
            classification = json.loads(response.text)
            
            conn = get_db_connection()
            cursor = conn.cursor()
            param = get_param_style()

            unit_id = None
            section_id = None

            cursor.execute(f"""
                SELECT u.id FROM curriculum_units u
                JOIN curriculum_subjects s ON u.subject_id = s.id
                JOIN curriculum_grades g ON u.grade_id = g.id
                WHERE s.name = {param} AND g.number = {param} AND u.unit_number = {param}
            """, (subject_name, grade_number, classification.get('unit_number')))
            unit = cursor.fetchone()
            if unit:
                unit_id = unit['id']

            if unit_id:
                cursor.execute(f"""
                    SELECT id FROM curriculum_sections
                    WHERE unit_id = {param} AND section_number = {param}
                """, (unit_id, classification.get('section_number')))
                section = cursor.fetchone()
                if section:
                    section_id = section['id']

            cursor.close()
            conn.close()

            classification['unit_id'] = unit_id
            classification['section_id'] = section_id
            classification['confidence'] = classification.get('confidence', 'Low')
            
            return classification
    except Exception as e:
        print(f"ERROR in classify_question_with_curriculum: {e}")
        error_text = str(e)
        if "429" in error_text or "RESOURCE_EXHAUSTED" in error_text:
            retry_match = re.search(r"retryDelay['\"]?:\s*['\"]?([0-9.]+)s", error_text)
            cooldown_seconds = float(retry_match.group(1)) if retry_match else 60.0
            classification_retry_after = time.time() + cooldown_seconds
        return {
            "error": str(e),
            "confidence": "Low",
            "reason": "Classification error"
        }
    
    return {
        "error": "Classification failed.",
        "confidence": "Low",
        "reason": "No valid classification generated"
    }

# ============================================
# TELEGRAM MEMBERSHIP CHECKING
# ============================================

def check_telegram_channel_membership(user_id_or_handle):
    if not TELEGRAM_BOT_TOKEN:
        return True

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

# ============================================
# STATIC ROUTES
# ============================================

@app.route('/sw.js')
def service_worker():
    return send_from_directory('static', 'sw.js', mimetype='application/javascript')

@app.route('/ping')
def ping():
    return "OK", 200


@app.route('/profile-photo/<filename>')
@portal_or_unified_required
def profile_photo(filename):
    if not re.fullmatch(r"(?:exam_)?[a-f0-9]{32}\.(?:jpg|png|webp)", filename or ''):
        return "Not found", 404
    return send_from_directory(PROFILE_PHOTO_FOLDER, filename)


@app.route('/api/unified/login', methods=['POST'])
def unified_login():
    data = request.get_json(silent=True) or request.form
    username = str(data.get('username') or '').strip().lower()
    password = str(data.get('password') or '')
    expected_role = str(data.get('expected_role') or '').strip().lower()
    if expected_role not in ('', 'student', 'admin'):
        return jsonify({"success": False, "error": "Choose a valid Examination System sign-in type."}), 400
    conn = get_db_connection()
    cursor = conn.cursor()
    param = get_param_style()
    try:
        cursor.execute(f"SELECT * FROM unified_accounts WHERE username = {param}", (username,))
        account = cursor.fetchone()
    finally:
        cursor.close()
        conn.close()
    if not account or not check_password_hash(account['password_hash'], password):
        return jsonify({"success": False, "error": "Invalid Examination System username or password."}), 401
    if account['role'] not in ('student', 'admin'):
        return jsonify({"success": False, "error": "This account cannot sign in to the Examination System."}), 403
    if expected_role and account['role'] != expected_role:
        message = "Use the administrator sign-in option." if account['role'] == 'admin' else "Use the student sign-in option."
        return jsonify({"success": False, "error": message}), 403
    if account['role'] == 'student' and not str(account['student_code'] or '').startswith('EX'):
        return jsonify({"success": False, "error": "Register a separate Examination System student account to continue."}), 403
    if account['account_status'] != 'ACTIVE':
        return jsonify({"success": False, "error": "This Examination System account is not active."}), 403
    session['unified_account_id'] = account['id']
    session['unified_role'] = account['role']
    return jsonify({"success": True, "role": account['role'], "account": unified_account_dict(account)})


@app.route('/api/examination-system/register', methods=['POST'])
def examination_system_register():
    """Create a student account used only by the separate Examination System."""
    data = request.get_json(silent=True) or {}
    username = str(data.get('username') or '').strip().lower()
    first_name = normalize_person_name(data.get('first_name') or '')
    last_name = normalize_person_name(data.get('last_name') or '')
    password = str(data.get('password') or '')
    try:
        grade = int(data.get('grade_level'))
        age = int(data.get('age'))
    except (ValueError, TypeError):
        return jsonify({"success": False, "error": "Enter a valid age and grade level."}), 400
    sex = str(data.get('sex') or '').strip().upper()
    stream = str(data.get('stream') or '').strip().title()
    email = normalize_email(data.get('email'))
    phone = normalize_ethiopian_phone(data.get('phone_number')) if str(data.get('phone_number') or '').strip() else None
    photo_data = str(data.get('photo') or '')
    if not valid_username(username) or not valid_person_name(first_name) or not valid_person_name(last_name):
        return jsonify({"success": False, "error": "Enter a username, first name, and last name."}), 400
    if len(password) < 8 or not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        return jsonify({"success": False, "error": "Password must be at least 8 characters and include a letter and a number."}), 400
    if sex not in ('MALE', 'FEMALE') or not 13 <= age <= 25 or grade not in (9, 10, 11, 12):
        return jsonify({"success": False, "error": "Check gender, age, and grade level (Grades 9 to 12)."}), 400
    if grade in (11, 12) and stream not in ('Natural Science', 'Social Science'):
        return jsonify({"success": False, "error": "Select Natural Science or Social Science for Grades 11 and 12."}), 400
    if not email or not phone or not photo_data.startswith('data:image/'):
        return jsonify({"success": False, "error": "Email, mobile number, and a 3x4 profile photo are required."}), 400
    if len(photo_data) > 5 * 1024 * 1024:
        return jsonify({"success": False, "error": "Profile photo must be smaller than 4 MB."}), 413
    try:
        header, encoded = photo_data.split(',', 1)
        raw_photo = base64.b64decode(encoded, validate=True)
        image = Image.open(BytesIO(raw_photo)).convert('RGB')
        width, height = image.size
        if width < 3 or height < 4:
            raise ValueError("Photo is too small.")
        # Crop to the requested 3:4 portrait ratio and store a normalized JPEG.
        ratio = 3 / 4
        if width / height > ratio:
            crop_width = int(height * ratio)
            left = (width - crop_width) // 2
            image = image.crop((left, 0, left + crop_width, height))
        else:
            crop_height = int(width / ratio)
            top = (height - crop_height) // 2
            image = image.crop((0, top, width, top + crop_height))
        image.thumbnail((600, 800))
        photo_name = f"exam_{uuid.uuid4().hex}.jpg"
        image.save(os.path.join(PROFILE_PHOTO_FOLDER, photo_name), 'JPEG', quality=88)
    except Exception:
        return jsonify({"success": False, "error": "Upload a valid portrait photo for the 3x4 profile."}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    p = get_param_style()
    try:
        cursor.execute(f"SELECT 1 FROM unified_accounts WHERE username = {p}", (username,))
        if cursor.fetchone():
            return jsonify({"success": False, "error": "This Examination System username is already registered."}), 409
        cursor.execute(f"SELECT 1 FROM unified_accounts WHERE LOWER(email) = {p}", (email.lower(),))
        if cursor.fetchone():
            return jsonify({"success": False, "error": "This Examination System email is already registered."}), 409
        cursor.execute("SELECT student_code FROM unified_accounts WHERE student_code LIKE 'EX%' ORDER BY id DESC")
        used_codes = {str(row['student_code'] or '') for row in cursor.fetchall()}
        n = 1
        while f"EX{n:06d}" in used_codes:
            n += 1
        candidate_id = f"EX{n:06d}"
        cursor.execute(f"""INSERT INTO unified_accounts
            (username,password_hash,role,first_name,last_name,student_code,phone_number,email,sex,age,stream,grade_level,profile_photo,account_status)
            VALUES ({p},{p},'student',{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},'ACTIVE')""",
            (username, generate_password_hash(password), first_name, last_name, candidate_id, phone, email,
             sex, age, stream if grade in (11, 12) else '', grade, photo_name))
        conn.commit()
        cursor.execute(f"SELECT * FROM unified_accounts WHERE username = {p}", (username,))
        account = unified_account_dict(cursor.fetchone())
        session['unified_account_id'] = account['id']
        session['unified_role'] = 'student'
        return jsonify({"success": True, "role": "student", "account": account}), 201
    except Exception:
        conn.rollback()
        app.logger.exception("Examination System student registration failed")
        return jsonify({"success": False, "error": "Registration could not be completed. Check that the username and email are unique."}), 409
    finally:
        cursor.close()
        conn.close()


@app.route('/api/unified/student-login', methods=['POST'])
def unified_student_login():
    return jsonify({"success": False, "error": "Examination System students must sign in with their registered username and password."}), 410
    # Retained below only as a migration reference; this legacy Student Code
    # login is no longer available in the Examination System.
    data = request.get_json(silent=True) or request.form
    student_code = str(data.get('student_code') or data.get('code') or '').strip().upper()
    full_name = normalize_person_name(data.get('full_name') or data.get('name') or '')
    if not student_code or not full_name:
        return jsonify({"success": False, "error": "Student code and full name are required."}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    param = get_param_style()
    try:
        cursor.execute(f"SELECT * FROM users WHERE student_code = {param} AND role = 'student'", (student_code,))
        primary_user = cursor.fetchone()
        account = None
        if primary_user:
            if not is_active_student(primary_user):
                return jsonify({"success": False, "error": "This student account is not active."}), 401
            expected_name = normalize_person_name(f"{primary_user['first_name']} {primary_user['last_name']}")
            if full_name.casefold() != expected_name.casefold():
                return jsonify({"success": False, "error": "Full name does not match the approved student account."}), 401
            cursor.execute(f"SELECT * FROM unified_accounts WHERE student_code = {param} AND role = 'student'", (student_code,))
            account = cursor.fetchone()
            if account:
                unified_name = normalize_person_name(f"{account['first_name']} {account['last_name']}")
                if unified_name.casefold() != expected_name.casefold():
                    return jsonify({"success": False, "error": "This Student Code conflicts with an older Unified System account. Ask an administrator to resolve the duplicate."}), 409
            else:
                username = f"ev_student_{primary_user['id']}"
                cursor.execute(f"SELECT 1 FROM unified_accounts WHERE username = {param}", (username,))
                if cursor.fetchone():
                    username = f"ev_student_{primary_user['id']}_{uuid.uuid4().hex[:8]}"
                cursor.execute(f"""INSERT INTO unified_accounts
                    (username, password_hash, role, first_name, last_name, student_code, phone_number, email, account_status)
                    VALUES ({param}, {param}, 'student', {param}, {param}, {param}, {param}, {param}, 'ACTIVE')""",
                    (username, generate_password_hash(uuid.uuid4().hex), primary_user['first_name'],
                     primary_user['last_name'], student_code, primary_user['phone_number'], primary_user['email']))
                conn.commit()
                cursor.execute(f"SELECT * FROM unified_accounts WHERE student_code = {param} AND role = 'student'", (student_code,))
                account = cursor.fetchone()
        else:
            # Keep previously issued Unified System codes working while new registrations
            # use the main approved student record as their single source of identity.
            cursor.execute(f"SELECT * FROM unified_accounts WHERE student_code = {param} AND role = 'student'", (student_code,))
            account = cursor.fetchone()
            if not account or account['account_status'] != 'ACTIVE':
                return jsonify({"success": False, "error": "Invalid student code or inactive student account."}), 401
            expected_name = normalize_person_name(f"{account['first_name']} {account['last_name']}")
            if full_name.casefold() != expected_name.casefold():
                return jsonify({"success": False, "error": "Full name does not match the registered student account."}), 401
        session['unified_account_id'] = account['id']
        session['unified_role'] = account['role']
        return jsonify({"success": True, "role": account['role'], "account": unified_account_dict(account)})
    except Exception:
        conn.rollback()
        app.logger.exception("Unified student code login failed")
        return jsonify({"success": False, "error": "Could not verify this student account."}), 500
    finally:
        cursor.close()
        conn.close()


@app.route('/api/unified/logout', methods=['POST'])
def unified_logout():
    session.pop('unified_account_id', None)
    session.pop('unified_role', None)
    return jsonify({"success": True})


@app.route('/api/unified/me', methods=['GET'])
@unified_account_required
def unified_me():
    conn = get_db_connection()
    cursor = conn.cursor()
    param = get_param_style()
    cursor.execute(f"SELECT * FROM unified_accounts WHERE id = {param}", (session['unified_account_id'],))
    account = cursor.fetchone()
    cursor.close()
    conn.close()
    if not account:
        return jsonify({"error": "Unified System account not found."}), 404
    return jsonify(unified_account_dict(account))


@app.route('/api/examination-system/active-attempt', methods=['GET', 'PUT', 'DELETE'])
@unified_account_required
def examination_system_active_attempt():
    """Store one recoverable in-progress exam per signed-in Examination System account."""
    if session.get('unified_role') != 'student':
        return jsonify({"error": "Student access is required."}), 403
    conn = get_db_connection()
    try:
        ensure_unified_exam_table(conn)
        cur = conn.cursor()
        p = get_param_style()
        account_key = str(session['unified_account_id'])
        if request.method == 'GET':
            cur.execute(f"SELECT payload FROM unified_exam_records WHERE collection_name = {p} AND record_id = {p}",
                        ('active_attempts', account_key))
            row = cur.fetchone()
            payload = json.loads(row['payload'] if hasattr(row, 'keys') else row[0]) if row else None
            cur.close()
            return jsonify({"attempt": payload})
        if request.method == 'DELETE':
            cur.execute(f"DELETE FROM unified_exam_records WHERE collection_name = {p} AND record_id = {p}",
                        ('active_attempts', account_key))
            conn.commit()
            cur.close()
            return jsonify({"success": True})
        body = request.get_json(silent=True) or {}
        attempt = body.get('attempt')
        if not isinstance(attempt, dict) or not isinstance(attempt.get('e'), dict) or not isinstance(attempt['e'].get('questions'), list):
            cur.close()
            return jsonify({"error": "A valid active examination is required."}), 400
        payload = json.dumps(attempt, ensure_ascii=False, separators=(',', ':'))
        if len(payload.encode('utf-8')) > 4 * 1024 * 1024:
            cur.close()
            return jsonify({"error": "This active exam is too large to save."}), 413
        cur.execute(f"""INSERT INTO unified_exam_records (collection_name, record_id, payload, updated_at)
            VALUES ({p}, {p}, {p}, CURRENT_TIMESTAMP)
            ON CONFLICT (collection_name, record_id) DO UPDATE SET payload = excluded.payload, updated_at = CURRENT_TIMESTAMP""",
            ('active_attempts', account_key, payload))
        conn.commit()
        cur.close()
        return jsonify({"success": True})
    except Exception:
        conn.rollback()
        app.logger.exception("Examination System attempt persistence failed")
        return jsonify({"error": "Could not save or restore the active examination."}), 500
    finally:
        conn.close()


def validate_unified_account_payload(data, require_password=False):
    username = str(data.get('username') or '').strip().lower()
    first_name = normalize_person_name(data.get('first_name') or '')
    last_name = normalize_person_name(data.get('last_name') or '')
    password = str(data.get('password') or '')
    if not valid_username(username):
        raise ValueError("Enter a username using 1 to 100 characters.")
    if not valid_person_name(first_name) or not valid_person_name(last_name):
        raise ValueError("Enter a valid first and last name.")
    if require_password and (len(password) < 8 or not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password)):
        raise ValueError("Password must be at least 8 characters and include a letter and a number.")
    return username, first_name, last_name, password


@app.route('/api/unified/students', methods=['GET'])
@unified_admin_required
def unified_students():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM unified_accounts WHERE role = 'student' AND account_status = 'ACTIVE' AND student_code LIKE 'EX%' ORDER BY id")
    accounts = [unified_account_dict(row) for row in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify(accounts)


@app.route('/api/unified/students', methods=['POST'])
@unified_admin_required
def create_unified_student():
    data = request.get_json(silent=True) or {}
    try:
        username, first_name, last_name, password = validate_unified_account_payload(data, True)
        phone_number = normalize_ethiopian_phone(data.get('phone_number')) if str(data.get('phone_number') or '').strip() else None
        email_address = normalize_email(data.get('email'))
        if not email_address:
            raise ValueError('Enter a valid email address.')
        age = int(data.get('age')) if str(data.get('age') or '').strip() else None
    except (ValueError, TypeError) as error:
        return jsonify({"success": False, "error": str(error)}), 400
    conn = get_db_connection()
    cursor = conn.cursor()
    param = get_param_style()
    try:
        cursor.execute(f"SELECT 1 FROM unified_accounts WHERE username = {param}", (username,))
        if cursor.fetchone():
            return jsonify({"success": False, "error": "This username is already registered in the Examination System."}), 409
        if phone_number and phone_is_registered(cursor, phone_number):
            return jsonify({"success": False, "error": "This phone number is already registered."}), 409
        if email_address:
            cursor.execute(f"SELECT 1 FROM unified_accounts WHERE LOWER(email) = {param}", (email_address.lower(),))
            if cursor.fetchone():
                return jsonify({"success": False, "error": "This email is already registered in the Examination System."}), 409
        cursor.execute("SELECT student_code FROM unified_accounts WHERE student_code LIKE 'EX%' ORDER BY id DESC")
        used_codes = {str(row['student_code'] or '') for row in cursor.fetchall()}
        number = 1
        while f"EX{number:06d}" in used_codes:
            number += 1
        code = f"EX{number:06d}"
        password_hash = generate_password_hash(password)
        cursor.execute(f"""INSERT INTO unified_accounts
            (username, password_hash, role, first_name, last_name, student_code, phone_number, email, sex, age, stream)
            VALUES ({param}, {param}, 'student', {param}, {param}, {param}, {param}, {param}, {param}, {param}, {param})""",
            (username, password_hash, first_name, last_name, code, phone_number, email_address,
             str(data.get('sex') or ''), age, str(data.get('stream') or 'Natural Sc.')))
        conn.commit()
        cursor.execute(f"SELECT * FROM unified_accounts WHERE username = {param}", (username,))
        account = cursor.fetchone()
        result = {"success": True, "message": "Student account created in the Examination System.",
                  "account": unified_account_dict(account)}
        return jsonify(result), 201
    except Exception as error:
        conn.rollback()
        return jsonify({"success": False, "error": "Username or Examination System ID is already registered."}), 409
    finally:
        cursor.close()
        conn.close()


def next_student_code_for_unified():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        return next_student_code(cursor)
    finally:
        cursor.close()
        conn.close()


@app.route('/api/unified/students/<int:account_id>', methods=['PUT'])
@unified_account_required
def update_unified_student(account_id):
    if session.get('unified_role') != 'admin' and account_id != session.get('unified_account_id'):
        return jsonify({"error": "You can edit only your own account."}), 403
    data = request.get_json(silent=True) or {}
    conn = get_db_connection()
    cursor = conn.cursor()
    param = get_param_style()
    try:
        fields = ['first_name', 'last_name', 'sex', 'age', 'stream']
        values = [normalize_person_name(data.get('first_name') or ''), normalize_person_name(data.get('last_name') or ''), str(data.get('sex') or ''), int(data['age']) if str(data.get('age') or '').strip() else None, str(data.get('stream') or 'Natural Sc.')]
        if not valid_person_name(values[0]) or not valid_person_name(values[1]):
            return jsonify({"error": "Enter a valid first and last name."}), 400
        if session.get('unified_role') == 'admin' and data.get('username'):
            fields.insert(0, 'username')
            values.insert(0, str(data['username']).strip().lower())
        if data.get('password'):
            password = str(data['password'])
            if len(password) < 8 or not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
                return jsonify({"error": "Password must be at least 8 characters and include a letter and a number."}), 400
            fields.append('password_hash')
            values.append(generate_password_hash(password))
        assignments = ', '.join(f"{field} = {param}" for field in fields)
        values.append(account_id)
        cursor.execute(f"UPDATE unified_accounts SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE id = {param} AND role = 'student'", values)
        if cursor.rowcount != 1:
            return jsonify({"error": "Student account not found."}), 404
        cursor.execute(f"SELECT student_code FROM unified_accounts WHERE id = {param}", (account_id,))
        linked = cursor.fetchone()
        if linked and linked['student_code']:
            cursor.execute(f"UPDATE users SET first_name = {param}, last_name = {param} WHERE student_code = {param} AND role = 'student'",
                           (values[fields.index('first_name')], values[fields.index('last_name')], linked['student_code']))
        conn.commit()
        cursor.execute(f"SELECT * FROM unified_accounts WHERE id = {param}", (account_id,))
        return jsonify({"success": True, "account": unified_account_dict(cursor.fetchone())})
    except (ValueError, TypeError):
        conn.rollback()
        return jsonify({"error": "Invalid account data."}), 400
    except Exception:
        conn.rollback()
        return jsonify({"error": "Username is already registered."}), 409
    finally:
        cursor.close()
        conn.close()


@app.route('/api/unified/students/<int:account_id>', methods=['DELETE'])
@unified_admin_required
def delete_unified_student(account_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    param = get_param_style()
    cursor.execute(f"DELETE FROM unified_accounts WHERE id = {param} AND role = 'student'", (account_id,))
    conn.commit()
    deleted = cursor.rowcount == 1
    cursor.close()
    conn.close()
    return jsonify({"success": deleted, "error": None if deleted else "Student account not found."}), (200 if deleted else 404)

# ============================================
# AUTHENTICATION ROUTES
# ============================================

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        first_name = normalize_person_name(request.form.get('first_name'))
        last_name = normalize_person_name(request.form.get('last_name'))
        username = request.form.get('username', '').strip().lower()
        password = request.form.get('password', '')
        try:
            phone_value = request.form.get('phone_number')
            phone_number = normalize_ethiopian_phone(phone_value) if str(phone_value or '').strip() else None
            email_address = normalize_email(request.form.get('email'))
            if not email_address:
                raise ValueError('Enter an email address so we can send your Student Code.')
        except ValueError as error:
            flash(str(error), "error")
            return render_template('signup.html')

        if not valid_person_name(first_name) or not valid_person_name(last_name):
            flash("Enter a valid first and last name using 2 to 50 letters.", "error")
            return render_template('signup.html')
        if not valid_username(username):
            flash("Enter a username using 1 to 100 characters.", "error")
            return render_template('signup.html')
        if len(password) < 8 or not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
            flash("Password must be at least 8 characters and include a letter and a number.", "error")
            return render_template('signup.html')
        conn = get_db_connection()
        cursor = conn.cursor()
        param = get_param_style()
        try:
            if phone_is_registered(cursor, phone_number):
                flash("This phone number already has a student registration. Contact an administrator if this is a duplicate.", "error")
                return render_template('signup.html')
            if email_is_registered(cursor, email_address):
                flash("This email address already has a student registration. Contact an administrator if this is a duplicate.", "error")
                return render_template('signup.html')
            cursor.execute(
                f'''INSERT INTO users
                    (username, password_hash, role, first_name, last_name, profile_photo, phone_number, email,
                     account_status, is_verified, registered_at)
                    VALUES ({param}, {param}, {param}, {param}, {param}, {param}, {param}, {param}, {param}, {param}, CURRENT_TIMESTAMP)''',
                (username, generate_password_hash(password), 'student', first_name, last_name,
                 None, phone_number, email_address, 'PENDING_APPROVAL', 0)
            )
            conn.commit()
            flash("Registration submitted. An administrator must approve your account before you can log in.", "success")
            return redirect(url_for('login'))
        except Exception:
            conn.rollback()
            flash("That username or phone number is already registered. Check the details or contact an administrator.", "error")
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
        param = get_param_style()
        cursor.execute(f'SELECT * FROM users WHERE username = {param}', (username,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if user and check_password_hash(user['password_hash'], password):
            if user['role'] == 'student' and user['account_status'] != 'ACTIVE':
                status_message = {
                    'PENDING_APPROVAL': "Your registration is waiting for administrator approval.",
                    'REJECTED': "Your registration was rejected. Please contact an administrator.",
                }.get(user['account_status'], "Your account is not active yet.")
                flash(status_message, "error")
                return render_template('login.html')
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

# ============================================
# MAIN WEB PAGE ROUTES
# ============================================

@app.route('/')
@login_required
def index():
    return render_template('index.html', username=session.get('username'), role=session.get('role'))

@app.route('/eduvault-system')
def eduvault_system():
    return render_template(
        'eduvault_system.html',
        flask_role='',
        flask_student=None,
    )

@app.route('/resources')
@app.route('/resources/<collection>')
@portal_or_unified_required
def resources_hub(collection='textbooks'):
    collections = {
        'textbooks': ('Textbooks', 'Open the student textbooks available for your grade and subject.'),
        'notes': ('Short Notes', 'Read concise revision notes published by the EduVault team.'),
        'explanations': ('Explanations', 'Review explanations saved from your completed exams.'),
    }
    if collection not in collections:
        abort(404)
    title, description = collections[collection]
    return render_template('resources.html', username=session.get('username'), role=session.get('role', 'student'),
                           collection=collection, collection_title=title, collection_description=description)

@app.route('/worksheets')
@login_required
def worksheets_page():
    return render_template('subject.html', subject_name='Practical Questions')

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
    conn = get_db_connection()
    cur = conn.cursor()
    p = get_param_style()
    cur.execute(f"SELECT duration_minutes FROM exams WHERE id = {p}", (exam_id,))
    exam_row = cur.fetchone()
    cur.close()
    conn.close()
    duration_minutes = exam_row['duration_minutes'] if exam_row else None
    return render_template('exam.html', exam_id=exam_id, exam_duration_minutes=duration_minutes or 0, exam_access_granted=exam_access_allowed(exam_id), verify_required=request.args.get('verify') == 'required')


@app.route('/exam/<int:exam_id>/verify', methods=['POST'])
@login_required
def verify_exam_identity(exam_id):
    if session.get('role') == 'admin':
        session['exam_verified_user_id'] = session['user_id']
        session['exam_verified_exam_id'] = exam_id
        return redirect(url_for('exam_page', exam_id=exam_id))
    user = get_user_by_id(session['user_id'])
    full_name = normalize_person_name(request.form.get('full_name'))
    student_code = request.form.get('student_code', '').strip().upper()
    expected_name = normalize_person_name(f"{user['first_name']} {user['last_name']}") if user else ''
    if not is_active_student(user):
        flash("Your account must be approved before entering an examination.", "error")
    elif full_name.casefold() != expected_name.casefold():
        flash("Full name does not match the approved student profile.", "error")
    elif student_code != str(user['student_code']).upper():
        flash("Student code is invalid for this account. Obtain the code from an administrator.", "error")
    else:
        session['exam_verified_user_id'] = user['id']
        session['exam_verified_exam_id'] = exam_id
        return redirect(url_for('exam_page', exam_id=exam_id))
    return redirect(url_for('exam_page', exam_id=exam_id, verify='required'))

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

@app.route('/study/<int:material_id>')
@login_required
def study_material_console(material_id):
    return render_template('study_material.html', material_id=material_id)

@app.route('/admin/review/<int:pending_exam_id>')
@admin_required
def review_pending_exam_page(pending_exam_id):
    return render_template('review_exam.html', pending_exam_id=pending_exam_id)

# ============================================
# API ENDPOINTS
# ============================================

@app.route('/api/admin/students/pending', methods=['GET'])
@admin_required
def get_pending_students():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, first_name, last_name, username, profile_photo, phone_number, email,
               registered_at, account_status
        FROM users
        WHERE role = 'student' AND account_status = 'PENDING_APPROVAL'
        ORDER BY registered_at ASC, id ASC
    """)
    students = []
    for row in cursor.fetchall():
        item = dict(row)
        item['full_name'] = normalize_person_name(f"{item.get('first_name') or ''} {item.get('last_name') or ''}")
        item['photo_url'] = url_for('profile_photo', filename=item['profile_photo']) if item.get('profile_photo') else None
        students.append(item)
    cursor.close()
    conn.close()
    return jsonify(students)


@app.route('/api/admin/students', methods=['POST'])
@admin_required
def add_student_by_admin():
    data = request.get_json(silent=True) or request.form
    first_name = normalize_person_name(data.get('first_name'))
    last_name = normalize_person_name(data.get('last_name'))
    username = str(data.get('username') or '').strip().lower()
    password = str(data.get('password') or '')
    try:
        phone_number = normalize_ethiopian_phone(data.get('phone_number')) if str(data.get('phone_number') or '').strip() else None
        email_address = normalize_email(data.get('email'))
        if not email_address:
            raise ValueError('Enter an email address for Student Code delivery.')
    except ValueError as error:
        return jsonify({"success": False, "error": str(error)}), 400

    if not valid_person_name(first_name) or not valid_person_name(last_name):
        return jsonify({"success": False, "error": "Enter a valid first and last name."}), 400
    if not valid_username(username):
        return jsonify({"success": False, "error": "Enter a username using 1 to 100 characters."}), 400
    if len(password) < 8 or not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        return jsonify({"success": False, "error": "Password must be at least 8 characters and include a letter and a number."}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    param = get_param_style()
    try:
        if phone_is_registered(cursor, phone_number):
            return jsonify({"success": False, "error": "This phone number already has a student registration."}), 409
        if email_is_registered(cursor, email_address):
            return jsonify({"success": False, "error": "This email address already has a student registration."}), 409
        cursor.execute(f"SELECT id FROM users WHERE username = {param}", (username,))
        if cursor.fetchone():
            return jsonify({"success": False, "error": "That username is already registered."}), 409

        code = next_student_code(cursor)
        insert_sql = f'''
            INSERT INTO users
                (username, password_hash, role, first_name, last_name, student_code, phone_number, email,
                 account_status, is_verified, registered_at, approved_at)
            VALUES ({param}, {param}, {param}, {param}, {param}, {param}, {param}, {param},
                    {param}, {param}, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        '''
        if is_postgres():
            insert_sql += " RETURNING id"
        cursor.execute(insert_sql, (
            username, generate_password_hash(password), 'student', first_name,
            last_name, code, phone_number, email_address, 'ACTIVE', 1
        ))
        user_id = cursor.fetchone()['id'] if is_postgres() else cursor.lastrowid
        sync_user_to_unified_student(cursor, user_id, first_name, last_name, code, phone_number, email_address)
        conn.commit()
        try:
            send_student_code_email(email_address, code)
        except RuntimeError as delivery_error:
            cursor.execute(f"""UPDATE users SET account_status = 'PENDING_APPROVAL',
                is_verified = 0, approved_at = NULL WHERE username = {param}""", (username,))
            cursor.execute(f"UPDATE unified_accounts SET account_status = 'PENDING_APPROVAL' WHERE username = {param}", (f"ev_student_{user_id}",))
            conn.commit()
            return jsonify({"success": False, "error": f"Code delivery failed; the account was left pending. {delivery_error}"}), 502
        response_data = {
            "success": True,
            "message": "Student added and activated.",
            "delivery_method": 'email',
            "username": username,
            "full_name": normalize_person_name(f"{first_name} {last_name}")
        }
        response_data['message'] = "Student added and activated. The shared Student Code was sent by email."
        return jsonify(response_data), 201
    except Exception as error:
        conn.rollback()
        return jsonify({"success": False, "error": str(error)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route('/api/admin/students/<int:user_id>/approve', methods=['POST'])
@admin_required
def approve_student(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    param = get_param_style()
    try:
        cursor.execute(f"SELECT id, role, account_status, student_code, phone_number, email, first_name, last_name FROM users WHERE id = {param}", (user_id,))
        student = cursor.fetchone()
        if not student or student['role'] != 'student':
            return jsonify({"success": False, "error": "Student registration not found."}), 404
        if student['account_status'] == 'ACTIVE' and student['student_code']:
            return jsonify({"success": True, "message": "Student is already approved."})
        if student['account_status'] != 'PENDING_APPROVAL':
            return jsonify({"success": False, "error": "Only pending registrations can be approved."}), 409
        if not student['email']:
            return jsonify({"success": False, "error": "This registration has no email address for code delivery."}), 409
        code = student['student_code'] or next_student_code(cursor)
        cursor.execute(f"""
            UPDATE users
            SET account_status = {param}, student_code = {param}, is_verified = {param}, approved_at = CURRENT_TIMESTAMP
            WHERE id = {param} AND role = 'student' AND account_status = 'PENDING_APPROVAL'
        """, ('ACTIVE', code, 1, user_id))
        if cursor.rowcount != 1:
            conn.rollback()
            return jsonify({"success": False, "error": "Registration changed before approval. Refresh and try again."}), 409
        sync_user_to_unified_student(cursor, user_id, student['first_name'], student['last_name'], code,
                                     student['phone_number'], student['email'])
        conn.commit()
        try:
            send_student_code_email(student['email'], code)
        except RuntimeError as delivery_error:
            cursor.execute(f"""UPDATE users SET account_status = 'PENDING_APPROVAL',
                is_verified = 0, approved_at = NULL WHERE id = {param} AND student_code = {param}""", (user_id, code))
            cursor.execute(f"UPDATE unified_accounts SET account_status = 'PENDING_APPROVAL' WHERE username = {param}",
                           (f"ev_student_{user_id}",))
            conn.commit()
            app.logger.warning("Student approval email failed for user id %s: %s", user_id, delivery_error)
            return jsonify({"success": False, "error": f"Code delivery failed, so this student remains pending. {delivery_error}"}), 502
        response_data = {"success": True, "message": "Student approved. The shared Student Code was sent by email.", "delivery_method": 'email'}
        return jsonify(response_data)
    except Exception as error:
        conn.rollback()
        return jsonify({"success": False, "error": str(error)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route('/api/admin/students/<int:user_id>/contact', methods=['PUT'])
@admin_required
def update_pending_student_contact(user_id):
    data = request.get_json(silent=True) or {}
    try:
        phone_raw = data.get('phone_number')
        phone_number = normalize_ethiopian_phone(phone_raw) if str(phone_raw or '').strip() else None
        email_address = normalize_email(data.get('email'))
        if not email_address:
            raise ValueError('Enter an email address for Student Code delivery.')
    except ValueError as error:
        return jsonify({"success": False, "error": str(error)}), 400
    conn = get_db_connection()
    cursor = conn.cursor()
    p = get_param_style()
    mirror_username = f"ev_student_{user_id}"
    try:
        cursor.execute(f"SELECT username, role, account_status FROM users WHERE id = {p}", (user_id,))
        student = cursor.fetchone()
        if not student or student['role'] != 'student' or student['account_status'] != 'PENDING_APPROVAL':
            return jsonify({"success": False, "error": "Only pending student registrations can be edited."}), 409
        for table, exclusion_sql, exclusion_value in (
            ('users', f"id <> {p}", user_id),
            ('unified_accounts', f"username <> {p}", mirror_username),
        ):
            if phone_number:
                cursor.execute(f"SELECT 1 FROM {table} WHERE phone_number = {p} AND {exclusion_sql} LIMIT 1",
                               (phone_number, exclusion_value))
                if cursor.fetchone():
                    return jsonify({"success": False, "error": "This phone number belongs to another student."}), 409
            if email_address:
                cursor.execute(f"SELECT 1 FROM {table} WHERE LOWER(email) = {p} AND {exclusion_sql} LIMIT 1",
                               (email_address, exclusion_value))
                if cursor.fetchone():
                    return jsonify({"success": False, "error": "This email address belongs to another student."}), 409
        cursor.execute(f"UPDATE users SET phone_number = {p}, email = {p} WHERE id = {p}",
                       (phone_number, email_address, user_id))
        cursor.execute(f"UPDATE unified_accounts SET phone_number = {p}, email = {p} WHERE username = {p}",
                       (phone_number, email_address, mirror_username))
        conn.commit()
        return jsonify({"success": True, "message": "Student delivery contact updated."})
    except Exception:
        conn.rollback()
        app.logger.exception("Could not update pending student contact for id %s", user_id)
        return jsonify({"success": False, "error": "Could not update this student's contact details."}), 500
    finally:
        cursor.close()
        conn.close()


@app.route('/api/admin/students/<int:user_id>/reject', methods=['POST'])
@admin_required
def reject_student(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    param = get_param_style()
    try:
        cursor.execute(f"""
            UPDATE users
            SET account_status = {param}, is_verified = {param}, rejected_at = CURRENT_TIMESTAMP
            WHERE id = {param} AND role = 'student' AND account_status = 'PENDING_APPROVAL'
        """, ('REJECTED', 0, user_id))
        if cursor.rowcount != 1:
            conn.rollback()
            return jsonify({"success": False, "error": "Only pending registrations can be rejected."}), 409
        cursor.execute(f"UPDATE unified_accounts SET account_status = 'REJECTED' WHERE username = {param}",
                       (f"ev_student_{user_id}",))
        conn.commit()
        return jsonify({"success": True, "message": "Student registration rejected."})
    except Exception as error:
        conn.rollback()
        return jsonify({"success": False, "error": str(error)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route('/api/profile', methods=['GET'])
@login_required
def get_profile():
    user = get_user_by_id(session['user_id'])
    if not user:
        return jsonify({"error": "Account not found."}), 404
    profile = dict(user)
    profile.pop('password_hash', None)
    profile['full_name'] = normalize_person_name(f"{profile.get('first_name') or ''} {profile.get('last_name') or ''}")
    if profile.get('profile_photo'):
        profile['photo_url'] = url_for('profile_photo', filename=profile['profile_photo'])
    return jsonify(profile)


@app.route('/api/verify-student-identity', methods=['POST'])
@login_required
def verify_student_identity():
    if session.get('role') != 'student':
        return jsonify({"success": False, "error": "Student verification is only available for student accounts."}), 403
    data = request.get_json(silent=True) or {}
    full_name = normalize_person_name(data.get('full_name'))
    student_code = str(data.get('student_code') or '').strip().upper()
    user = get_user_by_id(session['user_id'])
    expected_name = normalize_person_name(f"{user['first_name']} {user['last_name']}") if user else ''
    if not is_active_student(user):
        return jsonify({"success": False, "error": "Your account is not approved or active."}), 403
    if full_name.casefold() != expected_name.casefold():
        return jsonify({"success": False, "error": "Full name does not match your registered account."}), 403
    if student_code != str(user['student_code']).upper():
        return jsonify({"success": False, "error": "Student Code is invalid for this account."}), 403
    session['unified_exam_verified_user_id'] = user['id']
    return jsonify({"success": True, "student": {"code": user['student_code'], "name": expected_name, "photo": url_for('profile_photo', filename=user['profile_photo']) if user['profile_photo'] else ''}})

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
        
    now = time.time()
    session_key = f"verify_started_{task_type}"
    started_at = session.get(session_key)
    
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
    if elapsed < 10:
        remaining = max(1, int(10 - elapsed + 0.999))
        return jsonify({
            "success": False,
            "waiting": True,
            "remaining": remaining,
            "error": f"Please wait {remaining} more seconds."
        }), 202

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
    elif task_type == "bot":
        message = "Bot task verified!"
    elif task_type == "youtube":
        message = "YouTube task verified!"
    elif task_type == "group_invites":
        message = "Group invite task verified!"
    else:
        return jsonify({"success": False, "error": "Invalid task type"}), 400

    session.pop(session_key, None)
    session.modified = True
    return jsonify({
        "success": True,
        "message": message
    })

# ============================================
# EXAM AND QUESTION API
# ============================================

@app.route('/api/exams', methods=['GET'])
@login_required
def get_exams():
    conn = get_db_connection()
    cursor = conn.cursor()
    param = get_param_style()
    filters = []
    values = []
    destination = request.args.get('destination', '').strip().lower()
    if destination:
        kinds = [kind for kind in EXAMINATION_TYPES if examination_destination(kind) == destination]
        if not kinds:
            cursor.close()
            conn.close()
            return jsonify({"error": "Unknown examination destination."}), 400
        filters.append(f"e.examination_type IN ({', '.join([param] * len(kinds))})")
        values.extend(kinds)
    for query_key, column in (("examination_type", "e.examination_type"), ("subject", "e.subject"), ("grade", "e.grade"), ("academic_year", "e.academic_year")):
        value = request.args.get(query_key)
        if value:
            if query_key == "grade":
                try:
                    value = int(value)
                except ValueError:
                    cursor.close()
                    conn.close()
                    return jsonify({"error": "Grade must be a number."}), 400
            filters.append(f"{column} = {param}")
            values.append(value)
    title = request.args.get('title', '').strip()
    if title:
        filters.append(f"LOWER(e.title) LIKE {param}")
        values.append(f"%{title.casefold()}%")
    where_sql = f"WHERE {' AND '.join(filters)}" if filters else ""
    cursor.execute(f'''
        SELECT e.*, r.file_url, r.pdf_url 
        FROM exams e
        LEFT JOIN resources r ON e.resource_id = r.id
        {where_sql}
        ORDER BY e.id DESC
    ''', tuple(values))
    exams = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify([dict(exam) for exam in exams])


@app.route('/api/exams/<int:exam_id>/attempts/start', methods=['POST'])
@login_required
@exam_access_required
def start_exam_attempt(exam_id):
    data = request.get_json(silent=True) or {}
    requested_mode = str(data.get('mode') or 'exam').strip().lower()
    if requested_mode not in ('practice', 'exam'):
        return jsonify({"error": "Choose Practice Mode or Exam Mode."}), 400
    conn = get_db_connection()
    cur = conn.cursor()
    p = get_param_style()
    user_id = session.get('user_id')
    try:
        cur.execute(f"SELECT id, duration_minutes, scope_unit_id, scope_section_id FROM exams WHERE id = {p}", (exam_id,))
        exam = cur.fetchone()
        if not exam:
            return jsonify({"error": "Exam not found."}), 404
        scope_sql, scope_values = exam_question_scope(exam, p)
        cur.execute(f"SELECT COUNT(*) AS total FROM questions q WHERE {scope_sql}", scope_values)
        total = int(cur.fetchone()['total'] or 0)
        if not total:
            return jsonify({"error": "This exam has no questions."}), 400
        cur.execute(f"SELECT * FROM exam_attempts WHERE user_id = {p} AND exam_id = {p} AND status = 'in_progress' AND examination_mode = {p} ORDER BY id DESC LIMIT 1", (user_id, exam_id, requested_mode))
        attempt = cur.fetchone()
        now = time.time()
        if attempt:
            attempt_id = attempt['id']
            mode = attempt['examination_mode']
            started_at = float(attempt['started_at_epoch'])
            duration = int(attempt['duration_seconds'])
            resumed = True
        else:
            mode = requested_mode
            minutes = int(exam['duration_minutes'] or 0)
            duration = minutes * 60 if minutes > 0 else total * 90
            started_at = now
            resumed = False
            sql = f"INSERT INTO exam_attempts (user_id, exam_id, examination_mode, started_at_epoch, duration_seconds, status) VALUES ({', '.join([p] * 5)}, 'in_progress')"
            if is_postgres():
                cur.execute(sql + " RETURNING id", (user_id, exam_id, mode, started_at, duration))
                attempt_id = cur.fetchone()['id']
            else:
                cur.execute(sql, (user_id, exam_id, mode, started_at, duration))
                attempt_id = cur.lastrowid
            conn.commit()
        cur.execute(f"SELECT question_id, selected_answer, is_flagged FROM attempt_answers WHERE attempt_id = {p}", (attempt_id,))
        answers = {str(row['question_id']): {"answer": row['selected_answer'], "flagged": bool(row['is_flagged'])} for row in cur.fetchall()}
        remaining = remaining_exam_seconds(started_at, duration, now) if mode == 'exam' else None
        return jsonify({"success": True, "attempt_id": attempt_id, "mode": mode, "resumed": resumed,
                        "started_at": started_at, "duration_seconds": duration, "remaining_seconds": remaining,
                        "total_questions": total, "answers": answers})
    except Exception:
        conn.rollback()
        app.logger.exception("Could not start examination attempt")
        return jsonify({"error": "Could not start this examination."}), 500
    finally:
        cur.close()
        conn.close()


@app.route('/api/exam-attempts/<int:attempt_id>/answers/<int:question_id>', methods=['PUT'])
@login_required
def save_exam_attempt_answer(attempt_id, question_id):
    data = request.get_json(silent=True) or {}
    answer = data.get('answer')
    if answer is not None:
        answer = str(answer).upper()
        if answer not in ('A', 'B', 'C', 'D'):
            return jsonify({"error": "Select one of the available answer options."}), 400
    flagged = int(bool(data.get('flagged', False)))
    conn = get_db_connection()
    cur = conn.cursor()
    p = get_param_style()
    try:
        cur.execute(f"SELECT * FROM exam_attempts WHERE id = {p} AND user_id = {p}", (attempt_id, session.get('user_id')))
        attempt = cur.fetchone()
        if not attempt or not exam_access_allowed(attempt['exam_id']):
            return jsonify({"error": "Examination attempt not found or access denied."}), 403
        if attempt['status'] != 'in_progress':
            return jsonify({"error": "This examination has already been submitted."}), 409
        if attempt['examination_mode'] == 'exam' and time.time() >= float(attempt['started_at_epoch']) + int(attempt['duration_seconds']):
            return jsonify({"error": "The examination time has expired."}), 409
        cur.execute(f"SELECT id, scope_unit_id, scope_section_id FROM exams WHERE id = {p}", (attempt['exam_id'],))
        exam_scope = cur.fetchone()
        scope_sql, scope_values = exam_question_scope(exam_scope, p)
        cur.execute(f"SELECT q.id FROM questions q WHERE q.id = {p} AND {scope_sql}", (question_id, *scope_values))
        if not cur.fetchone():
            return jsonify({"error": "Question does not belong to this examination."}), 404
        now = time.time()
        sql = f"INSERT INTO attempt_answers (attempt_id, question_id, selected_answer, is_flagged, answered_at_epoch) VALUES ({p}, {p}, {p}, {p}, {p}) ON CONFLICT (attempt_id, question_id) DO UPDATE SET selected_answer = excluded.selected_answer, is_flagged = excluded.is_flagged, answered_at_epoch = excluded.answered_at_epoch"
        cur.execute(sql, (attempt_id, question_id, answer, flagged, now))
        conn.commit()
        return jsonify({"success": True})
    except Exception:
        conn.rollback()
        app.logger.exception("Could not save examination answer")
        return jsonify({"error": "Could not save the answer."}), 500
    finally:
        cur.close()
        conn.close()

@app.route('/api/exams/<int:exam_id>/questions', methods=['GET'])
@login_required
@exam_access_required
def get_questions(exam_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    param = get_param_style()
    attempt_id = request.args.get('attempt_id', type=int)
    if not attempt_id:
        cursor.close()
        conn.close()
        return jsonify({"error": "Start or resume an examination attempt first."}), 400
    cursor.execute(f"SELECT examination_mode, status FROM exam_attempts WHERE id = {param} AND exam_id = {param} AND user_id = {param}",
                   (attempt_id, exam_id, session.get('user_id')))
    attempt = cursor.fetchone()
    if not attempt or attempt['status'] != 'in_progress':
        cursor.close()
        conn.close()
        return jsonify({"error": "Active examination attempt not found."}), 403
    practice_mode = attempt['examination_mode'] == 'practice'
    cursor.execute(f"SELECT id, scope_unit_id, scope_section_id FROM exams WHERE id = {param}", (exam_id,))
    exam_scope = cursor.fetchone()
    scope_sql, scope_values = exam_question_scope(exam_scope, param)
    cursor.execute(f'''
        SELECT q.id, q.question_number, q.question_text, q.option_a, q.option_b, q.option_c, q.option_d,
               q.passage_text, q.diagram_instruction,
               {'q.correct_answer, q.explanation,' if practice_mode else ''}
               u.unit_number, u.title as unit_title,
               s.section_number, s.title as section_title
        FROM questions q
        LEFT JOIN curriculum_units u ON q.curriculum_unit_id = u.id
        LEFT JOIN curriculum_sections s ON q.curriculum_section_id = s.id
        WHERE {scope_sql}
        ORDER BY q.id ASC
    ''', scope_values)
    questions = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify([dict(q) for q in questions])

@app.route('/api/questions/<int:question_id>', methods=['GET'])
@login_required
def get_single_question(question_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    param = get_param_style()
    cursor.execute(f"SELECT * FROM questions WHERE id = {param}", (question_id,))
    question = cursor.fetchone()
    cursor.close()
    conn.close()
    if question:
        payload = dict(question)
        if session.get('role') != 'admin':
            payload.pop('correct_answer', None)
            payload.pop('explanation', None)
        return jsonify(payload)
    return jsonify({"error": "Question not found"}), 404

# ============================================
# CHAPTER AND CURRICULUM API
# ============================================

@app.route('/api/chapters/<subject>', methods=['GET'])
@login_required
def get_chapters(subject):
    grade = request.args.get('grade', 12)
    conn = get_db_connection()
    cursor = conn.cursor()
    param = get_param_style()
    
    cursor.execute(f'''
        SELECT DISTINCT u.id as unit_id, u.unit_number, u.title as name,
               COUNT(DISTINCT q.id) as question_count,
               COUNT(DISTINCT s.id) as section_count
        FROM curriculum_units u
        JOIN curriculum_subjects cs ON u.subject_id = cs.id
        JOIN curriculum_grades g ON u.grade_id = g.id
        LEFT JOIN curriculum_sections s ON u.id = s.unit_id
        LEFT JOIN questions q ON q.curriculum_unit_id = u.id
        WHERE cs.name = {param} AND g.number = {param}
        GROUP BY u.id, u.unit_number, u.title
        ORDER BY u.unit_number
    ''', (subject, grade))
    
    chaps = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify([dict(c) for c in chaps])

@app.route('/api/curriculum/<subject>/<int:grade>', methods=['GET'])
@login_required
def get_curriculum_structure(subject, grade):
    conn = get_db_connection()
    cursor = conn.cursor()
    param = get_param_style()
    
    cursor.execute(f'''
        SELECT u.id as unit_id, u.unit_number, u.title as unit_title,
               s.id as section_id, s.section_number, s.title as section_title,
               COUNT(DISTINCT q.id) as question_count
        FROM curriculum_units u
        JOIN curriculum_subjects cs ON u.subject_id = cs.id
        JOIN curriculum_grades g ON u.grade_id = g.id
        LEFT JOIN curriculum_sections s ON u.id = s.unit_id
        LEFT JOIN questions q ON q.curriculum_section_id = s.id
        WHERE cs.name = {param} AND g.number = {param}
        GROUP BY u.id, u.unit_number, u.title, s.id, s.section_number, s.title
        ORDER BY u.unit_number, s.section_number
    ''', (subject, grade))
    
    structure = cursor.fetchall()
    cursor.close()
    conn.close()
    
    result = {}
    for row in structure:
        unit_key = f"unit_{row['unit_id']}"
        if unit_key not in result:
            result[unit_key] = {
                "id": row['unit_id'],
                "unit_number": row['unit_number'],
                "unit_title": row['unit_title'],
                    "sections": {}
            }
        if row['section_id']:
            section_key = f"section_{row['section_id']}"
            if section_key not in result[unit_key]["sections"]:
                result[unit_key]["sections"][section_key] = {
                    "id": row['section_id'],
                    "section_number": row['section_number'],
                    "section_title": row['section_title'],
                    "question_count": row['question_count'] or 0
                }
    
    return jsonify(list(result.values()))


def exam_question_scope(exam, param, alias='q'):
    """Return the question predicate for a normal exam or a unit/section practice exam."""
    if exam['scope_section_id'] is not None:
        return f"{alias}.curriculum_section_id = {param}", (exam['scope_section_id'],)
    if exam['scope_unit_id'] is not None:
        return f"{alias}.curriculum_unit_id = {param}", (exam['scope_unit_id'],)
    return f"{alias}.exam_id = {param}", (exam['id'],)


@app.route('/api/curriculum/practice-exams', methods=['POST'])
@login_required
def open_curriculum_practice_exam():
    data = request.get_json(silent=True) or {}
    scope_type = str(data.get('scope_type') or '').strip().lower()
    try:
        scope_id = int(data.get('scope_id'))
    except (TypeError, ValueError):
        return jsonify({'error': 'Choose a valid unit or section.'}), 400
    if scope_type not in ('unit', 'section'):
        return jsonify({'error': 'Choose a unit or section.'}), 400

    conn = get_db_connection()
    cur = conn.cursor()
    p = get_param_style()
    try:
        if scope_type == 'section':
            cur.execute(f"""
                SELECT s.id AS scope_id, s.section_number, s.title AS section_title,
                       u.id AS unit_id, u.unit_number, u.title AS unit_title,
                       g.number AS grade, cs.name AS subject
                FROM curriculum_sections s
                JOIN curriculum_units u ON u.id = s.unit_id
                JOIN curriculum_grades g ON g.id = u.grade_id
                JOIN curriculum_subjects cs ON cs.id = u.subject_id
                WHERE s.id = {p}
            """, (scope_id,))
            scope = cur.fetchone()
            scope_column = 'scope_section_id'
            question_filter = 'curriculum_section_id'
            scope_title = f"Section {scope['section_number']}: {scope['section_title']}" if scope else ''
        else:
            cur.execute(f"""
                SELECT u.id AS scope_id, u.unit_number, u.title AS unit_title,
                       g.number AS grade, cs.name AS subject
                FROM curriculum_units u
                JOIN curriculum_grades g ON g.id = u.grade_id
                JOIN curriculum_subjects cs ON cs.id = u.subject_id
                WHERE u.id = {p}
            """, (scope_id,))
            scope = cur.fetchone()
            scope_column = 'scope_unit_id'
            question_filter = 'curriculum_unit_id'
            scope_title = f"Unit {scope['unit_number']}: {scope['unit_title']}" if scope else ''
        if not scope:
            return jsonify({'error': 'This curriculum unit or section was not found.'}), 404

        cur.execute(f"SELECT COUNT(*) AS total FROM questions WHERE {question_filter} = {p}", (scope_id,))
        total = int(cur.fetchone()['total'] or 0)
        if not total:
            return jsonify({'error': f'{scope_title} has no questions available yet.'}), 404

        cur.execute(f"SELECT id FROM exams WHERE {scope_column} = {p}", (scope_id,))
        exam = cur.fetchone()
        if exam:
            exam_id = exam['id']
        else:
            title = f"Grade {scope['grade']} {scope['subject']} · {scope_title}"
            columns = ('title', 'category', 'resource_type', 'subject', 'grade', 'instructions',
                       'total_marks', 'duration_minutes', 'examination_type', scope_column)
            values = (title, 'Chapter Practice', 'Exam', scope['subject'], scope['grade'],
                      f"Practice questions for Grade {scope['grade']} {scope['subject']} · {scope_title}.",
                      total, 30, 'chapter_practice', scope_id)
            sql = f"INSERT INTO exams ({', '.join(columns)}) VALUES ({', '.join([p] * len(columns))})"
            if is_postgres():
                cur.execute(sql + ' RETURNING id', values)
                exam_id = cur.fetchone()['id']
            else:
                cur.execute(sql, values)
                exam_id = cur.lastrowid
            conn.commit()
        return jsonify({'success': True, 'exam_id': exam_id, 'exam_url': url_for('exam_page', exam_id=exam_id)})
    except Exception:
        conn.rollback()
        app.logger.exception('Could not open curriculum practice exam')
        return jsonify({'error': 'Could not open practice for this curriculum scope.'}), 500
    finally:
        cur.close()
        conn.close()

def _chapter_practice_source_filter(param):
    source = request.args.get('source', '').strip().lower()
    if session.get('user_id') and session.get('role') != 'admin':
        conn = get_db_connection()
        cur = conn.cursor()
        p = get_param_style()
        cur.execute(f"SELECT 1 FROM exam_attempts WHERE user_id = {p} AND examination_mode = 'exam' AND status = 'in_progress' AND started_at_epoch + duration_seconds > {p} LIMIT 1",
                    (session.get('user_id'), time.time()))
        exam_in_progress = cur.fetchone()
        cur.close()
        conn.close()
        if exam_in_progress:
            return None, ()
    if source == 'entrance':
        return f" AND e.examination_type = {param}", ('official_entrance_exam',)
    if source == 'other':
        return f" AND e.examination_type <> {param}", ('official_entrance_exam',)
    if source == 'combined':
        return '', ()
    return None, ()


@app.route('/api/curriculum/unit/<int:unit_id>/questions', methods=['GET'])
@login_required
def get_unit_questions(unit_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    param = get_param_style()
    source_sql, source_values = _chapter_practice_source_filter(param)
    if source_sql is None:
        cursor.close(); conn.close()
        return jsonify({"error": "Select a practice source. Correct answers are hidden while a timed examination is active."}), 400
    cursor.execute(f'''
        SELECT q.*, e.title as exam_title
        FROM questions q
        JOIN exams e ON q.exam_id = e.id
        WHERE q.curriculum_unit_id = {param}{source_sql}
        ORDER BY q.id
    ''', (unit_id, *source_values))
    questions = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify([dict(q) for q in questions])

@app.route('/api/curriculum/section/<int:section_id>/questions', methods=['GET'])
@login_required
def get_section_questions(section_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    param = get_param_style()
    source_sql, source_values = _chapter_practice_source_filter(param)
    if source_sql is None:
        cursor.close(); conn.close()
        return jsonify({"error": "Select a practice source. Correct answers are hidden while a timed examination is active."}), 400
    cursor.execute(f'''
        SELECT q.*, e.title as exam_title
        FROM questions q
        JOIN exams e ON q.exam_id = e.id
        WHERE q.curriculum_section_id = {param}{source_sql}
        ORDER BY q.id
    ''', (section_id, *source_values))
    questions = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify([dict(q) for q in questions])

@app.route('/api/questions/chapter/<int:chapter_id>', methods=['GET'])
@login_required
def get_chapter_questions(chapter_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    param = get_param_style()
    source_sql, source_values = _chapter_practice_source_filter(param)
    if source_sql is None:
        cursor.close(); conn.close()
        return jsonify({"error": "Select a practice source. Correct answers are hidden while a timed examination is active."}), 400
    cursor.execute(f'''
        SELECT q.*, e.title as exam_title
        FROM questions q
        JOIN exams e ON q.exam_id = e.id
        WHERE q.chapter_id = {param}{source_sql}
        ORDER BY q.id ASC
    ''', (chapter_id, *source_values))
    questions = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify([dict(q) for q in questions])

# ============================================
# RESULT API
# ============================================

@app.route('/api/rankings', methods=['GET'])
@portal_or_unified_required
def get_rankings():
    """Return separate Entrance and Mock top-three rankings with student profiles."""
    conn = get_db_connection()
    cursor = conn.cursor()
    param = get_param_style()
    exam_id = request.args.get('exam_id')
    filter_sql = ''
    values = ['%entrance%', '%entrance%', '%entrance%']
    if exam_id:
        try:
            values.append(int(exam_id))
            filter_sql = f' AND r.exam_id = {param}'
        except ValueError:
            return jsonify({"error": "Invalid exam_id."}), 400
    cursor.execute(f'''
         SELECT r.id, r.user_id, r.exam_id, u.username, u.student_code,
             TRIM(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, '')) AS student_name,
             u.profile_photo, r.score, r.total_questions,
             r.accuracy, r.date_attempted, e.title AS exam_title, e.subject,
               CASE WHEN LOWER(e.resource_type) LIKE {param} OR LOWER(e.category) LIKE {param} OR LOWER(e.title) LIKE {param}
                    THEN 'entrance' ELSE 'mock' END AS exam_type
        FROM user_results r
        JOIN users u ON u.id = r.user_id
        JOIN exams e ON e.id = r.exam_id
        WHERE u.role = 'student'{filter_sql}
        ORDER BY r.date_attempted ASC, r.id ASC
    ''', values)
    rows = [dict(row) for row in cursor.fetchall()]
    for row in rows:
        row['photo_url'] = url_for('profile_photo', filename=row['profile_photo']) if row.get('profile_photo') else None
    response = calculate_rankings(rows, current_user_id=session['user_id'])
    response['top_performers_by_exam'] = calculate_exam_top_performers(rows)
    exam_system_results = []
    try:
        ensure_unified_exam_table(conn)
        cursor.execute(f'SELECT payload FROM unified_exam_records WHERE collection_name = {param}', ('results',))
        for item in cursor.fetchall():
            raw = item['payload'] if hasattr(item, 'keys') else item[0]
            try:
                result = json.loads(raw) if isinstance(raw, (str, bytes, bytearray)) else raw
            except (TypeError, ValueError):
                continue
            if isinstance(result, dict):
                exam_system_results.append(result)
    except Exception:
        app.logger.exception('Could not load EduVault Exam System results for performance rankings')
    cursor.close()
    conn.close()
    # These public Entrance and Mock leaderboards intentionally use only results
    # submitted in the EduVault Exam System's shared results collection.
    response['entrance_top_performers'] = calculate_exam_system_entrance_top_performers(exam_system_results)
    response['mock_top_performers'] = calculate_exam_system_mock_top_performers(exam_system_results)
    return jsonify(response)

@app.route('/api/results/submit', methods=['POST'])
@login_required
def submit_exam_results():
    data = request.get_json(silent=True) or {}
    try:
        attempt_id = int(data.get('attempt_id'))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "Start an examination attempt before submitting."}), 400
    conn = get_db_connection()
    cursor = conn.cursor()
    param = get_param_style()
    try:
        cursor.execute(f"SELECT * FROM exam_attempts WHERE id = {param} AND user_id = {param}",
                       (attempt_id, session.get('user_id')))
        attempt = cursor.fetchone()
        if not attempt or not exam_access_allowed(attempt['exam_id']):
            return jsonify({"success": False, "error": "Examination attempt not found or access denied."}), 403
        if attempt['status'] != 'in_progress':
            return jsonify({"success": False, "error": "This examination attempt has already been submitted."}), 409
        cursor.execute(f"SELECT id, scope_unit_id, scope_section_id FROM exams WHERE id = {param}", (attempt['exam_id'],))
        exam_scope = cursor.fetchone()
        scope_sql, scope_values = exam_question_scope(exam_scope, param)
        cursor.execute(f"SELECT q.id, q.correct_answer FROM questions q WHERE {scope_sql} ORDER BY q.id ASC", scope_values)
        questions = cursor.fetchall()
        if not questions:
            return jsonify({"success": False, "error": "Exam has no questions."}), 400
        cursor.execute(f"SELECT question_id, selected_answer FROM attempt_answers WHERE attempt_id = {param}", (attempt_id,))
        answers = {row['question_id']: row['selected_answer'] for row in cursor.fetchall()}
        score = score_saved_answers(questions, answers)
        total = score['total_questions']
        correct = score['correct_answers']
        incorrect = score['incorrect_answers']
        unanswered = score['unanswered_questions']
        accuracy = score['percentage']
        now = time.time()
        started_at = float(attempt['started_at_epoch'])
        duration = int(attempt['duration_seconds'])
        elapsed = max(0, int(now - started_at))
        automatic = attempt['examination_mode'] == 'exam' and elapsed >= duration
        time_taken = min(elapsed, duration) if attempt['examination_mode'] == 'exam' else elapsed
        status = 'expired' if automatic else 'submitted'
        cursor.execute(f"UPDATE exam_attempts SET status = {param}, submitted_at_epoch = {param}, time_taken_seconds = {param}, total_questions = {param}, correct_answers = {param}, incorrect_answers = {param}, unanswered_questions = {param}, score = {param} WHERE id = {param} AND user_id = {param} AND status = 'in_progress'",
                       (status, now, time_taken, total, correct, incorrect, unanswered, accuracy, attempt_id, session.get('user_id')))
        if cursor.rowcount != 1:
            conn.rollback()
            return jsonify({"success": False, "error": "This examination attempt has already been submitted."}), 409
        recommendation = "Review explanations for missed questions and revisit the related topics."
        result_sql = f"INSERT INTO user_results (user_id, exam_id, score, total_questions, time_used_seconds, accuracy, date_attempted, ai_recommendation, examination_mode) VALUES ({', '.join([param] * 9)})"
        result_values = (session['user_id'], attempt['exam_id'], correct, total, time_taken, accuracy,
                         time.strftime("%Y-%m-%d %H:%M"), recommendation, attempt['examination_mode'])
        if is_postgres():
            cursor.execute(result_sql + " RETURNING id", result_values)
            result_id = cursor.fetchone()['id']
        else:
            cursor.execute(result_sql, result_values)
            result_id = cursor.lastrowid
        for question in questions:
            answer = str(answers.get(question['id']) or '')
            is_correct = int(answer.upper() == str(question['correct_answer'] or '').upper())
            cursor.execute(f"INSERT INTO user_answer_details (result_id, question_id, submitted_answer, is_correct) VALUES ({param}, {param}, {param}, {param})",
                           (result_id, question['id'], answer, is_correct))
        conn.commit()
        return jsonify({"success": True, "result_id": result_id, "score": correct, "total_questions": total,
                        "correct_answers": correct, "incorrect_answers": incorrect, "unanswered_questions": unanswered,
                        "percentage": accuracy, "time_taken_seconds": time_taken, "automatic_submission": automatic})
    except Exception:
        conn.rollback()
        app.logger.exception("Could not submit examination attempt")
        return jsonify({"success": False, "error": "Could not submit this examination."}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/results/<int:result_id>', methods=['GET'])
@login_required
def get_result_details(result_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    param = get_param_style()
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

# ============================================
# RESOURCE API
# ============================================

@app.route('/api/resources', methods=['GET'])
@portal_or_unified_required
def get_resources():
    conn = get_db_connection()
    cursor = conn.cursor()
    param = get_param_style()
    cursor.execute(f'''
        SELECT id, title, resource_type, subject, grade, file_name, file_url, pdf_url, description
        FROM resources
        WHERE status = {param}
        ORDER BY grade, subject, resource_type
    ''', ('published',))
    resources = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify([dict(r) for r in resources])

@app.route('/api/textbook-library', methods=['GET'])
@portal_or_unified_required
def list_textbook_library():
    """List bundled student and teacher books in the Textbooks resource collection."""
    manifest_path = os.path.join(BASE_DIR, 'Databasejson', 'textbook_resources.json')
    try:
        with open(manifest_path, 'r', encoding='utf-8') as manifest_file:
            books = json.load(manifest_file)
    except (OSError, json.JSONDecodeError):
        return jsonify([])
    return jsonify([
        {**book, 'pdf_url': url_for('open_textbook_file', filename=book['file_name'])}
        for book in books
        if book.get('file_name') and os.path.isfile(os.path.join(TEXTBOOK_FOLDER, book['file_name']))
    ])

@app.route('/textbook-files/<path:filename>')
@portal_or_unified_required
def open_textbook_file(filename):
    """Serve only textbook files explicitly listed in the library manifest."""
    manifest_path = os.path.join(BASE_DIR, 'Databasejson', 'textbook_resources.json')
    try:
        with open(manifest_path, 'r', encoding='utf-8') as manifest_file:
            books = json.load(manifest_file)
    except (OSError, json.JSONDecodeError):
        abort(404)
    if not any(book.get('file_name') == filename for book in books):
        abort(404)
    return send_from_directory(TEXTBOOK_FOLDER, filename, as_attachment=False, mimetype='application/pdf')

@app.route('/resource-files/<int:resource_id>')
@portal_or_unified_required
def open_resource_file(resource_id):
    """Serve the uploaded file for a published resource without exposing the upload path."""
    conn = get_db_connection()
    cursor = conn.cursor()
    param = get_param_style()
    try:
        cursor.execute(f"SELECT file_name FROM resources WHERE id = {param} AND status = {param}",
                       (resource_id, 'published'))
        row = cursor.fetchone()
        if not row:
            abort(404)
        filename = row['file_name'] if hasattr(row, 'keys') else row[0]
        if not filename:
            abort(404)
        return send_from_directory(app.config['UPLOAD_FOLDER'], os.path.basename(filename), as_attachment=False)
    finally:
        cursor.close()
        conn.close()

@app.route('/api/resources/<int:resource_id>', methods=['GET'])
@login_required
def get_resource(resource_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    param = get_param_style()
    cursor.execute(f"SELECT * FROM resources WHERE id = {param}", (resource_id,))
    resource = cursor.fetchone()
    cursor.close()
    conn.close()
    if resource:
        return jsonify(dict(resource))
    return jsonify({"error": "Resource not found"}), 404

@app.route('/api/resources/type/<resource_type>', methods=['GET'])
@login_required
def get_resources_by_type(resource_type):
    conn = get_db_connection()
    cursor = conn.cursor()
    param = get_param_style()
    cursor.execute(f'''
        SELECT id, title, subject, grade, file_url, pdf_url, description
        FROM resources
        WHERE resource_type = {param} AND status = {param}
        ORDER BY grade, subject
    ''', (resource_type, 'published'))
    resources = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify([dict(r) for r in resources])

@app.route('/api/worksheets', methods=['GET'])
@login_required
def get_worksheets():
    return get_resources_by_type('Worksheet')

# ============================================
# BATCH CURRICULUM CLASSIFICATION
# ============================================
def _normalise_question_text(value):
    """Stable comparison key for detecting duplicate questions without changing display text."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", str(value or "").casefold())).strip()


def classify_questions_in_batches(questions, subject_name, grade_number, batch_size=20, force_reclassify=False):
    """Classify missing question labels in batches to avoid one Gemini call per question.

    Existing valid classifications are preserved. On quota/API failure, questions are retained
    with Low confidence rather than failing the upload.
    """
    global classification_retry_after
    results = {}
    pending = []
    curriculum_by_grade = {}
    for index, question in enumerate(questions):
        has_classification = (
            question.get("unit_number") not in (None, "") and
            question.get("unit_title") not in (None, "")
        )
        if has_classification and not force_reclassify:
            try:
                question_grade = int(question.get("curriculum_grade") or question.get("grade") or grade_number)
            except (TypeError, ValueError):
                question_grade = grade_number
            if question_grade not in curriculum_by_grade:
                curriculum_by_grade[question_grade] = get_curriculum_outline(subject_name, question_grade)
            question_curriculum = curriculum_by_grade[question_grade]
            unit_rows = [row for row in question_curriculum
                         if str(row.get("unit_number")) == str(question.get("unit_number"))
                         and str(row.get("unit_title") or row.get("title") or "") == str(question.get("unit_title") or "")]
            section_rows = [row for row in unit_rows if row.get("section_number") is not None]
            matched_section = next((row for row in section_rows
                                    if str(row.get("section_number")) == str(question.get("section_number"))
                                    and str(row.get("section_title") or "") == str(question.get("section_title") or "")), None)
            if unit_rows and (matched_section or not section_rows):
                canonical = matched_section or unit_rows[0]
                results[index] = {
                    "unit_number": canonical.get("unit_number"),
                    "unit_title": canonical.get("unit_title") or canonical.get("title"),
                    "section_number": canonical.get("section_number"),
                    "section_title": canonical.get("section_title"),
                    "confidence": question.get("confidence") or "High",
                    "curriculum_grade": question_grade,
                    "reason": question.get("reason") or "Classification matched the EduVault curriculum database"
                }
                continue
        pending.append((index, question))

    if not pending:
        return results

    if grade_number not in curriculum_by_grade:
        curriculum_by_grade[grade_number] = get_curriculum_outline(subject_name, grade_number)
    curriculum = curriculum_by_grade[grade_number]
    if not curriculum:
        for index, _ in pending:
            results[index] = {"curriculum_grade": grade_number, "confidence": "Low", "reason": f"No curriculum found for {subject_name} Grade {grade_number}"}
        return results

    if not get_gemini_client() or time.time() < classification_retry_after:
        for index, _ in pending:
            results[index] = {"curriculum_grade": grade_number, "confidence": "Low", "reason": "AI unavailable; question saved for later classification"}
        return results

    # Use previously classified questions as few-shot examples when available; examples are prompt-only
    # and are never inserted as new exam questions.
    examples = []
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        param = get_param_style()
        cursor.execute(f"""
            SELECT pq.question_text, pq.unit_number, pq.unit_title, pq.section_number,
                   pq.section_title
            FROM pending_questions pq
            JOIN pending_exams pe ON pe.id = pq.pending_exam_id
            WHERE pe.subject = {param} AND pe.grade = {param}
              AND pq.unit_title IS NOT NULL AND pq.question_text IS NOT NULL
            ORDER BY pq.id DESC LIMIT 4
        """, (subject_name, grade_number))
        examples = [dict(row) for row in cursor.fetchall()]
        cursor.close()
        conn.close()
    except Exception as sample_error:
        print(f"DEBUG: Could not load classification examples: {sample_error}")

    curriculum_json = json.dumps(curriculum, ensure_ascii=False)
    examples_json = json.dumps(examples, ensure_ascii=False)
    for start in range(0, len(pending), max(1, batch_size)):
        batch = pending[start:start + max(1, batch_size)]
        if time.time() < classification_retry_after:
            for index, _ in batch:
                results[index] = {"confidence": "Low", "reason": "Gemini quota cooldown; saved for manual/retry classification"}
            continue
        payload = []
        for index, question in batch:
            payload.append({
                "index": index,
                "question": question.get("question") or question.get("question_text") or "",
                "passage_text": question.get("passage_text") or None
            })
        prompt = f"""
You are an expert Ethiopian New Curriculum exam classifier for {subject_name}, Grade {grade_number}.
Classify each supplied question using ONLY the official curriculum below. Use the examples as reasoning
examples only; they are not questions to add to the exam. Never invent curriculum units or labels.
Return JSON only in this exact shape: {{"classifications":[{{"index":0,"unit_number":"1",
"unit_title":"exact official title","section_number":"1.1","section_title":"exact official title",
"confidence":"High|Medium|Low",
"reason":"brief reason"}}]}}.
Rules:
- Return exactly one classification for each input index, preserving its index.
- Select the closest official unit and section. Copy names and numbers exactly from the curriculum.
- If no precise match exists, use the best supported unit, set confidence Low, and explain uncertainty.
- Do not answer the exam question; classify only.
Official curriculum JSON:
{curriculum_json}
Previously classified reference examples (prompt-only; do not output them):
{examples_json}
Questions to classify:
{json.dumps(payload, ensure_ascii=False)}
"""
        last_error = None
        response_data = None
        for model_name in ("gemini-flash-latest", "gemini-2.0-flash"):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json", temperature=0.1
                    )
                )
                if not response or not response.text:
                    raise ValueError("AI returned an empty classification response")
                response_data = json.loads(response.text)
                break
            except Exception as error:
                last_error = error
                error_text = str(error).upper()
                if "429" in error_text or "RESOURCE_EXHAUSTED" in error_text:
                    retry_match = re.search(r"retryDelay['\"]?:\s*['\"]?([0-9.]+)s", str(error))
                    classification_retry_after = time.time() + (float(retry_match.group(1)) if retry_match else 60.0)
                    break
                if not any(code in error_text for code in ("503", "UNAVAILABLE", "NOT FOUND", "404")):
                    break
        items = (response_data or {}).get("classifications", []) if isinstance(response_data, dict) else response_data
        if not isinstance(items, list):
            items = []
        by_index = {item.get("index"): item for item in items if isinstance(item, dict) and item.get("index") is not None}
        valid_units = {str(row.get("unit_number")): row for row in curriculum}
        for index, _ in batch:
            item = by_index.get(index)
            if not item:
                results[index] = {"curriculum_grade": grade_number, "confidence": "Low", "reason": f"Batch classification unavailable: {last_error or 'no matching result'}"}
                continue
            # Guard against invented unit numbers and titles that are not in the curriculum.
            unit_key = str(item.get("unit_number")) if item.get("unit_number") is not None else None
            valid_rows = [row for row in curriculum if unit_key and str(row.get("unit_number")) == unit_key]
            valid_titles = {str(row.get("unit_title") or row.get("title") or "") for row in valid_rows}
            unit_title = item.get("unit_title")
            if not valid_rows or (unit_title and unit_title not in valid_titles):
                results[index] = {"curriculum_grade": grade_number, "confidence": "Low", "reason": "AI label did not match official curriculum; needs review"}
                continue
            official_unit_title = valid_rows[0].get("unit_title") or valid_rows[0].get("title")
            section_number = item.get("section_number")
            section_title = item.get("section_title")
            section_rows = [row for row in valid_rows if row.get("section_number") is not None]
            matched_sections = [row for row in section_rows if
                str(row.get("section_number")) == str(section_number) and
                (not section_title or str(row.get("section_title")) == str(section_title))]
            if section_rows and not matched_sections:
                section_number = section_title = None
                confidence = "Low"
                reason = "Unit matched; section label was not an exact curriculum match and needs review"
            else:
                confidence = item.get("confidence") if item.get("confidence") in ("High", "Medium", "Low") else "Low"
                reason = item.get("reason") or "Batch-classified against official curriculum"
            results[index] = {
                "unit_number": valid_rows[0].get("unit_number"),
                "unit_title": official_unit_title,
                "section_number": section_number,
                "section_title": section_title,
                "curriculum_grade": grade_number,
                "confidence": confidence,
                "reason": reason
            }
    return results


# ============================================
# SMART UPLOAD ENGINE WITH CLASSIFICATION
# ============================================

@app.route('/api/upload', methods=['POST'])
@admin_required
def upload_engine():
    title = request.form.get('title', 'Untitled Resource').strip()
    resource_type = request.form.get('resource_type', 'Exam').strip()
    legacy_category = request.form.get('category', '').strip()
    examination_type = normalize_examination_type(request.form.get('examination_type'), resource_type, legacy_category)
    category = EXAMINATION_TYPES[examination_type]
    resource_type = {
        'official_entrance_exam': 'Entrance Exam',
        'entrance_exam_worksheet': 'Worksheet',
        'school_final_exam': 'School Exam',
        'school_midterm_exam': 'School Exam',
        'school_test': 'School Exam',
        'worksheet': 'Worksheet',
        'practical_question': 'Worksheet',
        'practical_worksheet': 'Worksheet',
        'chapter_practice': 'Worksheet',
        'other_core_subject': 'Exam',
    }[examination_type]
    subject = request.form.get('subject', 'Mathematics').strip()
    grade = int(request.form.get('grade', 12))
    try:
        duration_minutes = int(request.form.get('duration_minutes') or 60)
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "Examination duration must be a whole number of minutes."}), 400
    if duration_minutes < 1 or duration_minutes > 600:
        return jsonify({"success": False, "error": "Examination duration must be between 1 and 600 minutes."}), 400
    academic_year = request.form.get('academic_year', '').strip()
    instructions = request.form.get('instructions', '').strip()

    file = request.files.get('file')
    if not file:
        return jsonify({"success": False, "error": "No file uploaded"}), 400

    if not allowed_file(file.filename):
        return jsonify({"success": False, "error": f"File type not allowed. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"}), 400

    filename = secure_filename(file.filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)
    with open(filepath, 'rb') as uploaded_content:
        source_hash = hashlib.sha256(uploaded_content.read()).hexdigest()

    try:
        if filename.lower().endswith('.json'):
            # Accept both the standard EduVault object ({"questions": [...]}) and
            # a plain list of questions. UTF-8 BOMs are common in exported JSON.
            with open(filepath, 'r', encoding='utf-8-sig') as f:
                ai_data = json.load(f)
            if isinstance(ai_data, list):
                ai_data = {'questions': ai_data}
            if not isinstance(ai_data, dict):
                return jsonify({"success": False, "error": "JSON must be an object containing a questions array, or a list of questions."}), 400
            if not title or title == 'Untitled Resource':
                title = str(ai_data.get('title') or os.path.splitext(filename)[0] or title).strip()
            subject = str(ai_data.get('subject') or subject).strip()
            try:
                grade = int(ai_data.get('grade') or grade)
            except (TypeError, ValueError):
                return jsonify({"success": False, "error": "The JSON grade must be a number."}), 400
            academic_year = str(ai_data.get('academic_year') or academic_year).strip()
            instructions = str(ai_data.get('instructions') or instructions).strip()
            # Map common question field names to the review/import schema.
            normalized_questions = []
            for index, item in enumerate(ai_data.get('questions') or [], start=1):
                if not isinstance(item, dict):
                    continue
                question = dict(item)
                question['question_text'] = question.get('question_text') or question.get('question') or question.get('text') or ''
                for letter in 'ABCD':
                    lower = letter.lower()
                    question[f'option_{lower}'] = (question.get(f'option_{lower}') or question.get(letter)
                                                    or question.get(f'choice_{lower}') or question.get(f'option{letter}') or '')
                answer = question.get('correct_answer') or question.get('correct') or question.get('answer') or 'A'
                answer_text = str(answer).strip()
                if answer_text.casefold() in {'option_a', 'a'}: answer_text = 'A'
                elif answer_text.casefold() in {'option_b', 'b'}: answer_text = 'B'
                elif answer_text.casefold() in {'option_c', 'c'}: answer_text = 'C'
                elif answer_text.casefold() in {'option_d', 'd'}: answer_text = 'D'
                elif answer_text in {'1', '2', '3', '4'}: answer_text = 'ABCD'[int(answer_text) - 1]
                question['correct_answer'] = answer_text.upper()
                question['question_number'] = question.get('question_number') or index
                normalized_questions.append(question)
            ai_data['questions'] = normalized_questions
        else:
            ai_data = parse_pdf_with_ai(filepath, subject, grade)

        if not ai_data or not ai_data.get('questions'):
            return jsonify({"success": False, "error": "No questions could be extracted from the file."}), 400

        questions = ai_data.get('questions', [])
        print(f"DEBUG: Extracted {len(questions)} questions")

        conn = get_db_connection()
        cursor = conn.cursor()
        param = get_param_style()
        cursor.execute(f"SELECT id FROM pending_exams WHERE source_hash = {param} AND status IN ('pending', 'approved') LIMIT 1", (source_hash,))
        duplicate_upload = cursor.fetchone()
        if duplicate_upload:
            cursor.close()
            conn.close()
            return jsonify({"success": False, "error": "This exact file has already been imported. Reuse its pending review or choose a different file."}), 409

        resource_insert = f"""
            INSERT INTO resources (title, resource_type, subject, grade, file_name, description, status, created_by, examination_type, source_hash)
            VALUES ({param}, {param}, {param}, {param}, {param}, {param}, {param}, {param}, {param}, {param})
        """
        if is_postgres():
            resource_insert += " RETURNING id"
        cursor.execute(resource_insert, (title, resource_type, subject, grade, filename, instructions, 'draft', session['user_id'], examination_type, source_hash))
        
        if is_postgres():
            resource_id = cursor.fetchone()['id']
        else:
            resource_id = cursor.lastrowid
        conn.commit()

        pending_insert = f"""
            INSERT INTO pending_exams (
                resource_id, title, resource_type, subject, grade, academic_year,
                school_name, instructions, source_filename, uploaded_by, examination_type, duration_minutes, source_hash
            )
            VALUES ({param}, {param}, {param}, {param}, {param}, {param}, {param}, {param}, {param}, {param}, {param}, {param}, {param})
        """
        if is_postgres():
            pending_insert += " RETURNING id"
        cursor.execute(pending_insert, (
            resource_id, title, resource_type, subject, grade,
            ai_data.get('academic_year') or academic_year,
            ai_data.get('school_name') or request.form.get('school_name', '').strip(),
            ai_data.get('instructions') or instructions,
            filename, session['user_id'], examination_type, duration_minutes, source_hash
        ))
        
        if is_postgres():
            pending_exam_id = cursor.fetchone()['id']
        else:
            pending_exam_id = cursor.lastrowid
        conn.commit()

        saved_count = 0
        classified_count = 0
        error_count = 0
        # Accept exact curriculum labels supplied by JSON; classify only missing or mismatched labels.
        batch_classifications = classify_questions_in_batches(
            questions, subject, grade, batch_size=20
        )
        # Within one upload, keep only the last occurrence of an exact duplicate. This lets a
        # corrected/re-entered question replace an earlier copy without adding sample questions.
        last_occurrence = {}
        for q_index, q_item in enumerate(questions):
            q_key = _normalise_question_text(q_item.get('question') or q_item.get('question_text', ''))
            if q_key:
                last_occurrence[q_key] = q_index
        duplicate_indices = {
            q_index for q_index, q_item in enumerate(questions)
            if (lambda k: bool(k) and last_occurrence.get(k) != q_index)(
                _normalise_question_text(q_item.get('question') or q_item.get('question_text', ''))
            )
        }
        for idx, q in enumerate(questions):
            try:
                q_text = q.get('question') or q.get('question_text', '')
                if not q_text:
                    continue
                if idx in duplicate_indices:
                    print(f"DEBUG: Skipping duplicate question at upload position {idx + 1}; latest copy retained.")
                    continue

                classification = batch_classifications.get(idx, {
                    'confidence': 'Low', 'reason': 'Classification not available; saved for review'
                })
                # Prefer a supplied classification only if the batch helper preserved it.
                opt_a = fix_latex_string(q.get('A') or q.get('option_a', ''))
                opt_b = fix_latex_string(q.get('B') or q.get('option_b', ''))
                opt_c = fix_latex_string(q.get('C') or q.get('option_c', ''))
                opt_d = fix_latex_string(q.get('D') or q.get('option_d', ''))
                explanation = fix_latex_string(q.get('explanation', ''))
                question_text = fix_latex_string(q_text)

                cursor.execute(f"""
                    INSERT INTO pending_questions (
                        pending_exam_id, question_number, source_year, question_text, option_a, option_b, option_c, option_d,
                        correct_answer, explanation, passage_text, diagram_instruction,
                        curriculum_grade, unit_number, unit_title, section_number, section_title,
                        confidence, classification_reason, status
                    )
                        VALUES ({param}, {param}, {param}, {param}, {param}, {param}, {param}, {param},
                            {param}, {param}, {param}, {param},
                            {param}, {param}, {param}, {param}, {param},
                            {param}, {param}, {param})
                """, (
                    pending_exam_id, 
                    q.get('question_number', idx + 1),
                    q.get('source_year') or ai_data.get('academic_year') or academic_year,
                    question_text,
                    opt_a, opt_b, opt_c, opt_d,
                    q.get('correct') or q.get('correct_answer', 'A'),
                    explanation,
                    q.get('passage_text'),
                    q.get('diagram_instruction'),
                    classification.get('curriculum_grade') or q.get('curriculum_grade') or grade,
                    classification.get('unit_number'),
                    classification.get('unit_title'),
                    classification.get('section_number'),
                    classification.get('section_title'),
                    classification.get('confidence', 'Low'),
                    classification.get('reason', 'Auto-classified'),
                    'pending'
                ))
                saved_count += 1
                if classification.get('unit_number') not in (None, '') and classification.get('unit_title'):
                    classified_count += 1
                
            except Exception as q_error:
                error_count += 1
                print(f"ERROR processing question {idx}: {q_error}")
                continue

        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({
            "success": True,
            "message": f"File processed: {saved_count} questions saved, {classified_count} classified to a curriculum unit; {len(duplicate_indices)} duplicate copies skipped; {error_count} errors.",
            "pending_exam_id": pending_exam_id,
            "total_questions": len(questions) - len(duplicate_indices),
            "saved_questions": saved_count,
            "duplicates_skipped": len(duplicate_indices),
            "classified": classified_count,
            "errors": error_count
        })

    except json.JSONDecodeError as e:
        return jsonify({"success": False, "error": f"Invalid JSON near line {e.lineno}, column {e.colno}. Please export or save the file as valid UTF-8 JSON."}), 400
    except Exception as e:
        print(f"ERROR in upload_engine: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if os.path.exists(filepath):
            os.remove(filepath)

# ============================================
# ADMIN REVIEW API
# ============================================

@app.route('/api/admin/pending_exams', methods=['GET'])
@admin_required
def get_pending_exams():
    conn = get_db_connection()
    cursor = conn.cursor()
    param = get_param_style()
    cursor.execute(f"""
        SELECT pe.*, r.title as resource_title, u.username as uploaded_by_name,
               (SELECT COUNT(*) FROM pending_questions WHERE pending_exam_id = pe.id AND status = 'pending') as question_count
        FROM pending_exams pe
        JOIN resources r ON pe.resource_id = r.id
        LEFT JOIN users u ON pe.uploaded_by = u.id
        WHERE pe.status = {param}
        ORDER BY pe.created_at DESC
    """, ('pending',))
    pending_exams = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify([dict(pe) for pe in pending_exams])


@app.route('/api/admin/pending_exams/<int:pending_exam_id>/classification', methods=['PUT'])
@admin_required
def update_pending_exam_classification(pending_exam_id):
    data = request.get_json(silent=True) or {}
    kind = normalize_examination_type(data.get('examination_type'))
    if kind not in EXAMINATION_TYPES:
        return jsonify({"error": "Choose a supported examination type."}), 400
    resource_type = {
        'official_entrance_exam': 'Entrance Exam', 'school_final_exam': 'School Exam',
        'school_midterm_exam': 'School Exam', 'school_test': 'School Exam', 'other_core_subject': 'Exam',
        'entrance_exam_worksheet': 'Worksheet', 'worksheet': 'Worksheet',
        'practical_question': 'Worksheet', 'practical_worksheet': 'Worksheet', 'chapter_practice': 'Worksheet'
    }[kind]
    conn = get_db_connection()
    cur = conn.cursor()
    p = get_param_style()
    try:
        cur.execute(f"SELECT resource_id FROM pending_exams WHERE id = {p} AND status = 'pending'", (pending_exam_id,))
        pending = cur.fetchone()
        if not pending:
            return jsonify({"error": "Only pending uploads can be reclassified."}), 409
        cur.execute(f"UPDATE pending_exams SET examination_type = {p}, resource_type = {p} WHERE id = {p}",
                    (kind, resource_type, pending_exam_id))
        cur.execute(f"UPDATE resources SET examination_type = {p}, resource_type = {p} WHERE id = {p}",
                    (kind, resource_type, pending['resource_id']))
        conn.commit()
        return jsonify({"success": True, "examination_type": kind, "destination": examination_destination(kind)})
    except Exception:
        conn.rollback()
        app.logger.exception("Could not reclassify pending examination")
        return jsonify({"error": "Could not update the examination classification."}), 500
    finally:
        cur.close()
        conn.close()

@app.route('/api/admin/pending_exams/<int:pending_exam_id>/questions', methods=['GET'])
@admin_required
def get_pending_questions(pending_exam_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    param = get_param_style()
    cursor.execute(f"""
        SELECT * FROM pending_questions
        WHERE pending_exam_id = {param} AND status = {param}
        ORDER BY question_number
    """, (pending_exam_id, 'pending'))
    questions = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify([dict(q) for q in questions])

@app.route('/api/admin/pending_exams/<int:pending_exam_id>/stats', methods=['GET'])
@admin_required
def get_pending_exam_stats(pending_exam_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    param = get_param_style()
    
    cursor.execute(f"""
        SELECT pe.*, r.title as resource_title
        FROM pending_exams pe
        JOIN resources r ON pe.resource_id = r.id
        WHERE pe.id = {param}
    """, (pending_exam_id,))
    exam = cursor.fetchone()
    
    if not exam:
        return jsonify({"error": "Pending exam not found"}), 404
    
    cursor.execute(f"""
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN confidence = 'High' THEN 1 ELSE 0 END) as high_confidence,
            SUM(CASE WHEN confidence = 'Medium' THEN 1 ELSE 0 END) as medium_confidence,
            SUM(CASE WHEN confidence = 'Low' THEN 1 ELSE 0 END) as low_confidence
        FROM pending_questions
        WHERE pending_exam_id = {param} AND status = {param}
    """, (pending_exam_id, 'pending'))
    stats = cursor.fetchone()
    
    cursor.close()
    conn.close()
    
    return jsonify({
        "exam": dict(exam),
        "stats": dict(stats) if stats else {"total": 0, "high_confidence": 0, "medium_confidence": 0, "low_confidence": 0}
    })

@app.route('/api/admin/pending_questions/<int:question_id>', methods=['PUT'])
@admin_required
def update_pending_question(question_id):
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    param = get_param_style()
    
    allowed_fields = [
        'question_text', 'option_a', 'option_b', 'option_c', 'option_d', 
        'correct_answer', 'explanation', 'passage_text', 'diagram_instruction',
        'curriculum_grade',
        'unit_number', 'unit_title', 'section_number', 'section_title',
        'confidence', 'classification_reason'
    ]
    
    updates = []
    values = []
    for key, value in data.items():
        if key in allowed_fields:
            updates.append(f"{key} = {param}")
            values.append(value)
    
    if not updates:
        return jsonify({"error": "No valid fields to update"}), 400
    
    values.append(question_id)
    cursor.execute(f"""
        UPDATE pending_questions
        SET {', '.join(updates)}
        WHERE id = {param}
    """, values)
    conn.commit()
    cursor.close()
    conn.close()
    
    return jsonify({"success": True, "message": "Question updated successfully"})

@app.route('/api/admin/pending_exams/<int:pending_exam_id>/approve', methods=['POST'])
@admin_required
def approve_pending_exam(pending_exam_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    param = get_param_style()

    try:
        cursor.execute(f"""
            SELECT pe.*
            FROM pending_exams pe
            WHERE pe.id = {param}
        """, (pending_exam_id,))
        pending_exam = cursor.fetchone()
        
        if not pending_exam:
            return jsonify({"error": "Pending exam not found"}), 404
        if pending_exam['status'] != 'pending':
            cursor.execute(f"SELECT id FROM exams WHERE resource_id = {param}", (pending_exam['resource_id'],))
            published = cursor.fetchone()
            if published:
                return jsonify({"error": "This upload has already been published.", "exam_id": published['id']}), 409
            return jsonify({"error": "This upload is no longer pending review."}), 409

        exam_insert = f"""
            INSERT INTO exams (
                resource_id, title, category, resource_type, subject, grade, 
                academic_year, school_name, instructions, examination_type, duration_minutes
            )
            VALUES ({param}, {param}, {param}, {param}, {param}, {param}, {param}, {param}, {param}, {param}, {param})
        """
        if is_postgres():
            exam_insert += " RETURNING id"
        cursor.execute(exam_insert, (
            pending_exam['resource_id'], 
            pending_exam['title'], 
            EXAMINATION_TYPES.get(pending_exam['examination_type'], 'Other Core Subject Examination'),
            pending_exam['resource_type'],
            pending_exam['subject'],
            pending_exam['grade'],
            pending_exam['academic_year'] or '',
            pending_exam['school_name'] or '',
            pending_exam['instructions'] or '',
            pending_exam['examination_type'] or 'other_core_subject',
            pending_exam['duration_minutes'] or 60
        ))
        
        if is_postgres():
            exam_id = cursor.fetchone()['id']
        else:
            exam_id = cursor.lastrowid
        cursor.execute(f"""
            SELECT * FROM pending_questions 
            WHERE pending_exam_id = {param} AND status <> {param}
        """, (pending_exam_id, 'rejected'))
        pending_questions = cursor.fetchall()

        if not pending_questions:
            return jsonify({"error": "No pending questions found for this exam"}), 404

        inserted_count = 0
        for pq in pending_questions:
            unit_id = section_id = chapter_id = None
            cursor.execute(f"""
                SELECT u.id
                FROM curriculum_units u
                JOIN curriculum_subjects cs ON cs.id = u.subject_id
                JOIN curriculum_grades cg ON cg.id = u.grade_id
                WHERE cs.name = {param} AND cg.number = {param}
                  AND (CAST(u.unit_number AS TEXT) = CAST({param} AS TEXT)
                       OR LOWER(TRIM(u.title)) = LOWER(TRIM({param})))
                LIMIT 1
            """, (
                pending_exam['subject'], pq['curriculum_grade'] or pending_exam['grade'],
                pq['unit_number'] or pq['unit_title'],
                pq['unit_number'] or pq['unit_title']
            ))
            unit = cursor.fetchone()
            if unit:
                unit_id = unit['id']

                cursor.execute(f"""
                    SELECT id
                    FROM curriculum_sections
                    WHERE unit_id = {param}
                      AND (CAST(section_number AS TEXT) = CAST({param} AS TEXT)
                           OR LOWER(TRIM(title)) = LOWER(TRIM({param})))
                    LIMIT 1
                """, (
                    unit_id,
                    pq['section_number'] or pq['section_title'],
                    pq['section_number'] or pq['section_title']
                ))
                section = cursor.fetchone()
                if section:
                    section_id = section['id']

            if unit_id is None or section_id is None:
                conn.rollback()
                return jsonify({
                    "error": f"Question {pq['question_number'] or ''} is not classified to a section in the selected grade and subject. Correct its curriculum classification before approving this exam."
                }), 422

            chapter_name = pq['section_title'] or pq['section_number'] or 'Unclassified'
            cursor.execute(f"""
                SELECT id FROM chapters
                WHERE subject = {param} AND grade = {param} AND name = {param}
            """, (pending_exam['subject'], pq['curriculum_grade'] or pending_exam['grade'], chapter_name))
            chapter = cursor.fetchone()
            if chapter:
                chapter_id = chapter['id']
            else:
                chapter_insert = f"""
                    INSERT INTO chapters (subject, grade, name)
                    VALUES ({param}, {param}, {param})
                """
                if is_postgres():
                    chapter_insert += " RETURNING id"
                cursor.execute(chapter_insert, (pending_exam['subject'], pq['curriculum_grade'] or pending_exam['grade'], chapter_name))
                chapter_id = cursor.fetchone()['id'] if is_postgres() else cursor.lastrowid

            cursor.execute(f"""
                INSERT INTO questions (
                    exam_id, chapter_id, question_number, source_year, question_text,
                    option_a, option_b, option_c, option_d,
                    correct_answer, explanation, passage_text, diagram_instruction,
                    curriculum_unit_id, curriculum_section_id,
                    classification_confidence, classification_reason
                )
                VALUES ({param}, {param}, {param}, {param}, {param}, {param}, {param}, {param},
                    {param}, {param}, {param}, {param}, {param}, {param}, {param}, {param}, {param})
            """, (
                exam_id,
                chapter_id,
                pq['question_number'],
                pq['source_year'],
                pq['question_text'],
                pq['option_a'] or '',
                pq['option_b'] or '',
                pq['option_c'] or '',
                pq['option_d'] or '',
                pq['correct_answer'] or 'A',
                pq['explanation'] or '',
                pq['passage_text'],
                pq['diagram_instruction'],
                unit_id,
                section_id,
                pq['confidence'],
                pq['classification_reason']
            ))
            inserted_count += 1

        cursor.execute(f"""
            UPDATE pending_exams 
            SET status = {param} 
            WHERE id = {param}
        """, ('approved', pending_exam_id))

        cursor.execute(f"""
            UPDATE resources 
            SET status = {param} 
            WHERE id = {param}
        """, ('published', pending_exam['resource_id']))

        conn.commit()
        
        return jsonify({
            "success": True,
            "message": f"Exam '{pending_exam['title']}' approved and published with {inserted_count} questions.",
            "exam_id": exam_id,
            "question_count": inserted_count
        })

    except Exception as e:
        conn.rollback()
        print(f"ERROR approving exam: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/admin/pending_exams/<int:pending_exam_id>/reject', methods=['POST'])
@admin_required
def reject_pending_exam(pending_exam_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    param = get_param_style()
    
    try:
        cursor.execute(f"""
            UPDATE pending_exams 
            SET status = {param} 
            WHERE id = {param}
        """, ('rejected', pending_exam_id))
        conn.commit()
        return jsonify({"success": True, "message": "Pending exam rejected."})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/admin/pending_exams/<int:pending_exam_id>', methods=['DELETE'])
@admin_required
def delete_pending_exam(pending_exam_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    param = get_param_style()
    
    try:
        cursor.execute(f"""
            SELECT resource_id FROM pending_exams WHERE id = {param}
        """, (pending_exam_id,))
        result = cursor.fetchone()
        
        if result:
            resource_id = result['resource_id']
            cursor.execute(f"""
                DELETE FROM pending_questions WHERE pending_exam_id = {param}
            """, (pending_exam_id,))
            cursor.execute(f"""
                DELETE FROM pending_exams WHERE id = {param}
            """, (pending_exam_id,))
            cursor.execute(f"""
                DELETE FROM resources WHERE id = {param}
            """, (resource_id,))
        
        conn.commit()
        return jsonify({"success": True, "message": "Pending exam deleted."})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

# ============================================
# AI TUTOR - TUTOR HELPER FUNCTIONS
# ============================================

def get_tutor_thread(user_id, thread_id):
    """Get a specific thread for a user"""
    conn = get_db_connection()
    cursor = conn.cursor()
    param = get_param_style()
    
    try:
        if is_postgres():
            cursor.execute(f"""
                SELECT id, title, created_at, updated_at 
                FROM tutor_threads 
                WHERE id = {param}::integer AND user_id = {param}::integer
            """, (thread_id, user_id))
        else:
            cursor.execute(f"""
                SELECT id, title, created_at, updated_at 
                FROM tutor_threads 
                WHERE id = {param} AND user_id = {param}
            """, (thread_id, user_id))
        
        thread = cursor.fetchone()
        cursor.close()
        conn.close()
        return dict(thread) if thread else None
    except Exception as e:
        print(f"Error getting thread: {e}")
        cursor.close()
        conn.close()
        return None

def create_tutor_thread(user_id, title="New Conversation"):
    """Create a new tutor thread for a user"""
    conn = get_db_connection()
    cursor = conn.cursor()
    param = get_param_style()
    
    try:
        if is_postgres():
            cursor.execute(f"""
                INSERT INTO tutor_threads (user_id, title) 
                VALUES ({param}::integer, {param}) 
                RETURNING id
            """, (user_id, title))
            thread_id = cursor.fetchone()['id']
        else:
            cursor.execute(f"""
                INSERT INTO tutor_threads (user_id, title) 
                VALUES ({param}, {param})
            """, (user_id, title))
            thread_id = cursor.lastrowid
        
        conn.commit()
        cursor.close()
        conn.close()
        return thread_id
    except Exception as e:
        print(f"Error creating thread: {e}")
        conn.rollback()
        cursor.close()
        conn.close()
        return None

def get_tutor_messages(thread_id, limit=50):
    """Get messages for a specific thread with limit"""
    conn = get_db_connection()
    cursor = conn.cursor()
    param = get_param_style()
    
    try:
        if is_postgres():
            cursor.execute(f"""
                SELECT id, sender_type, message_text, attachment_name, attachment_type, created_at
                FROM tutor_messages
                WHERE thread_id = {param}::integer
                ORDER BY created_at ASC
                LIMIT {param}::integer
            """, (thread_id, limit))
        else:
            cursor.execute(f"""
                SELECT id, sender_type, message_text, attachment_name, attachment_type, created_at
                FROM tutor_messages
                WHERE thread_id = {param}
                ORDER BY created_at ASC
                LIMIT {param}
            """, (thread_id, limit))
        
        messages = cursor.fetchall()
        cursor.close()
        conn.close()
        return [dict(m) for m in messages]
    except Exception as e:
        print(f"Error getting messages: {e}")
        cursor.close()
        conn.close()
        return []

def save_tutor_message(thread_id, sender_type, message_text, attachment_name=None, attachment_type=None):
    """Save a message to the tutor thread"""
    conn = get_db_connection()
    cursor = conn.cursor()
    param = get_param_style()
    
    try:
        if is_postgres():
            cursor.execute(f"""
                INSERT INTO tutor_messages (thread_id, sender_type, message_text, attachment_name, attachment_type)
                VALUES ({param}::integer, {param}, {param}, {param}, {param})
                RETURNING id
            """, (thread_id, sender_type, message_text, attachment_name, attachment_type))
            message_id = cursor.fetchone()['id']
        else:
            cursor.execute(f"""
                INSERT INTO tutor_messages (thread_id, sender_type, message_text, attachment_name, attachment_type)
                VALUES ({param}, {param}, {param}, {param}, {param})
            """, (thread_id, sender_type, message_text, attachment_name, attachment_type))
            message_id = cursor.lastrowid
        
        # Update thread timestamp
        if is_postgres():
            cursor.execute(f"""
                UPDATE tutor_threads 
                SET updated_at = CURRENT_TIMESTAMP 
                WHERE id = {param}::integer
            """, (thread_id,))
        else:
            cursor.execute(f"""
                UPDATE tutor_threads 
                SET updated_at = CURRENT_TIMESTAMP 
                WHERE id = {param}
            """, (thread_id,))
        
        conn.commit()
        cursor.close()
        conn.close()
        return message_id
    except Exception as e:
        print(f"Error saving message: {e}")
        conn.rollback()
        cursor.close()
        conn.close()
        return None

def get_all_tutor_threads(user_id):
    """Get all threads for a user"""
    conn = get_db_connection()
    cursor = conn.cursor()
    param = get_param_style()
    
    try:
        cursor.execute(f"""
            SELECT id, title, 
                   (SELECT COUNT(*) FROM tutor_messages WHERE thread_id = tutor_threads.id) as message_count,
                   updated_at
            FROM tutor_threads
            WHERE user_id = {param}
            ORDER BY updated_at DESC
        """, (user_id,))
        
        threads = cursor.fetchall()
        cursor.close()
        conn.close()
        return [dict(t) for t in threads]
    except Exception as e:
        print(f"Error getting threads: {e}")
        cursor.close()
        conn.close()
        return []

def delete_tutor_thread(user_id, thread_id):
    """Delete a thread and all its messages"""
    conn = get_db_connection()
    cursor = conn.cursor()
    param = get_param_style()
    
    try:
        if is_postgres():
            cursor.execute(f"""
                DELETE FROM tutor_threads 
                WHERE id = {param}::integer AND user_id = {param}::integer
            """, (thread_id, user_id))
        else:
            cursor.execute(f"""
                DELETE FROM tutor_threads 
                WHERE id = {param} AND user_id = {param}
            """, (thread_id, user_id))
        
        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        print(f"Error deleting thread: {e}")
        conn.rollback()
        cursor.close()
        conn.close()
        return False

def rename_tutor_thread(user_id, thread_id, new_title):
    """Rename a thread"""
    conn = get_db_connection()
    cursor = conn.cursor()
    param = get_param_style()
    
    try:
        if is_postgres():
            cursor.execute(f"""
                UPDATE tutor_threads 
                SET title = {param} 
                WHERE id = {param}::integer AND user_id = {param}::integer
            """, (new_title, thread_id, user_id))
        else:
            cursor.execute(f"""
                UPDATE tutor_threads 
                SET title = {param} 
                WHERE id = {param} AND user_id = {param}
            """, (new_title, thread_id, user_id))
        
        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        print(f"Error renaming thread: {e}")
        conn.rollback()
        cursor.close()
        conn.close()
        return False

def process_uploaded_file(file):
    """Process uploaded file and extract content"""
    if not file:
        return None, None, None
    
    filename = secure_filename(file.filename)
    file_ext = filename.rsplit('.', 1)[1].lower()
    
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=f".{file_ext}")
    file.save(temp_file.name)
    temp_file_path = temp_file.name
    temp_file.close()
    
    file_content = ""
    file_type = None
    uploaded_file_ref = None
    
    try:
        if file_ext in ['png', 'jpg', 'jpeg', 'gif', 'webp']:
            if client:
                uploaded_file_ref = client.files.upload(file=temp_file_path)
                while uploaded_file_ref.state.name == "PROCESSING":
                    time.sleep(1.5)
                    uploaded_file_ref = client.files.get(name=uploaded_file_ref.name)
            file_type = 'image'
            file_content = "Image uploaded for analysis."
            
        elif file_ext == 'pdf':
            from pypdf import PdfReader
            reader = PdfReader(temp_file_path)
            text_parts = []
            for page in reader.pages:
                text_parts.append(page.extract_text())
            file_content = "\n".join(text_parts)
            file_type = 'text'
            
        elif file_ext == 'txt':
            with open(temp_file_path, 'r', encoding='utf-8') as f:
                file_content = f.read()
            file_type = 'text'
            
        elif file_ext in ['mp3', 'wav', 'ogg', 'm4a']:
            try:
                recognizer = sr.Recognizer()
                with sr.AudioFile(temp_file_path) as source:
                    audio_data = recognizer.record(source)
                    file_content = recognizer.recognize_google(audio_data)
                    file_type = 'text'
            except Exception as e:
                file_content = "Could not transcribe audio."
                file_type = 'error'
                
        elif file_ext == 'docx':
            try:
                import docx
                doc = docx.Document(temp_file_path)
                file_content = "\n".join([para.text for para in doc.paragraphs])
                file_type = 'text'
            except:
                file_content = "DOCX support requires additional libraries."
                file_type = 'error'
        else:
            file_content = f"File type '{file_ext}' uploaded."
            file_type = 'text'
            
    except Exception as e:
        file_content = f"Error processing file: {str(e)}"
        file_type = 'error'
        print(f"File processing error: {e}")
    
    if os.path.exists(temp_file_path):
        try:
            os.unlink(temp_file_path)
        except:
            pass
    
    return file_content, file_type, uploaded_file_ref

def build_conversation_context(messages, max_messages=10):
    """Build conversation context from messages"""
    if not messages:
        return ""
    
    recent_messages = messages[-max_messages:]
    context = ""
    
    for msg in recent_messages:
        sender = "Student" if msg['sender_type'] == 'user' else "Assistant"
        context += f"{sender}: {msg['message_text']}\n"
    
    return context

def generate_ai_response(user_message, conversation_context, file_content=None, uploaded_file_ref=None):
    """Generate AI response using Gemini"""
    if not get_gemini_client():
        return "AI service is not configured. Please contact the administrator."
    
    context_parts = []
    
    if conversation_context:
        context_parts.append(f"Previous conversation:\n{conversation_context}")
    
    if user_message:
        context_parts.append(f"Student's new question: {user_message}")
    
    if file_content and file_content != "Image uploaded for analysis.":
        context_parts.append(f"Uploaded content: {file_content[:500]}{'...' if len(file_content) > 500 else ''}")
    
    if not context_parts:
        return "I didn't receive any message or file. How can I help you today?"
    
    full_prompt = f"""
You are EduVault's empathetic, world-class academic tutor for Ethiopian students.

**Instructions:**
1. Review the previous conversation to understand the context.
2. Answer the student's new question based on the full conversation history.
3. If the student asks a follow-up question, reference the previous discussion.
4. Provide clear, step-by-step explanations.
5. Use simple, encouraging English suitable for high school students.
6. For math and physics, include LaTeX formulas enclosed in $...$ or $$...$$.
7. If the student uploaded an image, analyze it and respond accordingly.
8. Be supportive and thorough in your explanations.

**Conversation Context (Previous messages):**
{conversation_context if conversation_context else 'No previous conversation.'}

**Student's New Question:**
{user_message}

**Additional Content:**
{file_content if file_content and file_content != "Image uploaded for analysis." else 'No additional content.'}

**Your Response:**
"""
    
    try:
        if uploaded_file_ref:
            response = client.models.generate_content(
                model="gemini-3.5-flash",
                contents=[uploaded_file_ref, full_prompt]
            )
            try:
                client.files.delete(name=uploaded_file_ref.name)
            except:
                pass
        else:
            response = client.models.generate_content(
                model="gemini-3.5-flash",
                contents=full_prompt
            )
        
        if response and response.text:
            return response.text
        else:
            return "I apologize, but I couldn't generate a response. Please try rephrasing your question."
    except Exception as e:
        return f"I encountered an error: {str(e)}. Please try again."

# ============================================
# AI TUTOR MAIN CHAT ENDPOINT
# ============================================

@app.route('/api/tutor/chat', methods=['POST'])
@login_required
def tutor_chat():
    """
    Handles text, images, and files for the AI Tutor.
    Maintains conversation context for follow-up questions.
    """
    try:
        user_id = session['user_id']
        thread_id = request.form.get('thread_id')
        user_message = request.form.get('message', '').strip()
        conversation_context = request.form.get('context', '').strip()
        
        print(f"DEBUG: Tutor chat request - user: {user_id}, thread: {thread_id}")
        print(f"DEBUG: Message: {user_message[:50] if user_message else 'empty'}...")
        print(f"DEBUG: Context length: {len(conversation_context)} chars")
        
        # --- Thread Management ---
        if not thread_id or thread_id in ['undefined', 'null', '']:
            thread_title = user_message[:50] if user_message else "New Conversation"
            thread_id = create_tutor_thread(user_id, thread_title)
            if not thread_id:
                return jsonify({"error": "Failed to create thread"}), 500
            print(f"DEBUG: Created new thread: {thread_id}")
        else:
            thread = get_tutor_thread(user_id, thread_id)
            if not thread:
                thread_title = user_message[:50] if user_message else "New Conversation"
                thread_id = create_tutor_thread(user_id, thread_title)
                print(f"DEBUG: Thread not found, created new: {thread_id}")
            else:
                print(f"DEBUG: Using existing thread: {thread_id}")
        
        thread_id = str(thread_id)
        
        # --- Save User Message ---
        if user_message:
            save_tutor_message(thread_id, 'user', user_message)
        
        # --- Process Uploaded File ---
        file_content = ""
        file_type = None
        uploaded_file_ref = None
        
        if 'file' in request.files:
            file = request.files['file']
            if file and allowed_file(file.filename):
                file_content, file_type, uploaded_file_ref = process_uploaded_file(file)
                
                if file_content and file_type != 'error':
                    save_tutor_message(
                        thread_id, 
                        'user', 
                        f"[File uploaded: {file.filename}]", 
                        file.filename, 
                        file_type
                    )
        
        # --- Get conversation history for context ---
        if not conversation_context:
            messages = get_tutor_messages(thread_id, limit=20)
            conversation_context = build_conversation_context(messages, max_messages=10)
            print(f"DEBUG: Built context from DB: {len(conversation_context)} chars")
        
        # --- Generate AI Response ---
        ai_response = generate_ai_response(
            user_message, 
            conversation_context, 
            file_content, 
            uploaded_file_ref
        )
        
        # Save AI Response 
        save_tutor_message(thread_id, 'ai', ai_response)
        
        print(f"DEBUG: Successfully processed request for thread {thread_id}")
        
        return jsonify({
            "response": ai_response,
            "thread_id": thread_id,
            "success": True
        })
        
    except Exception as e:
        print(f"ERROR in tutor_chat: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "error": str(e),
            "success": False
        }), 500
# AI TUTOR THREAD MANAGEMENT ENDPOINTS
@app.route('/api/tutor/threads', methods=['GET'])
@login_required
def get_tutor_threads_endpoint():
    """Returns a list of chat threads for the logged-in user."""
    try:
        threads = get_all_tutor_threads(session['user_id'])
        return jsonify(threads)
    except Exception as e:
        print(f"Error getting threads: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/tutor/threads/<int:thread_id>/messages', methods=['GET'])
@login_required
def get_tutor_messages_endpoint(thread_id):
    """Returns messages for a specific thread."""
    try:
        thread = get_tutor_thread(session['user_id'], thread_id)
        if not thread:
            return jsonify({"error": "Thread not found"}), 404
        
        messages = get_tutor_messages(thread_id, limit=100)
        return jsonify(messages)
    except Exception as e:
        print(f"Error getting messages: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/tutor/threads/<int:thread_id>', methods=['DELETE'])
@login_required
def delete_tutor_thread_endpoint(thread_id):
    """Deletes a chat thread and its messages."""
    try:
        success = delete_tutor_thread(session['user_id'], thread_id)
        if success:
            return jsonify({"success": True, "message": "Thread deleted"})
        else:
            return jsonify({"error": "Failed to delete thread"}), 500
    except Exception as e:
        print(f"Error deleting thread: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/tutor/threads/<int:thread_id>/rename', methods=['PUT'])
@login_required
def rename_tutor_thread_endpoint(thread_id):
    """Renames a chat thread."""
    try:
        data = request.get_json()
        new_title = data.get('title', '').strip()
        if not new_title:
            return jsonify({"error": "Title is required"}), 400
        
        success = rename_tutor_thread(session['user_id'], thread_id, new_title)
        if success:
            return jsonify({"success": True, "message": "Thread renamed"})
        else:
            return jsonify({"error": "Failed to rename thread"}), 500
    except Exception as e:
        print(f"Error renaming thread: {e}")
        return jsonify({"error": str(e)}), 500

# AI TUTOR SIMPLE CHAT (Legacy)
@app.route('/api/tutor/chat/simple', methods=['POST'])
@login_required
def tutor_chat_simple():
    """Simple text-only chat endpoint for backward compatibility."""
    try:
        data = request.get_json(silent=True) or {}
        user_message = (data.get("message") or "").strip()
        thread_id = data.get("thread_id")
        
        if not user_message:
            return jsonify({"error": "Message is required"}), 400
        
        if not get_gemini_client():
            return jsonify({"error": "GEMINI_API_KEY is not configured on the server."}), 500
        
        if not thread_id:
            thread_id = create_tutor_thread(session['user_id'], user_message[:50])
        else:
            thread = get_tutor_thread(session['user_id'], thread_id)
            if not thread:
                thread_id = create_tutor_thread(session['user_id'], user_message[:50])
        
        save_tutor_message(thread_id, 'user', user_message)
        
        messages = get_tutor_messages(thread_id, limit=20)
        conversation_context = build_conversation_context(messages, max_messages=10)
        
        ai_response = generate_ai_response(user_message, conversation_context)
        
        save_tutor_message(thread_id, 'ai', ai_response)
        
        return jsonify({
            "response": ai_response,
            "thread_id": str(thread_id),
            "model": "gemini-3.5-flash"
        })
        
    except Exception as error:
        print(f"ERROR in tutor_chat_simple: {error}")
        return jsonify({
            "error": "AI Tutor is temporarily unavailable.",
            "details": str(error)
        }), 503

# AI TUTOR STATS ENDPOINT
@app.route('/api/tutor/stats', methods=['GET'])
@login_required
def get_tutor_stats():
    """Get tutor usage statistics for the user."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        param = get_param_style()
        
        cursor.execute(f"""
            SELECT COUNT(*) as total_messages
            FROM tutor_messages
            WHERE thread_id IN (SELECT id FROM tutor_threads WHERE user_id = {param})
        """, (session['user_id'],))
        total_messages = cursor.fetchone()['total_messages'] or 0
        
        cursor.execute(f"""
            SELECT COUNT(*) as total_threads
            FROM tutor_threads
            WHERE user_id = {param}
        """, (session['user_id'],))
        total_threads = cursor.fetchone()['total_threads'] or 0
        
        cursor.execute(f"""
            SELECT MAX(updated_at) as last_activity
            FROM tutor_threads
            WHERE user_id = {param}
        """, (session['user_id'],))
        last_activity = cursor.fetchone()['last_activity']
        
        cursor.close()
        conn.close()
        
        return jsonify({
            "total_messages": total_messages,
            "total_threads": total_threads,
            "last_activity": last_activity
        })
    except Exception as e:
        print(f"Error getting stats: {e}")
        return jsonify({"error": str(e)}), 500

# AI TUTOR SEARCH ENDPOINT
@app.route('/api/tutor/search', methods=['GET'])
@login_required
def search_tutor_messages():
    """Search through tutor messages for a user."""
    try:
        query = request.args.get('q', '').strip()
        if not query or len(query) < 3:
            return jsonify({"error": "Search query must be at least 3 characters"}), 400
        
        conn = get_db_connection()
        cursor = conn.cursor()
        param = get_param_style()
        
        if is_postgres():
            cursor.execute(f"""
                SELECT tm.*, tt.title as thread_title
                FROM tutor_messages tm
                JOIN tutor_threads tt ON tm.thread_id = tt.id
                WHERE tt.user_id = {param}::integer
                AND tm.message_text ILIKE {param}
                ORDER BY tm.created_at DESC
                LIMIT 50
            """, (session['user_id'], f'%{query}%'))
        else:
            cursor.execute(f"""
                SELECT tm.*, tt.title as thread_title
                FROM tutor_messages tm
                JOIN tutor_threads tt ON tm.thread_id = tt.id
                WHERE tt.user_id = {param}
                AND tm.message_text LIKE {param}
                ORDER BY tm.created_at DESC
                LIMIT 50
            """, (session['user_id'], f'%{query}%'))
        
        results = cursor.fetchall()
        cursor.close()
        conn.close()
        
        return jsonify([dict(r) for r in results])
    except Exception as e:
        print(f"Error searching messages: {e}")
        return jsonify({"error": str(e)}), 500

# ============================================
# AI TUTOR EXPORT ENDPOINT
# ============================================

@app.route('/api/tutor/export/<int:thread_id>', methods=['GET'])
@login_required
def export_tutor_thread(thread_id):
    """Export a tutor thread as JSON or text."""
    try:
        thread = get_tutor_thread(session['user_id'], thread_id)
        if not thread:
            return jsonify({"error": "Thread not found"}), 404
        
        messages = get_tutor_messages(thread_id, limit=1000)
        
        export_data = {
            "thread_id": thread_id,
            "title": thread['title'],
            "created_at": thread['created_at'],
            "updated_at": thread['updated_at'],
            "messages": messages
        }
        
        format_type = request.args.get('format', 'json')
        if format_type == 'text':
            text_output = f"Thread: {thread['title']}\n"
            text_output += f"Created: {thread['created_at']}\n"
            text_output += "=" * 50 + "\n\n"
            
            for msg in messages:
                sender = "Student" if msg['sender_type'] == 'user' else "Assistant"
                text_output += f"[{sender}] {msg['message_text']}\n\n"
            
            return text_output, 200, {'Content-Type': 'text/plain'}
        
        return jsonify(export_data)
    except Exception as e:
        print(f"Error exporting thread: {e}")
        return jsonify({"error": str(e)}), 500

# ============================================
# Unified Exam System: shared SQL persistence
# ============================================
UNIFIED_COLLECTIONS = {'results', 'students', 'examFiles', 'examPackages', 'examSchedules', 'examArchive'}

def ensure_unified_exam_table(conn):
    """Create the generic record table in the same active Edu-Vault SQL database."""
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS unified_exam_records (
        collection_name TEXT NOT NULL, record_id TEXT NOT NULL, payload TEXT NOT NULL,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (collection_name, record_id))""")
    cur.execute("""CREATE TABLE IF NOT EXISTS unified_exam_files (
        file_id TEXT PRIMARY KEY, filename TEXT NOT NULL, content_type TEXT,
        file_data BYTEA NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    conn.commit()
    cur.close()

@app.route('/api/unified-exam/health', methods=['GET'])
def unified_exam_health():
    conn = None
    try:
        conn = get_db_connection(); ensure_unified_exam_table(conn); cur = conn.cursor(); cur.execute('SELECT 1'); cur.close()
        return jsonify({'success': True, 'database': 'Edu-Vault SQL', 'driver': 'postgresql' if is_postgres() else 'sqlite'})
    except Exception as e:
        print(f'Unified exam database health check failed: {e}')
        return jsonify({'success': False, 'error': 'Edu-Vault database is unavailable'}), 503
    finally:
        if conn is not None: conn.close()

@app.route('/api/unified-exam/records/<collection_name>', methods=['GET'])
def unified_exam_list_records(collection_name):
    if collection_name not in UNIFIED_COLLECTIONS: return jsonify({'error': 'Unsupported record collection'}), 404
    conn = None
    try:
        conn = get_db_connection(); ensure_unified_exam_table(conn); param = get_param_style(); cur = conn.cursor()
        cur.execute(f'SELECT record_id, payload FROM unified_exam_records WHERE collection_name = {param} ORDER BY updated_at DESC', (collection_name,))
        records = []
        for row in cur.fetchall():
            rid = row['record_id'] if hasattr(row, 'keys') else row[0]
            raw = row['payload'] if hasattr(row, 'keys') else row[1]
            try: payload = json.loads(raw)
            except Exception: payload = {}
            records.append({'id': rid, 'data': payload})
        cur.close(); return jsonify({'records': records})
    except Exception as e:
        print(f'Unified exam record list failed ({collection_name}): {e}')
        return jsonify({'error': 'Could not read exam records'}), 500
    finally:
        if conn is not None: conn.close()

@app.route('/api/unified-exam/records/<collection_name>/<path:record_id>', methods=['PUT', 'DELETE'])
def unified_exam_record(collection_name, record_id):
    if collection_name not in UNIFIED_COLLECTIONS: return jsonify({'error': 'Unsupported record collection'}), 404
    conn = None
    try:
        conn = get_db_connection(); ensure_unified_exam_table(conn); param = get_param_style(); cur = conn.cursor()
        if request.method == 'DELETE':
            cur.execute(f'DELETE FROM unified_exam_records WHERE collection_name = {param} AND record_id = {param}', (collection_name, record_id))
            conn.commit(); cur.close(); return jsonify({'success': True, 'deleted': True})
        body = request.get_json(silent=True) or {}; incoming = body.get('data')
        if not isinstance(incoming, dict): return jsonify({'error': 'Record data must be a JSON object'}), 400
        if body.get('merge'):
            cur.execute(f'SELECT payload FROM unified_exam_records WHERE collection_name = {param} AND record_id = {param}', (collection_name, record_id))
            old = cur.fetchone()
            if old:
                raw = old['payload'] if hasattr(old, 'keys') else old[0]
                try: prior = json.loads(raw)
                except Exception: prior = {}
                prior.update(incoming); incoming = prior
        payload = json.dumps(incoming, ensure_ascii=False, separators=(',', ':'))
        sql = f"INSERT INTO unified_exam_records (collection_name, record_id, payload, updated_at) VALUES ({param}, {param}, {param}, CURRENT_TIMESTAMP) ON CONFLICT (collection_name, record_id) DO UPDATE SET payload = excluded.payload, updated_at = CURRENT_TIMESTAMP"
        cur.execute(sql, (collection_name, record_id, payload)); conn.commit(); cur.close()
        return jsonify({'success': True, 'id': record_id})
    except Exception as e:
        print(f'Unified exam record save failed ({collection_name}/{record_id}): {e}')
        if conn is not None:
            try: conn.rollback()
            except Exception: pass
        return jsonify({'error': 'Could not save exam record'}), 500
    finally:
        if conn is not None: conn.close()

@app.route('/api/unified-exam/files', methods=['POST'])
def unified_exam_upload_file():
    uploaded = request.files.get('file')
    if not uploaded or not uploaded.filename:
        return jsonify({'error': 'Choose a file to upload'}), 400
    content = uploaded.read(MAX_FILE_SIZE + 1)
    if len(content) > MAX_FILE_SIZE:
        return jsonify({'error': 'File exceeds the 16 MB upload size limit'}), 413
    safe_name = secure_filename(uploaded.filename) or 'exam-file'
    file_id = uuid.uuid4().hex
    conn = None
    try:
        conn = get_db_connection(); ensure_unified_exam_table(conn); param = get_param_style(); cur = conn.cursor()
        cur.execute(f"INSERT INTO unified_exam_files (file_id, filename, content_type, file_data) VALUES ({param}, {param}, {param}, {param})",
                    (file_id, safe_name, uploaded.mimetype or 'application/octet-stream', content))
        conn.commit(); cur.close()
        public_url = url_for('unified_exam_download_file', filename=file_id)
        return jsonify({'success': True, 'url': public_url, 'name': safe_name, 'path': file_id})
    except Exception as e:
        print(f'Unified exam file upload failed: {e}')
        if conn is not None:
            try: conn.rollback()
            except Exception: pass
        return jsonify({'error': 'Could not store the uploaded file in the Edu-Vault database'}), 500
    finally:
        if conn is not None: conn.close()

@app.route('/api/unified-exam/files/<path:filename>', methods=['GET'])
def unified_exam_download_file(filename):
    conn = None
    try:
        conn = get_db_connection(); ensure_unified_exam_table(conn); param = get_param_style(); cur = conn.cursor()
        cur.execute(f'SELECT filename, content_type, file_data FROM unified_exam_files WHERE file_id = {param}', (filename,))
        row = cur.fetchone(); cur.close()
        if not row: return jsonify({'error': 'File not found'}), 404
        name = row['filename'] if hasattr(row, 'keys') else row[0]
        mime = row['content_type'] if hasattr(row, 'keys') else row[1]
        data = row['file_data'] if hasattr(row, 'keys') else row[2]
        return send_file(BytesIO(bytes(data)), mimetype=mime or 'application/octet-stream', as_attachment=False, download_name=name)
    except Exception as e:
        print(f'Unified exam file download failed: {e}')
        return jsonify({'error': 'Could not retrieve uploaded file'}), 500
    finally:
        if conn is not None: conn.close()


@app.route('/api/unified-exam/generated-practice')
@unified_account_required
def unified_generated_practice_exams():
    """Expose SQL curriculum-generator exams to the separate Unified Exam UI."""
    conn = get_db_connection()
    cur = conn.cursor()
    p = get_param_style()
    try:
        allowed_categories = ['Curriculum Practice']
        owner_user_id = None
        if session.get('unified_role') == 'admin':
            allowed_categories.append('AI Generated Practice')
        else:
            cur.execute(f"SELECT student_code FROM unified_accounts WHERE id = {p} AND role = 'student'",
                        (session.get('unified_account_id'),))
            account = cur.fetchone()
            if account and account['student_code']:
                cur.execute(f"SELECT id FROM users WHERE student_code = {p} AND role = 'student'",
                            (account['student_code'],))
                owner = cur.fetchone()
                if owner:
                    owner_user_id = owner['id']
        category_filter = f"e.category = {p}"
        query_params = ['Curriculum Practice']
        if 'AI Generated Practice' in allowed_categories:
            category_filter = f"e.category IN ({p}, {p})"
            query_params = ['Curriculum Practice', 'AI Generated Practice']
        elif owner_user_id is not None:
            category_filter = f"(e.category = {p} OR (e.category = {p} AND EXISTS (SELECT 1 FROM generated_exam_owners o WHERE o.exam_id = e.id AND o.user_id = {p} AND o.status = 'active')))"
            query_params = ['Curriculum Practice', 'AI Generated Practice', owner_user_id]
        cur.execute(f"""
            SELECT e.id, e.title, e.subject, e.grade, e.duration_minutes, e.instructions,
                   q.id AS question_id, q.question_text, q.option_a, q.option_b,
                   q.option_c, q.option_d, q.correct_answer, q.explanation,
                   q.passage_text, q.diagram_instruction, q.question_number
            FROM exams e
            LEFT JOIN questions q ON q.exam_id = e.id
            WHERE {category_filter}
            ORDER BY e.id DESC, q.id ASC
        """, tuple(query_params))
        exams = {}
        for row in cur.fetchall():
            item = dict(row)
            exam_id = str(item['id'])
            if exam_id not in exams:
                exams[exam_id] = {
                    'id': f"generated-{exam_id}", 'sourceExamId': item['id'],
                    'title': item['title'], 'subject': item['subject'],
                    'grade': item['grade'], 'duration': max(60, int(item.get('duration_minutes') or 30) * 60),
                    'instructions': item.get('instructions') or 'Choose the best answer for each question.',
                    'questions': []
                }
            if item.get('question_id') is None:
                continue
            options = [item.get(f'option_{letter}') or '' for letter in ('a', 'b', 'c', 'd')]
            correct_raw = str(item.get('correct_answer') or '').strip()
            correct_index = next((i for i, letter in enumerate(('A', 'B', 'C', 'D')) if re.match(rf'^{letter}(?:[).:\s]|$)', correct_raw, re.I)), None)
            if correct_index is None:
                correct_index = next((i for i, option in enumerate(options) if option and correct_raw == option), 0)
            exams[exam_id]['questions'].append({
                'number': item.get('question_number') or len(exams[exam_id]['questions']) + 1,
                'q': item.get('question_text') or '', 'o': options, 'a': correct_index,
                'explanation': item.get('explanation') or '', 'passage': item.get('passage_text') or '',
                'diagramInstruction': item.get('diagram_instruction') or ''
            })
        return jsonify({'exams': list(exams.values())})
    except Exception:
        app.logger.exception('Could not load generated practice exams')
        return jsonify({'error': 'Could not load generated practice exams.'}), 500
    finally:
        cur.close()
        conn.close()


@app.route('/api/unified-exam/explanations', methods=['POST'])
@unified_account_required
def save_unified_exam_explanation():
    data = request.form
    pdf_file = request.files.get('pdf')
    try:
        result = json.loads(data.get('result') or '')
    except (TypeError, ValueError):
        result = None
    if not isinstance(result, dict) or not isinstance(result.get('questionResults'), list):
        return jsonify({'error': 'A completed exam result with question explanations is required.'}), 400
    if not pdf_file:
        return jsonify({'error': 'Create the exam explanation PDF before saving it.'}), 400
    pdf_content = pdf_file.read()
    if not pdf_content.startswith(b'%PDF-') or not pdf_content.rstrip().endswith(b'%%EOF'):
        return jsonify({'error': 'The uploaded explanation file is not a valid PDF.'}), 400
    if len(pdf_content) > 12 * 1024 * 1024:
        return jsonify({'error': 'The explanation PDF is larger than the 12 MB limit.'}), 413

    account_id = str(session.get('unified_account_id'))
    record_id = f"{account_id}-{uuid.uuid4().hex}"
    pdf_filename = f'{record_id}.pdf'
    pdf_path = os.path.join(EXAM_EXPLANATION_FOLDER, pdf_filename)
    payload = {'account_id': account_id, 'result': result, 'pdf_filename': pdf_filename,
               'saved_at': datetime.utcnow().isoformat() + 'Z'}
    conn = None
    cur = None
    try:
        with open(pdf_path, 'wb') as pdf_file:
            pdf_file.write(pdf_content)
        conn = get_db_connection()
        ensure_unified_exam_table(conn)
        cur = conn.cursor()
        p = get_param_style()
        cur.execute(
            f"INSERT INTO unified_exam_records (collection_name, record_id, payload, updated_at) VALUES ({p}, {p}, {p}, CURRENT_TIMESTAMP)",
            ('examExplanations', record_id, json.dumps(payload, ensure_ascii=False, separators=(',', ':')))
        )
        conn.commit()
        cur.close()
        cur = None
        return jsonify({'success': True, 'id': record_id,
                        'url': url_for('unified_exam_explanation_page', explanation_id=record_id),
                        'resource_url': url_for('resources_hub', collection='explanations')})
    except Exception:
        if conn:
            conn.rollback()
        try:
            os.remove(pdf_path)
        except OSError:
            pass
        app.logger.exception('Could not save exam explanation resource')
        return jsonify({'error': 'Could not save this explanation in EduVault.'}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route('/api/unified-exam/explanations', methods=['GET'])
@unified_account_required
def list_unified_exam_explanations():
    """List only the signed-in Unified Exam student's saved explanation resources."""
    conn = get_db_connection()
    try:
        ensure_unified_exam_table(conn)
        cur = conn.cursor()
        p = get_param_style()
        cur.execute(f"SELECT record_id, payload FROM unified_exam_records WHERE collection_name = {p} ORDER BY updated_at DESC",
                    ('examExplanations',))
        account_id = str(session.get('unified_account_id'))
        items = []
        for row in cur.fetchall():
            record_id = row['record_id'] if hasattr(row, 'keys') else row[0]
            raw = row['payload'] if hasattr(row, 'keys') else row[1]
            try:
                resource = json.loads(raw)
            except (TypeError, ValueError):
                continue
            if str(resource.get('account_id')) != account_id:
                continue
            result = resource.get('result') or {}
            items.append({
                'id': record_id,
                'title': result.get('title') or 'Exam Explanation',
                'subject': result.get('subject') or 'Examination',
                'grade': result.get('grade'),
                'saved_at': resource.get('saved_at'),
                'url': url_for('unified_exam_explanation_page', explanation_id=record_id)
            })
        cur.close()
        return jsonify(items)
    finally:
        conn.close()


@app.route('/api/unified-exam/explanations/<path:explanation_id>/pdf')
@unified_account_required
def unified_exam_explanation_pdf(explanation_id):
    conn = get_db_connection()
    cur = conn.cursor()
    p = get_param_style()
    try:
        cur.execute(
            f"SELECT payload FROM unified_exam_records WHERE collection_name = {p} AND record_id = {p}",
            ('examExplanations', explanation_id)
        )
        row = cur.fetchone()
        if not row:
            abort(404)
        raw = row['payload'] if hasattr(row, 'keys') else row[0]
        resource = json.loads(raw)
        if str(resource.get('account_id')) != str(session.get('unified_account_id')):
            abort(404)
        filename = os.path.basename(str(resource.get('pdf_filename') or ''))
        if not filename or filename != f'{explanation_id}.pdf':
            abort(404)
        title = secure_filename(str((resource.get('result') or {}).get('title') or 'Exam Explanation')) or 'Exam-Explanation'
        response = send_from_directory(EXAM_EXPLANATION_FOLDER, filename, mimetype='application/pdf',
                                       as_attachment=False, download_name=f'{title}.pdf')
        response.headers['Content-Disposition'] = f'inline; filename="{title}.pdf"'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['Cache-Control'] = 'private, no-store'
        return response
    finally:
        cur.close()
        conn.close()


@app.route('/eduvault-system/explanations/<path:explanation_id>')
@unified_account_required
def unified_exam_explanation_page(explanation_id):
    conn = get_db_connection()
    cur = conn.cursor()
    p = get_param_style()
    try:
        cur.execute(
            f"SELECT payload FROM unified_exam_records WHERE collection_name = {p} AND record_id = {p}",
            ('examExplanations', explanation_id)
        )
        row = cur.fetchone()
        if not row:
            abort(404)
        raw = row['payload'] if hasattr(row, 'keys') else row[0]
        resource = json.loads(raw)
        if str(resource.get('account_id')) != str(session.get('unified_account_id')):
            abort(404)
        pdf_url = (url_for('unified_exam_explanation_pdf', explanation_id=explanation_id)
                   if resource.get('pdf_filename') else None)
        return render_template('exam_explanation.html', result=resource.get('result') or {},
                               saved_at=resource.get('saved_at'), pdf_url=pdf_url)
    finally:
        cur.close()
        conn.close()


# ============================================================
# EDUVAULT CURRICULUM UPGRADE: BLOOM, VIDEOS, NOTES, ANALYTICS
# ============================================================

BLOOM_CATEGORIES = (
    "Remember", "Understand", "Apply", "Analyze", "Evaluate", "Create"
)
PRACTICE_GENERATOR_SUBJECTS = (
    'Mathematics', 'Physics', 'Chemistry', 'Biology', 'English',
    'Geography', 'History', 'Economics', 'Aptitude'
)


def ensure_learning_upgrade_schema():
    """Create additive tables only; never delete or rewrite existing student data."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        if is_postgres():
            cur.execute("ALTER TABLE user_results ADD COLUMN IF NOT EXISTS examination_mode TEXT NOT NULL DEFAULT 'exam'")
            cur.execute("ALTER TABLE exams ADD COLUMN IF NOT EXISTS duration_minutes INTEGER")
            cur.execute("ALTER TABLE exams ADD COLUMN IF NOT EXISTS examination_type TEXT")
            cur.execute("ALTER TABLE pending_exams ADD COLUMN IF NOT EXISTS examination_type TEXT")
            cur.execute("ALTER TABLE pending_exams ADD COLUMN IF NOT EXISTS duration_minutes INTEGER")
            cur.execute("ALTER TABLE resources ADD COLUMN IF NOT EXISTS examination_type TEXT")
            cur.execute("ALTER TABLE resources ADD COLUMN IF NOT EXISTS source_hash TEXT")
            cur.execute("ALTER TABLE pending_exams ADD COLUMN IF NOT EXISTS source_hash TEXT")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS question_bloom_tags (
                    question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
                    category TEXT NOT NULL,
                    confidence TEXT NOT NULL DEFAULT 'Unverified',
                    reviewed_by INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (question_id, category)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS tutorial_videos (
                    id SERIAL PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    grade INTEGER NOT NULL,
                    subject TEXT NOT NULL,
                    unit_title TEXT DEFAULT '',
                    chapter_title TEXT DEFAULT '',
                    topic_title TEXT DEFAULT '',
                    video_url TEXT NOT NULL,
                    duration TEXT DEFAULT '',
                    language TEXT DEFAULT 'English',
                    source_name TEXT DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'draft',
                    created_by INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS revision_notes (
                    id SERIAL PRIMARY KEY,
                    title TEXT NOT NULL,
                    grade INTEGER NOT NULL,
                    subject TEXT NOT NULL,
                    unit_title TEXT DEFAULT '',
                    chapter_title TEXT DEFAULT '',
                    topic_title TEXT DEFAULT '',
                    summary TEXT DEFAULT '',
                    content TEXT NOT NULL DEFAULT '',
                    source_attribution TEXT DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'draft',
                    created_by INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_answer_details (
                    id SERIAL PRIMARY KEY,
                    result_id INTEGER NOT NULL REFERENCES user_results(id) ON DELETE CASCADE,
                    question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
                    submitted_answer TEXT DEFAULT '',
                    is_correct INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(result_id, question_id)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS generated_exam_owners (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    exam_id INTEGER NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, exam_id)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS exam_attempts (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    exam_id INTEGER NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
                    examination_mode TEXT NOT NULL CHECK (examination_mode IN ('practice', 'exam')),
                    started_at_epoch DOUBLE PRECISION NOT NULL,
                    duration_seconds INTEGER NOT NULL,
                    submitted_at_epoch DOUBLE PRECISION,
                    time_taken_seconds INTEGER,
                    total_questions INTEGER,
                    correct_answers INTEGER,
                    incorrect_answers INTEGER,
                    unanswered_questions INTEGER,
                    score FLOAT,
                    status TEXT NOT NULL DEFAULT 'in_progress' CHECK (status IN ('in_progress', 'submitted', 'expired'))
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS attempt_answers (
                    id SERIAL PRIMARY KEY,
                    attempt_id INTEGER NOT NULL REFERENCES exam_attempts(id) ON DELETE CASCADE,
                    question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
                    selected_answer TEXT,
                    is_flagged INTEGER NOT NULL DEFAULT 0,
                    answered_at_epoch DOUBLE PRECISION,
                    UNIQUE(attempt_id, question_id)
                )
            """)
        else:
            existing_exam_columns = {row[1] for row in cur.execute("PRAGMA table_info(exams)").fetchall()}
            if "duration_minutes" not in existing_exam_columns:
                cur.execute("ALTER TABLE exams ADD COLUMN duration_minutes INTEGER")
            if "examination_type" not in existing_exam_columns:
                cur.execute("ALTER TABLE exams ADD COLUMN examination_type TEXT")
            existing_result_columns = {row[1] for row in cur.execute("PRAGMA table_info(user_results)").fetchall()}
            if "examination_mode" not in existing_result_columns:
                cur.execute("ALTER TABLE user_results ADD COLUMN examination_mode TEXT NOT NULL DEFAULT 'exam'")
            for table, columns in (("pending_exams", {row[1] for row in cur.execute("PRAGMA table_info(pending_exams)").fetchall()}),
                                   ("resources", {row[1] for row in cur.execute("PRAGMA table_info(resources)").fetchall()})):
                if "examination_type" not in columns:
                    cur.execute(f"ALTER TABLE {table} ADD COLUMN examination_type TEXT")
                if "source_hash" not in columns:
                    cur.execute(f"ALTER TABLE {table} ADD COLUMN source_hash TEXT")
                if table == "pending_exams" and "duration_minutes" not in columns:
                    cur.execute("ALTER TABLE pending_exams ADD COLUMN duration_minutes INTEGER")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS question_bloom_tags (
                    question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
                    category TEXT NOT NULL,
                    confidence TEXT NOT NULL DEFAULT 'Unverified',
                    reviewed_by INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (question_id, category)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS tutorial_videos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    grade INTEGER NOT NULL,
                    subject TEXT NOT NULL,
                    unit_title TEXT DEFAULT '',
                    chapter_title TEXT DEFAULT '',
                    topic_title TEXT DEFAULT '',
                    video_url TEXT NOT NULL,
                    duration TEXT DEFAULT '',
                    language TEXT DEFAULT 'English',
                    source_name TEXT DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'draft',
                    created_by INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS revision_notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    grade INTEGER NOT NULL,
                    subject TEXT NOT NULL,
                    unit_title TEXT DEFAULT '',
                    chapter_title TEXT DEFAULT '',
                    topic_title TEXT DEFAULT '',
                    summary TEXT DEFAULT '',
                    content TEXT NOT NULL DEFAULT '',
                    source_attribution TEXT DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'draft',
                    created_by INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_answer_details (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    result_id INTEGER NOT NULL REFERENCES user_results(id) ON DELETE CASCADE,
                    question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
                    submitted_answer TEXT DEFAULT '',
                    is_correct INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(result_id, question_id)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS generated_exam_owners (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    exam_id INTEGER NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, exam_id)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS exam_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    exam_id INTEGER NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
                    examination_mode TEXT NOT NULL CHECK (examination_mode IN ('practice', 'exam')),
                    started_at_epoch REAL NOT NULL,
                    duration_seconds INTEGER NOT NULL,
                    submitted_at_epoch REAL,
                    time_taken_seconds INTEGER,
                    total_questions INTEGER,
                    correct_answers INTEGER,
                    incorrect_answers INTEGER,
                    unanswered_questions INTEGER,
                    score REAL,
                    status TEXT NOT NULL DEFAULT 'in_progress' CHECK (status IN ('in_progress', 'submitted', 'expired'))
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS attempt_answers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    attempt_id INTEGER NOT NULL REFERENCES exam_attempts(id) ON DELETE CASCADE,
                    question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
                    selected_answer TEXT,
                    is_flagged INTEGER NOT NULL DEFAULT 0,
                    answered_at_epoch REAL,
                    UNIQUE(attempt_id, question_id)
                )
            """)
        for table, category_column in (("resources", "title"), ("exams", "category"), ("pending_exams", "title")):
            cur.execute(f"SELECT id, examination_type, resource_type, title, {category_column} AS legacy_category FROM {table}")
            for row in cur.fetchall():
                item = dict(row)
                if not item.get("examination_type"):
                    kind = normalize_examination_type(None, item.get("resource_type"), item.get("legacy_category"))
                    cur.execute(f"UPDATE {table} SET examination_type = {get_param_style()} WHERE id = {get_param_style()}",
                                (kind, item["id"]))
        cur.execute("CREATE INDEX IF NOT EXISTS idx_exams_examination_type ON exams(examination_type)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_pending_exams_examination_type ON pending_exams(examination_type)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_resources_examination_type ON resources(examination_type)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_exam_attempts_owner_exam ON exam_attempts(user_id, exam_id, status)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_attempt_answers_attempt ON attempt_answers(attempt_id)")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


@app.route('/exam-generator')
@login_required
def curriculum_exam_generator_page():
    return render_template('exam_generator.html', username=session.get('username'), role=session.get('role', 'student'))


@app.route('/video-learning')
@login_required
def curriculum_video_learning_page():
    return render_template('video_learning.html', username=session.get('username'), role=session.get('role', 'student'))


@app.route('/learning-notes')
@login_required
def revision_notes_page():
    return render_template('learning_notes.html', username=session.get('username'), role=session.get('role', 'student'))


@app.route('/learning-analytics')
@login_required
def learning_analytics_page():
    return render_template('learning_analytics.html', username=session.get('username'), role=session.get('role', 'student'))


@app.route('/api/learning/curriculum-options')
@login_required
def learning_curriculum_options():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT g.number AS grade, s.name AS subject
        FROM curriculum_grades g
        JOIN curriculum_units u ON u.grade_id = g.id
        JOIN curriculum_subjects s ON s.id = u.subject_id
        ORDER BY g.number, s.name
    """)
    rows = [dict(row) for row in cur.fetchall()]
    available = {(int(row['grade']), row['subject']) for row in rows}
    for grade in (9, 10, 11, 12):
        for subject in PRACTICE_GENERATOR_SUBJECTS:
            if (grade, subject) not in available:
                rows.append({'grade': grade, 'subject': subject})
    rows.sort(key=lambda row: (int(row['grade']), str(row['subject']).casefold()))
    cur.close()
    conn.close()
    return jsonify({"items": rows, "bloom_categories": list(BLOOM_CATEGORIES)})


@app.route('/api/learning/bloom-tags/<int:question_id>', methods=['GET'])
@login_required
def get_question_bloom_tags(question_id):
    conn = get_db_connection()
    cur = conn.cursor()
    p = get_param_style()
    cur.execute(f"SELECT category, confidence FROM question_bloom_tags WHERE question_id = {p} ORDER BY category", (question_id,))
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return jsonify(rows)


@app.route('/api/admin/questions/<int:question_id>/bloom-tags', methods=['PUT'])
@admin_required
def update_question_bloom_tags(question_id):
    data = request.get_json(silent=True) or {}
    categories = data.get('categories', [])
    confidence = data.get('confidence', 'Reviewed')
    if not isinstance(categories, list) or any(c not in BLOOM_CATEGORIES for c in categories):
        return jsonify({"error": "Choose one or more valid Bloom's taxonomy categories."}), 400
    if confidence not in ('Unverified', 'Low', 'Medium', 'High', 'Reviewed'):
        return jsonify({"error": "Invalid confidence value."}), 400
    conn = get_db_connection()
    cur = conn.cursor()
    p = get_param_style()
    try:
        cur.execute(f"SELECT id FROM questions WHERE id = {p}", (question_id,))
        if not cur.fetchone():
            return jsonify({"error": "Question not found."}), 404
        cur.execute(f"DELETE FROM question_bloom_tags WHERE question_id = {p}", (question_id,))
        for category in categories:
            cur.execute(
                f"INSERT INTO question_bloom_tags (question_id, category, confidence, reviewed_by) VALUES ({p}, {p}, {p}, {p})",
                (question_id, category, confidence, session.get('user_id'))
            )
        conn.commit()
        return jsonify({"success": True, "question_id": question_id, "categories": categories, "confidence": confidence})
    except Exception as exc:
        conn.rollback()
        app.logger.exception("Could not update Bloom taxonomy tags")
        return jsonify({"error": "Could not save the question categories."}), 500
    finally:
        cur.close()
        conn.close()


@app.route('/api/exam-generator/generate', methods=['POST'])
@login_required
def generate_curriculum_exam():
    data = request.get_json(silent=True) or {}
    try:
        grade = int(data.get('grade'))
        count = max(1, min(100, int(data.get('question_count', 20))))
        duration = max(5, min(240, int(data.get('duration_minutes', 30))))
    except (TypeError, ValueError):
        return jsonify({"error": "Select a valid grade, question count, and duration."}), 400
    subject = str(data.get('subject', '')).strip()
    categories = data.get('categories') or []
    unit_ids = data.get('unit_ids') or []
    section_ids = data.get('section_ids') or []
    if grade not in (9, 10, 11, 12) or not subject:
        return jsonify({"error": "Select a valid grade and subject."}), 400
    if not isinstance(categories, list) or any(c not in BLOOM_CATEGORIES for c in categories):
        return jsonify({"error": "One or more Bloom's taxonomy categories are invalid."}), 400
    try:
        unit_ids = [int(x) for x in unit_ids]
        section_ids = [int(x) for x in section_ids]
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid unit or topic selection."}), 400

    import random
    conn = get_db_connection()
    cur = conn.cursor()
    p = get_param_style()
    try:
        if not unit_ids and not section_ids:
            return jsonify({"error": "Choose at least one curriculum unit or section."}), 400
        scope_filters = [f"cs.name = {p}", f"g.number = {p}"]
        scope_values = [subject, grade]
        if unit_ids:
            scope_filters.append("u.id IN (" + ",".join([p] * len(unit_ids)) + ")")
            scope_values.extend(unit_ids)
        if section_ids:
            scope_filters.append("s.id IN (" + ",".join([p] * len(section_ids)) + ")")
            scope_values.extend(section_ids)
        cur.execute(f"""
            SELECT DISTINCT u.id AS unit_id, s.id AS section_id
            FROM curriculum_units u
            JOIN curriculum_subjects cs ON cs.id = u.subject_id
            JOIN curriculum_grades g ON g.id = u.grade_id
            LEFT JOIN curriculum_sections s ON s.unit_id = u.id
            WHERE {' AND '.join(scope_filters)}
        """, tuple(scope_values))
        valid_scope = cur.fetchall()
        valid_unit_ids = {int(row['unit_id']) for row in valid_scope}
        valid_section_ids = {int(row['section_id']) for row in valid_scope if row['section_id'] is not None}
        if any(value not in valid_unit_ids for value in unit_ids) or any(value not in valid_section_ids for value in section_ids):
            return jsonify({"error": "Selected units and sections must belong to this grade and subject."}), 400
        filters = [f"e.grade = {p}", f"e.subject = {p}", "q.correct_answer IS NOT NULL",
                   "TRIM(q.question_text) <> ''", "TRIM(q.option_a) <> ''", "TRIM(q.option_b) <> ''",
                   "TRIM(q.option_c) <> ''", "TRIM(q.option_d) <> ''"]
        params = [grade, subject]
        if unit_ids:
            filters.append("q.curriculum_unit_id IN (" + ",".join([p] * len(unit_ids)) + ")")
            params.extend(unit_ids)
        if section_ids:
            filters.append("q.curriculum_section_id IN (" + ",".join([p] * len(section_ids)) + ")")
            params.extend(section_ids)
        if categories:
            filters.append("EXISTS (SELECT 1 FROM question_bloom_tags bt WHERE bt.question_id = q.id AND bt.category IN (" + ",".join([p] * len(categories)) + "))")
            params.extend(categories)
        cur.execute("""
            SELECT q.id, q.question_text, q.option_a, q.option_b, q.option_c, q.option_d,
                   q.correct_answer, q.explanation, q.passage_text, q.diagram_instruction,
                   q.curriculum_unit_id, q.curriculum_section_id,
                   q.question_number, q.source_year, q.chapter_id
            FROM questions q JOIN exams e ON e.id = q.exam_id
            WHERE """ + " AND ".join(filters) + " ORDER BY q.id", tuple(params))
        pool = [dict(row) for row in cur.fetchall()]
        random.shuffle(pool)
        if len(pool) < count:
            return jsonify({
                "error": f"Only {len(pool)} eligible questions are available for this selection; {count} were requested.",
                "available": len(pool), "requested": count,
                "hint": "Ask an administrator to review question metadata or choose a broader curriculum scope."
            }), 400
        selected = pool[:count]
        title = f"Curriculum Practice — Grade {grade} {subject} — {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}"
        if is_postgres():
            cur.execute("""
                INSERT INTO exams (title, category, resource_type, subject, grade, instructions, total_marks, duration_minutes, examination_type)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
            """, (title, "Curriculum Practice", "Exam", subject, grade,
                  f"Generated from the selected curriculum. Duration: {duration} minutes.", count, duration, 'chapter_practice'))
            exam_id = cur.fetchone()['id']
        else:
            cur.execute("""
                INSERT INTO exams (title, category, resource_type, subject, grade, instructions, total_marks, duration_minutes, examination_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (title, "Curriculum Practice", "Exam", subject, grade,
                  f"Generated from the selected curriculum. Duration: {duration} minutes.", count, duration, 'chapter_practice'))
            exam_id = cur.lastrowid
        for q in selected:
            question_insert = f"""
                INSERT INTO questions
                (exam_id, chapter_id, question_text, option_a, option_b, option_c, option_d,
                 correct_answer, explanation, passage_text, diagram_instruction,
                 curriculum_unit_id, curriculum_section_id, question_number, source_year)
                VALUES ({', '.join([p] * 15)})
            """
            if is_postgres():
                question_insert += " RETURNING id"
            cur.execute(question_insert, (exam_id, q['chapter_id'], q['question_text'], q['option_a'], q['option_b'],
                  q['option_c'], q['option_d'], q['correct_answer'], q['explanation'] or '',
                  q['passage_text'], q['diagram_instruction'], q['curriculum_unit_id'],
                  q['curriculum_section_id'], q['question_number'], q['source_year']))
            new_qid = cur.fetchone()['id'] if is_postgres() else cur.lastrowid
            cur.execute(f"""
                INSERT INTO question_bloom_tags (question_id, category, confidence, reviewed_by)
                SELECT {p}, category, confidence, reviewed_by
                FROM question_bloom_tags WHERE question_id = {p}
            """, (new_qid, q['id']))
        conn.commit()
        return jsonify({"success": True, "exam_id": exam_id, "title": title, "question_count": count,
                        "duration_minutes": duration, "exam_url": url_for('exam_page', exam_id=exam_id),
                        "system_url": url_for('eduvault_system')})
    except Exception:
        conn.rollback()
        app.logger.exception("Exam generation failed")
        return jsonify({"error": "Exam generation failed. Check the server logs and database configuration."}), 500
    finally:
        cur.close()
        conn.close()


@app.route('/api/exam-generator/ai-generate', methods=['POST'])
@login_required
def generate_ai_curriculum_exam():
    data = request.get_json(silent=True) or {}
    try:
        grade = int(data.get('grade'))
        duration = max(5, min(240, int(data.get('duration_minutes', 30))))
        unit_ids = [int(value) for value in (data.get('unit_ids') or [])]
        section_ids = [int(value) for value in (data.get('section_ids') or [])]
        counts_raw = data.get('bloom_counts') or {}
        if not isinstance(counts_raw, dict):
            raise ValueError()
        bloom_counts = {category: int(counts_raw.get(category, 0) or 0) for category in BLOOM_CATEGORIES}
    except (TypeError, ValueError):
        return jsonify({'error': 'Choose a grade, duration, curriculum scope, and whole-number Bloom counts.'}), 400

    subject = str(data.get('subject') or '').strip()
    examination_type = str(data.get('examination_type') or 'chapter_practice').strip().lower()
    total = sum(bloom_counts.values())
    if examination_type not in ('chapter_practice', 'practical_question'):
        return jsonify({'error': 'Generated content must be Chapter Practice or Practical Questions.'}), 400
    if grade not in (9, 10, 11, 12) or subject not in PRACTICE_GENERATOR_SUBJECTS:
        return jsonify({'error': 'Choose a valid Grade 9–12 subject.'}), 400
    if any(value < 0 or value > 100 for value in bloom_counts.values()) or not 1 <= total <= 100:
        return jsonify({'error': 'Bloom counts must total between 1 and 100 questions.'}), 400
    try:
        gemini = get_gemini_client()
    except Exception:
        app.logger.exception('Gemini client initialization failed')
        gemini = None
    if not gemini:
        return jsonify({'error': 'EduVault practice questions are temporarily unavailable. Please contact support.'}), 503

    conn = get_db_connection()
    cur = conn.cursor()
    p = get_param_style()
    try:
        cur.execute(f"""
            SELECT u.id AS unit_id, u.unit_number, u.title AS unit_title,
                   s.id AS section_id, s.section_number, s.title AS section_title
            FROM curriculum_units u
            JOIN curriculum_subjects cs ON cs.id = u.subject_id
            JOIN curriculum_grades g ON g.id = u.grade_id
            LEFT JOIN curriculum_sections s ON s.unit_id = u.id
            WHERE cs.name = {p} AND g.number = {p}
            ORDER BY u.unit_number, s.section_number
        """, (subject, grade))
        curriculum_rows = [dict(row) for row in cur.fetchall()]
    finally:
        cur.close()
        conn.close()

    has_curriculum = bool(curriculum_rows)
    if not has_curriculum:
        return jsonify({'error': 'No curriculum sections are recorded for this grade and subject yet.'}), 400
    if not unit_ids and not section_ids:
        return jsonify({'error': 'Select at least one unit or section.'}), 400
    valid_units = {int(row['unit_id']) for row in curriculum_rows}
    if any(unit_id not in valid_units for unit_id in unit_ids):
        return jsonify({'error': 'A selected unit does not match this grade and subject.'}), 400
    scope_units = set(unit_ids) if unit_ids else valid_units
    valid_sections = {int(row['section_id']) for row in curriculum_rows if row.get('section_id') is not None and int(row['unit_id']) in scope_units}
    if any(section_id not in valid_sections for section_id in section_ids):
        return jsonify({'error': 'A selected section does not match the selected grade, subject, and unit.'}), 400
    scope_sections = set(section_ids) if section_ids else valid_sections
    section_map = {}
    for row in curriculum_rows:
        if row.get('section_id') is not None and int(row['unit_id']) in scope_units and int(row['section_id']) in scope_sections:
            section_map[int(row['section_id'])] = {
                'section_id': int(row['section_id']), 'unit_id': int(row['unit_id']), 'unit_number': row['unit_number'],
                'unit_title': row['unit_title'], 'section_number': row.get('section_number'),
                'section_title': row.get('section_title') or ''
            }
    if not section_map:
        return jsonify({'error': 'The selected unit or section has no curriculum sections.'}), 400
    sections = [section_map[section_id] for section_id in sorted(section_map)]
    section_prompt = sections
    scope_instruction = (
        f'Write questions suitable for Grade {grade} {subject}, only from the selected curriculum sections below. '
        'For Aptitude, stay within the selected aptitude sections. Assign every question the ID of the section it tests.'
    )

    questions = []
    try:
        remaining_counts = dict(bloom_counts)
        category_cursor = 0
        while sum(remaining_counts.values()):
            batch_size = min(10, sum(remaining_counts.values()))
            batch_categories = []
            while len(batch_categories) < batch_size:
                category = BLOOM_CATEGORIES[category_cursor % len(BLOOM_CATEGORIES)]
                category_cursor += 1
                if remaining_counts[category] > 0:
                    batch_categories.append(category)
                    remaining_counts[category] -= 1
            expected_counts = {category: batch_categories.count(category) for category in BLOOM_CATEGORIES}
            prompt = f"""Write exactly {batch_size} original multiple-choice questions for Grade {grade} {subject} in one batch.
The batch must match this exact Bloom category distribution: {json.dumps(expected_counts)}. Give every question its appropriate Bloom category.
{scope_instruction}
Return JSON only: {{"questions":[{{"question":"...","option_a":"...","option_b":"...","option_c":"...","option_d":"...","correct_answer":"A","explanation":"...","section_id":123,"bloom_category":"Remember"}}]}}
Each item must contain four plausible options, one correct letter A/B/C/D, a clear explanation, the requested section_id, and bloom_category exactly as requested. Do not repeat questions, invent facts, or return markdown.
Selected curriculum sections: {json.dumps(section_prompt, ensure_ascii=False)}"""
            try:
                response = gemini.models.generate_content(
                    model='gemini-3.8-flash', contents=prompt,
                    config=types.GenerateContentConfig(response_mime_type='application/json', max_output_tokens=8192, temperature=0.25)
                )
            except Exception as exc:
                raise RuntimeError('EduVault could not prepare this batch: ' + str(exc)) from exc
            if not response or not response.text:
                raise RuntimeError('EduVault could not prepare this batch. Please try again.')
            parsed = json.loads(response.text)
            batch = parsed.get('questions') if isinstance(parsed, dict) else None
            if not isinstance(batch, list) or len(batch) != batch_size:
                raise ValueError(f'EduVault could not prepare all {batch_size} questions in this batch. Please try again.')
            returned_counts = {category: 0 for category in BLOOM_CATEGORIES}
            for item in batch:
                if not isinstance(item, dict):
                    raise ValueError('EduVault returned a question in an unsupported format. Please try again.')
                question_text = str(item.get('question') or '').strip()
                options = [str(item.get(f'option_{letter}') or '').strip() for letter in 'abcd']
                answer = str(item.get('correct_answer') or '').strip().upper()
                category = str(item.get('bloom_category') or '').strip()
                try:
                    section_id = int(item.get('section_id')) if item.get('section_id') is not None else None
                except (TypeError, ValueError):
                    section_id = -1
                if not question_text or any(not option for option in options) or answer not in ('A', 'B', 'C', 'D'):
                    raise ValueError('A question was incomplete. Please try again.')
                if category not in returned_counts:
                    raise ValueError('A question had an invalid Bloom level. Please try again.')
                if section_id not in section_map:
                    raise ValueError('A question did not match the sections you selected. Please try again.')
                returned_counts[category] += 1
                questions.append({'question_text': question_text, 'options': options, 'answer': answer,
                                  'explanation': str(item.get('explanation') or '').strip(),
                                  'section': section_map[section_id], 'category': category})
            if returned_counts != expected_counts:
                raise ValueError('The questions did not match your Bloom counts. Please try again.')
    except (ValueError, RuntimeError, json.JSONDecodeError) as exc:
        app.logger.warning('AI practice exam generation failed validation: %s', exc)
        return jsonify({'error': str(exc)}), 502
    except Exception:
        app.logger.exception('Gemini question generation failed')
        return jsonify({'error': 'EduVault could not prepare your questions right now. Please try again shortly.'}), 502

    conn = get_db_connection()
    cur = conn.cursor()
    p = get_param_style()
    try:
        title_prefix = 'Practical Questions' if examination_type == 'practical_question' else 'Practice Questions'
        title = f"{title_prefix} — Grade {grade} {subject} — {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}"
        insert_exam = f"INSERT INTO exams (title, category, resource_type, subject, grade, instructions, total_marks, duration_minutes, examination_type) VALUES ({', '.join([p] * 9)})"
        if is_postgres():
            insert_exam += ' RETURNING id'
        category = 'AI Generated Practical Questions' if examination_type == 'practical_question' else 'AI Generated Practice'
        cur.execute(insert_exam, (title, category, 'Exam', subject, grade,
                                  f'EduVault practice from selected curriculum sections. Duration: {duration} minutes.', total, duration, examination_type))
        exam_id = cur.fetchone()['id'] if is_postgres() else cur.lastrowid
        for number, question in enumerate(questions, start=1):
            section = question['section']
            insert_question = f"""INSERT INTO questions
                (exam_id, chapter_id, question_text, option_a, option_b, option_c, option_d, correct_answer, explanation,
                 passage_text, diagram_instruction, curriculum_unit_id, curriculum_section_id, question_number, source_year)
                VALUES ({', '.join([p] * 15)})"""
            if is_postgres():
                insert_question += ' RETURNING id'
            cur.execute(insert_question, (exam_id, None, question['question_text'], *question['options'], question['answer'],
                                          question['explanation'], None, None,
                                          section['unit_id'],
                                          section['section_id'], number, None))
            question_id = cur.fetchone()['id'] if is_postgres() else cur.lastrowid
            cur.execute(f"INSERT INTO question_bloom_tags (question_id, category, confidence, reviewed_by) VALUES ({p}, {p}, {p}, {p})",
                        (question_id, question['category'], 'Unverified', session.get('user_id')))
        cur.execute(f"INSERT INTO generated_exam_owners (user_id, exam_id, status) VALUES ({p}, {p}, 'active')",
                    (session.get('user_id'), exam_id))
        conn.commit()
        return jsonify({'success': True, 'exam_id': exam_id, 'title': title, 'question_count': total,
                        'duration_minutes': duration, 'bloom_counts': bloom_counts,
                        'exam_url': url_for('exam_page', exam_id=exam_id), 'system_url': url_for('eduvault_system')})
    except Exception:
        conn.rollback()
        app.logger.exception('Could not save the generated practice exam')
        return jsonify({'error': 'The questions were generated but could not be saved. Please try again.'}), 500
    finally:
        cur.close()
        conn.close()


@app.route('/api/exam-generator/mine')
@login_required
def list_my_generated_exams():
    conn = get_db_connection()
    cur = conn.cursor()
    p = get_param_style()
    cur.execute(f"""SELECT e.id, e.title, e.subject, e.grade, e.duration_minutes, e.total_marks, o.created_at,
                    (SELECT COUNT(*) FROM questions q WHERE q.exam_id = e.id) AS question_count,
                    (SELECT COUNT(*) FROM user_results r WHERE r.exam_id = e.id AND r.user_id = {p}) AS attempts
                 FROM generated_exam_owners o JOIN exams e ON e.id = o.exam_id
                 WHERE o.user_id = {p} AND o.status = 'active' ORDER BY o.created_at DESC, e.id DESC""",
                (session.get('user_id'), session.get('user_id')))
    rows = [dict(row) for row in cur.fetchall()]
    cur.close()
    conn.close()
    return jsonify(rows)


@app.route('/api/exam-generator/mine/<int:exam_id>', methods=['DELETE'])
@login_required
def delete_my_generated_exam(exam_id):
    conn = get_db_connection()
    cur = conn.cursor()
    p = get_param_style()
    try:
        cur.execute(f"SELECT id FROM generated_exam_owners WHERE user_id = {p} AND exam_id = {p} AND status = 'active'",
                    (session.get('user_id'), exam_id))
        if not cur.fetchone():
            return jsonify({'error': 'This generated exam is not in your saved exams.'}), 404
        cur.execute(f"SELECT COUNT(*) AS total FROM user_results WHERE exam_id = {p}", (exam_id,))
        row = cur.fetchone()
        attempted = int(row['total'] if hasattr(row, 'keys') else row[0]) > 0
        if attempted:
            cur.execute(f"UPDATE generated_exam_owners SET status = 'deleted' WHERE user_id = {p} AND exam_id = {p}",
                        (session.get('user_id'), exam_id))
        else:
            cur.execute(f"DELETE FROM exams WHERE id = {p}", (exam_id,))
        conn.commit()
        return jsonify({'success': True, 'history_preserved': attempted})
    except Exception:
        conn.rollback()
        app.logger.exception('Could not delete generated exam')
        return jsonify({'error': 'Could not delete this generated exam.'}), 500
    finally:
        cur.close()
        conn.close()


@app.route('/api/exam-generator/mine/<int:exam_id>/questions')
@login_required
def list_my_generated_exam_questions(exam_id):
    conn = get_db_connection()
    cur = conn.cursor()
    p = get_param_style()
    cur.execute(f"SELECT 1 FROM generated_exam_owners WHERE user_id = {p} AND exam_id = {p} AND status = 'active'",
                (session.get('user_id'), exam_id))
    if not cur.fetchone():
        cur.close(); conn.close()
        return jsonify({'error': 'This exam is not in your saved exams.'}), 404
    cur.execute(f"""
        SELECT q.id, q.question_number, q.question_text, bt.category,
               u.unit_number, u.title AS unit_title,
               s.section_number, s.title AS section_title
        FROM questions q
        LEFT JOIN question_bloom_tags bt ON bt.question_id = q.id
        LEFT JOIN curriculum_units u ON u.id = q.curriculum_unit_id
        LEFT JOIN curriculum_sections s ON s.id = q.curriculum_section_id
        WHERE q.exam_id = {p}
        ORDER BY q.question_number, q.id
    """, (exam_id,))
    rows = [dict(row) for row in cur.fetchall()]
    cur.close(); conn.close()
    return jsonify(rows)


@app.route('/api/exam-generator/mine/<int:exam_id>/questions/<int:question_id>', methods=['DELETE'])
@login_required
def delete_my_generated_exam_question(exam_id, question_id):
    conn = get_db_connection()
    cur = conn.cursor()
    p = get_param_style()
    try:
        cur.execute(f"SELECT id FROM generated_exam_owners WHERE user_id = {p} AND exam_id = {p} AND status = 'active'",
                    (session.get('user_id'), exam_id))
        if not cur.fetchone():
            return jsonify({'error': 'This exam is not in your saved exams.'}), 404
        cur.execute(f"SELECT 1 FROM user_results WHERE exam_id = {p} LIMIT 1", (exam_id,))
        if cur.fetchone():
            return jsonify({'error': 'This exam has already been taken. Its questions are locked to preserve your results.'}), 409
        cur.execute(f"SELECT 1 FROM questions WHERE id = {p} AND exam_id = {p}", (question_id, exam_id))
        if not cur.fetchone():
            return jsonify({'error': 'Question not found in this exam.'}), 404
        cur.execute(f"DELETE FROM questions WHERE id = {p} AND exam_id = {p}", (question_id, exam_id))
        cur.execute(f"SELECT COUNT(*) AS total FROM questions WHERE exam_id = {p}", (exam_id,))
        row = cur.fetchone()
        remaining = int(row['total'] if hasattr(row, 'keys') else row[0])
        cur.execute(f"UPDATE exams SET total_marks = {p} WHERE id = {p}", (remaining, exam_id))
        conn.commit()
        return jsonify({'success': True, 'remaining_questions': remaining})
    except Exception:
        conn.rollback()
        app.logger.exception('Could not remove generated question')
        return jsonify({'error': 'Could not remove this question.'}), 500
    finally:
        cur.close()
        conn.close()


@app.route('/api/learning/videos')
@login_required
def list_learning_videos():
    conn = get_db_connection()
    cur = conn.cursor()
    p = get_param_style()
    filters = ["status = 'published'"]
    params = []
    for key, col in [('grade', 'grade'), ('subject', 'subject')]:
        value = request.args.get(key)
        if value:
            try:
                value = int(value) if key == 'grade' else value.strip()
                filters.append(f"{col} = {p}")
                params.append(value)
            except ValueError:
                pass
    cur.execute("SELECT id, title, description, grade, subject, unit_title, chapter_title, topic_title, video_url, duration, language, source_name FROM tutorial_videos WHERE " + " AND ".join(filters) + " ORDER BY grade, subject, title", tuple(params))
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return jsonify(rows)


@app.route('/api/learning/videos', methods=['POST'])
@admin_required
def create_learning_video():
    data = request.get_json(silent=True) or {}
    required = ['title', 'grade', 'subject', 'video_url']
    if any(not str(data.get(k, '')).strip() for k in required):
        return jsonify({"error": "Title, grade, subject, and video URL are required."}), 400
    url = str(data['video_url']).strip()
    if not re.match(r'^https://', url, re.I):
        return jsonify({"error": "Use a valid HTTPS video URL."}), 400
    try:
        grade = int(data['grade'])
        if grade not in (9, 10, 11, 12):
            raise ValueError()
    except ValueError:
        return jsonify({"error": "Grade must be 9, 10, 11, or 12."}), 400
    conn = get_db_connection()
    cur = conn.cursor()
    p = get_param_style()
    try:
        fields = ['title','description','grade','subject','unit_title','chapter_title','topic_title','video_url','duration','language','source_name','status','created_by']
        values = [str(data.get(k, '') or '').strip() for k in fields]
        values[2] = grade
        values[11] = 'published' if data.get('publish') else 'draft'
        values[12] = session.get('user_id')
        sql = f"INSERT INTO tutorial_videos ({', '.join(fields)}) VALUES ({', '.join([p] * len(fields))})"
        if is_postgres():
            sql += " RETURNING id"
        cur.execute(sql, tuple(values))
        item_id = cur.fetchone()['id'] if is_postgres() else cur.lastrowid
        conn.commit()
        return jsonify({"success": True, "id": item_id}), 201
    except Exception:
        conn.rollback()
        app.logger.exception("Video creation failed")
        return jsonify({"error": "Could not save the video."}), 500
    finally:
        cur.close()
        conn.close()


@app.route('/api/learning/notes')
@portal_or_unified_required
def list_learning_notes():
    conn = get_db_connection()
    cur = conn.cursor()
    p = get_param_style()
    filters = ["status = 'published'"]
    params = []
    for key, col in [('grade', 'grade'), ('subject', 'subject')]:
        value = request.args.get(key)
        if value:
            try:
                value = int(value) if key == 'grade' else value.strip()
                filters.append(f"{col} = {p}")
                params.append(value)
            except ValueError:
                pass
    cur.execute("SELECT id, title, grade, subject, unit_title, chapter_title, topic_title, summary, content, source_attribution FROM revision_notes WHERE " + " AND ".join(filters) + " ORDER BY grade, subject, title", tuple(params))
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return jsonify(rows)


@app.route('/api/learning/notes', methods=['POST'])
@admin_required
def create_learning_note():
    data = request.get_json(silent=True) or {}
    if not str(data.get('title', '')).strip() or not str(data.get('content', '')).strip():
        return jsonify({"error": "Title and note content are required."}), 400
    try:
        grade = int(data.get('grade'))
        if grade not in (9, 10, 11, 12):
            raise ValueError()
    except (TypeError, ValueError):
        return jsonify({"error": "Grade must be 9, 10, 11, or 12."}), 400
    conn = get_db_connection()
    cur = conn.cursor()
    p = get_param_style()
    try:
        fields = ['title','grade','subject','unit_title','chapter_title','topic_title','summary','content','source_attribution','status','created_by']
        values = [str(data.get(k, '') or '').strip() for k in fields]
        values[1] = grade
        values[9] = 'published' if data.get('publish') else 'draft'
        values[10] = session.get('user_id')
        sql = f"INSERT INTO revision_notes ({', '.join(fields)}) VALUES ({', '.join([p] * len(fields))})"
        if is_postgres():
            sql += " RETURNING id"
        cur.execute(sql, tuple(values))
        item_id = cur.fetchone()['id'] if is_postgres() else cur.lastrowid
        conn.commit()
        return jsonify({"success": True, "id": item_id}), 201
    except Exception:
        conn.rollback()
        app.logger.exception("Note creation failed")
        return jsonify({"error": "Could not save the note."}), 500
    finally:
        cur.close()
        conn.close()


@app.route('/api/learning/analytics')
@login_required
def learning_analytics_data():
    conn = get_db_connection()
    cur = conn.cursor()
    p = get_param_style()
    filters = [f"r.user_id = {p}"]
    filter_values = [session.get('user_id')]
    for key, column in (("subject", "e.subject"), ("grade", "e.grade"),
                        ("examination_type", "e.examination_type"), ("mode", "r.examination_mode")):
        value = request.args.get(key)
        if value:
            if key == 'grade':
                try:
                    value = int(value)
                except ValueError:
                    return jsonify({"error": "Grade must be a number."}), 400
            filters.append(f"{column} = {p}")
            filter_values.append(value)
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()
    if date_from:
        filters.append(f"DATE(r.date_attempted) >= {p}")
        filter_values.append(date_from)
    if date_to:
        filters.append(f"DATE(r.date_attempted) <= {p}")
        filter_values.append(date_to)
    where_sql = ' AND '.join(filters)
    cur.execute(f"""
        SELECT r.id, r.score, r.total_questions, r.accuracy, r.date_attempted,
               CASE WHEN EXISTS (SELECT 1 FROM user_answer_details ad WHERE ad.result_id = r.id)
                    THEN (SELECT COUNT(*) FROM user_answer_details ad WHERE ad.result_id = r.id AND ad.is_correct = 1) END AS correct_answers,
               CASE WHEN EXISTS (SELECT 1 FROM user_answer_details ad WHERE ad.result_id = r.id)
                    THEN (SELECT COUNT(*) FROM user_answer_details ad WHERE ad.result_id = r.id AND COALESCE(ad.submitted_answer, '') <> '' AND ad.is_correct = 0) END AS incorrect_answers,
               CASE WHEN EXISTS (SELECT 1 FROM user_answer_details ad WHERE ad.result_id = r.id)
                    THEN (SELECT COUNT(*) FROM user_answer_details ad WHERE ad.result_id = r.id AND COALESCE(ad.submitted_answer, '') = '') END AS unanswered_questions,
               r.examination_mode, e.examination_type, e.title AS exam_title, e.subject, e.grade, e.category
        FROM user_results r JOIN exams e ON e.id = r.exam_id
        WHERE {where_sql}
        ORDER BY r.date_attempted DESC, r.id DESC
    """, tuple(filter_values))
    attempts = [dict(r) for r in cur.fetchall()]
    cur.execute(f"""
        SELECT bt.category, COUNT(*) AS total,
               SUM(CASE WHEN ad.is_correct = 1 THEN 1 ELSE 0 END) AS correct
        FROM user_answer_details ad
        JOIN question_bloom_tags bt ON bt.question_id = ad.question_id
        JOIN user_results r ON r.id = ad.result_id
        JOIN exams e ON e.id = r.exam_id
        WHERE {where_sql}
        GROUP BY bt.category ORDER BY bt.category
    """, tuple(filter_values))
    category_rows = [dict(r) for r in cur.fetchall()]
    cur.execute(f"""
        SELECT e.grade, e.subject, u.unit_number, u.title AS unit_title,
               s.section_number, s.title AS section_title, COUNT(DISTINCT q.id) AS total,
               COUNT(DISTINCT CASE WHEN ad.is_correct = 1 THEN q.id END) AS correct
        FROM user_answer_details ad
        JOIN user_results r ON r.id = ad.result_id
        JOIN questions q ON q.id = ad.question_id
        JOIN exams e ON e.id = r.exam_id
        LEFT JOIN curriculum_units u ON u.id = q.curriculum_unit_id
        LEFT JOIN curriculum_sections s ON s.id = q.curriculum_section_id
        WHERE {where_sql}
        GROUP BY e.grade, e.subject, u.unit_number, u.title, s.section_number, s.title
        ORDER BY e.grade, e.subject, u.unit_number, s.section_number
    """, tuple(filter_values))
    curriculum_rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    categories = []
    for row in category_rows:
        total = int(row['total'] or 0)
        correct = int(row['correct'] or 0)
        categories.append({"category": row['category'], "total": total, "correct": correct,
                           "accuracy": round(correct / total * 100, 1) if total else None})
    curriculum_performance = []
    for row in curriculum_rows:
        total = int(row['total'] or 0)
        correct = int(row['correct'] or 0)
        curriculum_performance.append({
            'grade': row['grade'], 'subject': row['subject'], 'unit_number': row['unit_number'],
            'unit_title': row['unit_title'] or 'Unmapped unit',
            'section_number': row['section_number'], 'section_title': row['section_title'] or 'Unclassified section',
            'total': total, 'correct': correct,
            'accuracy': round(correct / total * 100, 1) if total else None
        })
    by_subject = {}
    category_totals = {'entrance': 0, 'core_subjects': 0, 'practical_questions': 0, 'chapter_practice': 0}
    mode_totals = {'practice': 0, 'exam': 0}
    for attempt in attempts:
        subject = str(attempt.get('subject') or 'Other')
        bucket = by_subject.setdefault(subject, {'subject': subject, 'attempts': 0, 'accuracies': [], 'highest': 0.0, 'lowest': 100.0})
        accuracy = float(attempt.get('accuracy') or 0)
        bucket['attempts'] += 1
        bucket['accuracies'].append(accuracy)
        bucket['highest'] = max(bucket['highest'], accuracy)
        bucket['lowest'] = min(bucket['lowest'], accuracy)
        kind = attempt.get('examination_type') or ''
        destination = examination_destination(kind) if kind in EXAMINATION_TYPES else 'core_subjects'
        if destination == 'entrance_exam_portal': category_totals['entrance'] += 1
        elif destination == 'practical_questions': category_totals['practical_questions'] += 1
        elif destination == 'chapter_practice': category_totals['chapter_practice'] += 1
        else: category_totals['core_subjects'] += 1
        mode = attempt.get('examination_mode') or 'exam'
        if mode in mode_totals: mode_totals[mode] += 1
    subject_performance = [{**item, 'average_accuracy': round(sum(item.pop('accuracies')) / item['attempts'], 1),
                            'highest': round(item['highest'], 1), 'lowest': round(item['lowest'], 1)}
                           for item in by_subject.values()]
    subject_performance.sort(key=lambda item: (-item['average_accuracy'], item['subject'].casefold()))
    weak = [area for area in categories + curriculum_performance
            if area['total'] >= 2 and area['accuracy'] is not None and area['accuracy'] < 65]
    strong = [area for area in categories + curriculum_performance
              if area['total'] >= 2 and area['accuracy'] is not None and area['accuracy'] >= 85]
    weak_area_labels = []
    for area in weak[:5]:
        if 'category' in area:
            weak_area_labels.append(f"Bloom · {area['category']}")
        else:
            weak_area_labels.append(f"Grade {area['grade']} {area['subject']} · Unit {area['unit_number']}: {area['unit_title']} · Section {area['section_number']}: {area['section_title']}")
    strong_area_labels = []
    for area in strong[:3]:
        if 'category' in area:
            strong_area_labels.append(f"Bloom · {area['category']}")
        else:
            strong_area_labels.append(f"Grade {area['grade']} {area['subject']} · Unit {area['unit_number']}: {area['unit_title']} · Section {area['section_number']}: {area['section_title']}")
    known_areas = weak_area_labels + strong_area_labels

    recommendations = []
    try:
        gemini = get_gemini_client()
    except Exception:
        app.logger.info('Gemini analytics client unavailable.', exc_info=True)
        gemini = None
    if gemini and known_areas:
        try:
            performance_context = {
                'weak_areas': weak[:5], 'strong_areas': strong[:5],
                'attempts': len(attempts)
            }
            prompt = f"""Create up to 5 short, specific study recommendations for a Grade 9–12 student using only the performance data and area labels supplied below. Prioritize weak areas, then suggest a way to maintain strong areas. Do not invent units, topics, scores, or study resources. Return JSON only as {{"recommendations":[{{"area":"one exact supplied area label","title":"...","reason":"...","action":"..."}}]}}.
Performance data: {json.dumps(performance_context, ensure_ascii=False)}"""
            response = gemini.models.generate_content(
                model='gemini-3.8-flash', contents=prompt,
                config=types.GenerateContentConfig(response_mime_type='application/json', max_output_tokens=2048, temperature=0.3)
            )
            parsed = json.loads(response.text or '{}')
            allowed_areas = set(known_areas)
            for item in (parsed.get('recommendations') or [])[:5]:
                if isinstance(item, dict) and item.get('area') in allowed_areas:
                    recommendations.append({key: str(item.get(key) or '')[:400] for key in ('area', 'title', 'reason', 'action')})
        except Exception:
            app.logger.info('Gemini analytics recommendations unavailable; using score-based guidance.', exc_info=True)
    if not recommendations:
        for area in weak[:5]:
            label = (f"Bloom · {area['category']}" if 'category' in area else
                     f"Grade {area['grade']} {area['subject']} · Unit {area['unit_number']}: {area['unit_title']} · Section {area['section_number']}: {area['section_title']}")
            recommendations.append({'area': label, 'title': f"Strengthen {label}",
                                    'reason': f"You answered {area['correct']} of {area['total']} correctly ({area['accuracy']}%).",
                                    'action': 'Generate a short practice exam for this area, then review each explanation.'})
        if not recommendations and not attempts:
            recommendations.append({'area': '', 'title': 'Start your learning record',
                                    'reason': 'No completed exams are available for analysis yet.',
                                    'action': 'Generate a curriculum practice exam and complete it.'})
        elif not recommendations:
            recommendations.append({'area': '', 'title': 'Keep your progress steady',
                                    'reason': 'Your tracked areas are developing well or need more attempts for a reliable comparison.',
                                    'action': 'Complete another mixed-topic exam to keep building your learning record.'})
    return jsonify({'attempts': attempts, 'bloom_performance': categories,
                    'curriculum_performance': curriculum_performance, 'weak_areas': weak,
                    'strong_areas': strong, 'recommendations': recommendations,
                    'subject_performance': subject_performance,
                    'category_attempts': category_totals, 'mode_attempts': mode_totals})


@app.route('/api/admin/learning/content', methods=['GET'])
@admin_required
def admin_learning_content():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, title, grade, subject, status FROM tutorial_videos ORDER BY created_at DESC")
    videos = [dict(r) for r in cur.fetchall()]
    cur.execute("SELECT id, title, grade, subject, status FROM revision_notes ORDER BY created_at DESC")
    notes = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return jsonify({"videos": videos, "notes": notes})


@app.route('/api/admin/exam-analytics', methods=['GET'])
@admin_required
def admin_exam_analytics():
    """Return aggregate examination metrics from published exams and recorded results."""
    conn = get_db_connection()
    cur = conn.cursor()
    p = get_param_style()
    filters = []
    values = []
    exam_filters = []
    exam_values = []
    for key, column in (("examination_type", "e.examination_type"),
                        ("subject", "e.subject"), ("grade", "e.grade"),
                        ("academic_year", "e.academic_year")):
        value = request.args.get(key, '').strip()
        if not value:
            continue
        if key == 'grade':
            try:
                value = int(value)
            except ValueError:
                cur.close()
                conn.close()
                return jsonify({"error": "Grade must be a number."}), 400
        filters.append(f"{column} = {p}")
        values.append(value)
        exam_filters.append(f"{column} = {p}")
        exam_values.append(value)
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()
    if date_from:
        filters.append(f"DATE(r.date_attempted) >= {p}")
        values.append(date_from)
    if date_to:
        filters.append(f"DATE(r.date_attempted) <= {p}")
        values.append(date_to)
    result_filter = (' WHERE ' + ' AND '.join(filters)) if filters else ''
    try:
        exam_filter_sql = (' WHERE ' + ' AND '.join(exam_filters)) if exam_filters else ''
        cur.execute(f"SELECT COUNT(*) AS total_exams FROM exams e{exam_filter_sql}", tuple(exam_values))
        total_exams = int(cur.fetchone()['total_exams'])
        cur.execute(f"SELECT COUNT(*) AS total_questions FROM questions q JOIN exams e ON e.id = q.exam_id{exam_filter_sql}", tuple(exam_values))
        total_questions = int(cur.fetchone()['total_questions'])
        cur.execute(f"""SELECT e.examination_type, COUNT(DISTINCT e.id) AS exam_count
                       FROM exams e{exam_filter_sql} GROUP BY e.examination_type""", tuple(exam_values))
        type_counts = {str(row['examination_type'] or 'other_core_subject'): int(row['exam_count'])
                       for row in cur.fetchall()}
        cur.execute(f"""SELECT COUNT(*) AS attempts, AVG(r.accuracy) AS average_score
                         FROM user_results r JOIN exams e ON e.id = r.exam_id{result_filter}""", tuple(values))
        summary_row = cur.fetchone()
        cur.execute(f"""SELECT e.subject, COUNT(*) AS attempts, AVG(r.accuracy) AS average_accuracy
                         FROM user_results r JOIN exams e ON e.id = r.exam_id{result_filter}
                         GROUP BY e.subject ORDER BY average_accuracy ASC, attempts DESC LIMIT 8""", tuple(values))
        difficult_subjects = [dict(row) for row in cur.fetchall()]
        cur.execute(f"""SELECT q.id, SUBSTR(q.question_text, 1, 180) AS question_text,
                         COUNT(*) AS attempts,
                         100.0 * SUM(CASE WHEN ad.is_correct = 1 THEN 1 ELSE 0 END) / COUNT(*) AS accuracy,
                         e.subject
                         FROM user_answer_details ad
                         JOIN user_results r ON r.id = ad.result_id
                         JOIN exams e ON e.id = r.exam_id
                         JOIN questions q ON q.id = ad.question_id
                         {result_filter} {('AND' if result_filter else 'WHERE')} ad.submitted_answer IS NOT NULL
                         GROUP BY q.id, q.question_text, e.subject
                         ORDER BY accuracy ASC, attempts DESC LIMIT 10""", tuple(values))
        difficult_questions = [dict(row) for row in cur.fetchall()]
        cur.execute(f"""SELECT u.id AS user_id, COALESCE(u.first_name || ' ' || u.last_name, u.username) AS student,
                         COUNT(*) AS attempts, AVG(r.accuracy) AS average_accuracy
                         FROM user_results r JOIN exams e ON e.id = r.exam_id
                         JOIN users u ON u.id = r.user_id{result_filter}
                         GROUP BY u.id, u.first_name, u.last_name, u.username
                         ORDER BY average_accuracy DESC, attempts DESC LIMIT 10""", tuple(values))
        rankings = [dict(row) for row in cur.fetchall()]
        return jsonify({
            'total_exams': total_exams, 'total_questions': total_questions,
            'exam_type_counts': type_counts,
            'student_attempts': int(summary_row['attempts'] or 0),
            'average_score': round(float(summary_row['average_score'] or 0), 1),
            'most_difficult_subjects': difficult_subjects,
            'most_difficult_questions': difficult_questions,
            'student_rankings': rankings,
        })
    except Exception:
        app.logger.exception('Could not load admin examination analytics')
        return jsonify({'error': 'Could not load examination analytics.'}), 500
    finally:
        cur.close()
        conn.close()



@app.route('/admin/bloom-taxonomy')
@admin_required
def bloom_taxonomy_admin_page():
    return render_template('bloom_admin.html', username=session.get('username'), role=session.get('role', 'admin'))


@app.route('/api/admin/questions/search')
@admin_required
def search_questions_for_bloom_review():
    query = (request.args.get('q') or '').strip()
    if len(query) < 2:
        return jsonify({"items": []})
    conn = get_db_connection()
    cur = conn.cursor()
    p = get_param_style()
    like = f"%{query}%"
    cur.execute(f"""
        SELECT q.id, q.question_text, e.subject, e.grade, e.title AS exam_title
        FROM questions q JOIN exams e ON e.id = q.exam_id
        WHERE q.question_text LIKE {p}
        ORDER BY q.id DESC LIMIT 40
    """, (like,))
    rows = [dict(r) for r in cur.fetchall()]
    for row in rows:
        cur.execute(f"SELECT category, confidence FROM question_bloom_tags WHERE question_id = {p} ORDER BY category", (row['id'],))
        row['bloom_tags'] = [dict(t) for t in cur.fetchall()]
    cur.close()
    conn.close()
    return jsonify({"items": rows})


@app.route('/api/learning/videos/<int:video_id>', methods=['PUT', 'DELETE'])
@admin_required
def manage_learning_video(video_id):
    conn = get_db_connection()
    cur = conn.cursor()
    p = get_param_style()
    try:
        if request.method == 'DELETE':
            cur.execute(f"DELETE FROM tutorial_videos WHERE id = {p}", (video_id,))
            if cur.rowcount == 0:
                return jsonify({"error": "Video not found."}), 404
            conn.commit()
            return jsonify({"success": True})
        data = request.get_json(silent=True) or {}
        allowed = {'title','description','grade','subject','unit_title','chapter_title','topic_title','video_url','duration','language','source_name','status'}
        updates = {k: data[k] for k in allowed if k in data}
        if not updates:
            return jsonify({"error": "No editable fields were supplied."}), 400
        if 'status' in updates and updates['status'] not in ('draft','published','archived'):
            return jsonify({"error": "Invalid publication status."}), 400
        if 'video_url' in updates and not re.match(r'^https://', str(updates['video_url']), re.I):
            return jsonify({"error": "Use an HTTPS video URL."}), 400
        if 'grade' in updates:
            updates['grade'] = int(updates['grade'])
            if updates['grade'] not in (9,10,11,12):
                return jsonify({"error": "Grade must be 9, 10, 11, or 12."}), 400
        assignments = ", ".join(f"{key} = {p}" for key in updates)
        cur.execute(f"UPDATE tutorial_videos SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE id = {p}",
                    tuple(updates.values()) + (video_id,))
        if cur.rowcount == 0:
            return jsonify({"error": "Video not found."}), 404
        conn.commit()
        return jsonify({"success": True})
    except (ValueError, TypeError):
        conn.rollback()
        return jsonify({"error": "Invalid video data."}), 400
    except Exception:
        conn.rollback()
        app.logger.exception("Video update failed")
        return jsonify({"error": "Could not update the video."}), 500
    finally:
        cur.close()
        conn.close()


@app.route('/api/learning/notes/<int:note_id>', methods=['PUT', 'DELETE'])
@admin_required
def manage_learning_note(note_id):
    conn = get_db_connection()
    cur = conn.cursor()
    p = get_param_style()
    try:
        if request.method == 'DELETE':
            cur.execute(f"DELETE FROM revision_notes WHERE id = {p}", (note_id,))
            if cur.rowcount == 0:
                return jsonify({"error": "Note not found."}), 404
            conn.commit()
            return jsonify({"success": True})
        data = request.get_json(silent=True) or {}
        allowed = {'title','grade','subject','unit_title','chapter_title','topic_title','summary','content','source_attribution','status'}
        updates = {k: data[k] for k in allowed if k in data}
        if not updates:
            return jsonify({"error": "No editable fields were supplied."}), 400
        if 'status' in updates and updates['status'] not in ('draft','published','archived'):
            return jsonify({"error": "Invalid publication status."}), 400
        if 'grade' in updates:
            updates['grade'] = int(updates['grade'])
            if updates['grade'] not in (9,10,11,12):
                return jsonify({"error": "Grade must be 9, 10, 11, or 12."}), 400
        assignments = ", ".join(f"{key} = {p}" for key in updates)
        cur.execute(f"UPDATE revision_notes SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE id = {p}",
                    tuple(updates.values()) + (note_id,))
        if cur.rowcount == 0:
            return jsonify({"error": "Note not found."}), 404
        conn.commit()
        return jsonify({"success": True})
    except (ValueError, TypeError):
        conn.rollback()
        return jsonify({"error": "Invalid note data."}), 400
    except Exception:
        conn.rollback()
        app.logger.exception("Note update failed")
        return jsonify({"error": "Could not update the note."}), 500
    finally:
        cur.close()
        conn.close()

# Additive schema migration runs on startup; existing tables and student data are retained.
try:
    ensure_learning_upgrade_schema()
except Exception as upgrade_error:
    app.logger.exception("EduVault learning upgrade schema initialization failed: %s", upgrade_error)


if __name__ == '__main__':
    if not os.path.exists('uploads'):
        os.makedirs('uploads')
    debug_mode = os.getenv('FLASK_DEBUG', '0') == '1'
    app.run(debug=debug_mode, threaded=True, port=5000)
