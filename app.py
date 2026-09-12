# app.py - Complete Updated Version with AI Tutor Memory
import os
import json
import time
import re
import sqlite3
import urllib.request
import urllib.error
import tempfile
import uuid
import shutil
from functools import wraps
from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash, send_from_directory
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
MAX_FILE_SIZE = 16 * 1024 * 1024  # 16 MB
SQLITE_BUSY_TIMEOUT_MS = 30_000
ALLOWED_EXTENSIONS = {'pdf', 'json', 'png', 'jpg', 'jpeg', 'gif', 'txt', 'docx', 'mp3', 'wav', 'ogg', 'm4a'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(PROFILE_PHOTO_FOLDER, exist_ok=True)

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
from ranking import calculate_entrance_top_performers, calculate_exam_top_performers, calculate_rankings

try:
    init_db()
except Exception as e:
    def get_curriculum_outline(subject_name, grade_number):
        conn = get_db_connection()
        cursor = conn.cursor()
        param = get_param_style()
        cursor.execute(f"""
            SELECT u.unit_number, u.title AS unit_title,
                   s.section_number, s.title AS section_title,
                   t.topic_title, t.subtopic
            FROM curriculum_units u
            JOIN curriculum_subjects cs ON cs.id = u.subject_id
            JOIN curriculum_grades cg ON cg.id = u.grade_id
            LEFT JOIN curriculum_sections s ON s.unit_id = u.id
            LEFT JOIN curriculum_topics t ON t.section_id = s.id
            WHERE cs.name = {param} AND cg.number = {param}
            ORDER BY u.unit_number, s.section_number, t.topic_title
        """, (subject_name, grade_number))
        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        outline = []
        for row in rows:
            outline.append({
                "unit_number": row["unit_number"],
                "unit_title": row["unit_title"],
                "section_number": row["section_number"],
                "section_title": row["section_title"],
                "topic_title": row["topic_title"],
                "subtopic": row["subtopic"]
            })
        return outline

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
            return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        except Exception as error:
            print(f"DEBUG: PostgreSQL connection failed ({error}); using SQLite.")
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
    return bool(re.fullmatch(r"[a-z0-9](?:[a-z0-9_.-]{1,28}[a-z0-9])?", value or ""))


def unified_account_dict(row):
    account = dict(row)
    account.pop('password_hash', None)
    account['name'] = normalize_person_name(
        f"{account.get('first_name') or ''} {account.get('last_name') or ''}"
    )
    account['code'] = account.get('student_code') or ''
    account['studentCode'] = account.get('student_code') or ''
    account['studentName'] = account['name']
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
    return verified_user_id == user['id'] and (exam_id is None or verified_exam_id == exam_id)


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
    cursor.execute("SELECT student_code FROM users WHERE student_code IS NOT NULL")
    highest = 0
    for row in cursor.fetchall():
        match = re.fullmatch(r"ST(\d+)", str(row['student_code'] or '').upper())
        if match:
            highest = max(highest, int(match.group(1)))
    while True:
        highest += 1
        candidate = f"ST{highest:03d}"
        param = get_param_style()
        cursor.execute(f"SELECT 1 FROM users WHERE student_code = {param}", (candidate,))
        if not cursor.fetchone():
            return candidate


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
               s.section_number, s.title AS section_title,
               t.topic_title, t.subtopic
        FROM curriculum_units u
        JOIN curriculum_subjects cs ON cs.id = u.subject_id
        JOIN curriculum_grades cg ON cg.id = u.grade_id
        LEFT JOIN curriculum_sections s ON s.unit_id = u.id
        LEFT JOIN curriculum_topics t ON t.section_id = s.id
        WHERE cs.name = {param} AND cg.number = {param}
        ORDER BY u.unit_number, s.section_number, t.topic_title
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
        raise ValueError(f"No curriculum JSON found for {subject_name} Grade {grade_number}.")

    uploaded_file = client.files.upload(file=pdf_path)
    try:
        while uploaded_file.state.name == "PROCESSING":
            time.sleep(1.5)
            uploaded_file = client.files.get(name=uploaded_file.name)
        prompt = f"""
Read the complete Ethiopian entrance exam PDF. Return JSON only and extract every question in original order.
Preserve question_number and source_year exactly as printed. Classify each question only against this textbook
curriculum JSON; never invent a unit, section, topic, or subtopic.
Subject: {subject_name}; Grade: {grade_number}
Curriculum: {json.dumps(curriculum, ensure_ascii=False)}
Schema: {{"school_name": null, "department": "{subject_name}", "academic_year": null,
"instructions": null, "questions": [{{"question_number": 1, "source_year": null, "question": "",
"A": "", "B": "", "C": "", "D": "", "correct": "A", "explanation": "",
"passage_text": null, "diagram_instruction": null, "unit_number": null, "unit_title": null,
"section_number": null, "section_title": null, "topic_title": null, "subtopic": null,
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
               s.section_number, s.title as section_title,
               t.topic_title, t.subtopic
        FROM curriculum_units u
        JOIN curriculum_subjects cs ON u.subject_id = cs.id
        JOIN curriculum_grades cg ON u.grade_id = cg.id
        LEFT JOIN curriculum_sections s ON u.id = s.unit_id
        LEFT JOIN curriculum_topics t ON s.id = t.section_id
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
            if row['topic_title']:
                curriculum_context += f"    Topic: {row['topic_title']}"
                if row['subtopic']:
                    curriculum_context += f" - Subtopic: {row['subtopic']}"
                curriculum_context += "\n"

    prompt = f"""
You are an expert Ethiopian curriculum specialist.

Your task is to classify the following exam question into the correct Unit, Section, Topic, and Subtopic of the Ethiopian New Curriculum for {subject_name} Grade {grade_number}.

**Question:**
{question_text}

**Official Curriculum Reference:**
{curriculum_context}

**Instructions:**
1.  Identify the most specific Unit, Section, Topic, and Subtopic from the official curriculum provided above.
2.  You MUST select from the official curriculum items listed. Do NOT invent new units or topics.
3.  Provide a confidence level: "High", "Medium", or "Low".
4.  Explain your reasoning briefly.
5.  Output the result in the following JSON format ONLY:

{{
    "unit_number": "Unit number (e.g., 1)",
    "unit_title": "Title of the unit from curriculum",
    "section_number": "Section number (e.g., 1.2)",
    "section_title": "Title of the section from curriculum",
    "topic_title": "Title of the topic from curriculum",
    "subtopic": "Subtopic from curriculum (if applicable, else null)",
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
            topic_id = None

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

            if section_id:
                cursor.execute(f"""
                    SELECT id FROM curriculum_topics
                    WHERE section_id = {param} AND topic_title = {param}
                """, (section_id, classification.get('topic_title')))
                topic = cursor.fetchone()
                if topic:
                    topic_id = topic['id']

            cursor.close()
            conn.close()

            classification['unit_id'] = unit_id
            classification['section_id'] = section_id
            classification['topic_id'] = topic_id
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
@login_required
def profile_photo(filename):
    if not re.fullmatch(r"[a-f0-9]{32}\.(?:jpg|png|webp)", filename or ''):
        return "Not found", 404
    return send_from_directory(PROFILE_PHOTO_FOLDER, filename)


@app.route('/api/unified/login', methods=['POST'])
def unified_login():
    data = request.get_json(silent=True) or request.form
    username = str(data.get('username') or '').strip().lower()
    password = str(data.get('password') or '')
    conn = get_db_connection()
    cursor = conn.cursor()
    param = get_param_style()
    cursor.execute(f"SELECT * FROM unified_accounts WHERE username = {param}", (username,))
    account = cursor.fetchone()
    cursor.close()
    conn.close()
    if not account or not check_password_hash(account['password_hash'], password):
        return jsonify({"success": False, "error": "Invalid Unified System username or password."}), 401
    if account['account_status'] != 'ACTIVE':
        return jsonify({"success": False, "error": "This Unified System account is not active."}), 403
    session['unified_account_id'] = account['id']
    session['unified_role'] = account['role']
    return jsonify({"success": True, "role": account['role'], "account": unified_account_dict(account)})


@app.route('/api/unified/student-login', methods=['POST'])
def unified_student_login():
    data = request.get_json(silent=True) or request.form
    student_code = str(data.get('student_code') or data.get('code') or '').strip().upper()
    full_name = normalize_person_name(data.get('full_name') or data.get('name') or '')
    if not student_code or not full_name:
        return jsonify({"success": False, "error": "Student code and full name are required."}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    param = get_param_style()
    cursor.execute(
        f"SELECT * FROM unified_accounts WHERE student_code = {param} AND role = 'student'",
        (student_code,)
    )
    account = cursor.fetchone()
    cursor.close()
    conn.close()

    if not account or account['account_status'] != 'ACTIVE':
        return jsonify({"success": False, "error": "Invalid student code or inactive student account."}), 401

    expected_name = normalize_person_name(
        f"{account['first_name']} {account['last_name']}"
    )
    if full_name.casefold() != expected_name.casefold():
        return jsonify({"success": False, "error": "Full name does not match the registered student account."}), 401

    session['unified_account_id'] = account['id']
    session['unified_role'] = account['role']
    return jsonify({"success": True, "role": account['role'], "account": unified_account_dict(account)})


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


def validate_unified_account_payload(data, require_password=False):
    username = str(data.get('username') or '').strip().lower()
    first_name = normalize_person_name(data.get('first_name') or '')
    last_name = normalize_person_name(data.get('last_name') or '')
    password = str(data.get('password') or '')
    if not valid_username(username):
        raise ValueError("Username must be 3-30 lowercase characters.")
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
    cursor.execute("SELECT * FROM unified_accounts WHERE role = 'student' ORDER BY id")
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
        code = str(data.get('student_code') or next_student_code_for_unified()).strip().upper()
        age = int(data.get('age')) if str(data.get('age') or '').strip() else None
    except (ValueError, TypeError) as error:
        return jsonify({"success": False, "error": str(error)}), 400
    conn = get_db_connection()
    cursor = conn.cursor()
    param = get_param_style()
    try:
        cursor.execute(f"""INSERT INTO unified_accounts
            (username, password_hash, role, first_name, last_name, student_code, sex, age, stream)
            VALUES ({param}, {param}, 'student', {param}, {param}, {param}, {param}, {param}, {param})""",
            (username, generate_password_hash(password), first_name, last_name, code,
             str(data.get('sex') or ''), age, str(data.get('stream') or 'Natural Sc.')))
        conn.commit()
        cursor.execute(f"SELECT * FROM unified_accounts WHERE username = {param}", (username,))
        account = cursor.fetchone()
        return jsonify({"success": True, "account": unified_account_dict(account)}), 201
    except Exception as error:
        conn.rollback()
        return jsonify({"success": False, "error": "Username or student code is already registered."}), 409
    finally:
        cursor.close()
        conn.close()


def next_student_code_for_unified():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT student_code FROM unified_accounts WHERE student_code IS NOT NULL")
    highest = 0
    for row in cursor.fetchall():
        match = re.fullmatch(r"ST(\d+)", str(row['student_code'] or '').upper())
        if match:
            highest = max(highest, int(match.group(1)))
    cursor.close()
    conn.close()
    return f"ST{highest + 1:03d}"


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

        if not valid_person_name(first_name) or not valid_person_name(last_name):
            flash("Enter a valid first and last name using 2 to 50 letters.", "error")
            return render_template('signup.html')
        if not valid_username(username):
            flash("Username must be 3-30 characters using lowercase letters, numbers, dots, dashes, or underscores.", "error")
            return render_template('signup.html')
        if len(password) < 8 or not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
            flash("Password must be at least 8 characters and include a letter and a number.", "error")
            return render_template('signup.html')
        conn = get_db_connection()
        cursor = conn.cursor()
        param = get_param_style()
        try:
            cursor.execute(
                f'''INSERT INTO users
                    (username, password_hash, role, first_name, last_name, profile_photo,
                     account_status, is_verified, registered_at)
                    VALUES ({param}, {param}, {param}, {param}, {param}, {param}, {param}, {param}, CURRENT_TIMESTAMP)''',
                (username, generate_password_hash(password), 'student', first_name, last_name,
                 None, 'PENDING_APPROVAL', 0)
            )
            conn.commit()
            flash("Registration submitted. An administrator must approve your account before you can log in.", "success")
            return redirect(url_for('login'))
        except Exception:
            conn.rollback()
            flash("That username is already registered. Choose another username.", "error")
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
@login_required
def resources_hub():
    return render_template('resources.html', username=session.get('username'), role=session.get('role', 'student'))

@app.route('/worksheets')
@login_required
def worksheets_page():
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
    return render_template('exam.html', exam_id=exam_id, exam_access_granted=exam_access_allowed(exam_id), verify_required=request.args.get('verify') == 'required')


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
        SELECT id, first_name, last_name, username, profile_photo,
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

    if not valid_person_name(first_name) or not valid_person_name(last_name):
        return jsonify({"success": False, "error": "Enter a valid first and last name."}), 400
    if not valid_username(username):
        return jsonify({"success": False, "error": "Username must use lowercase letters, numbers, dots, dashes, or underscores."}), 400
    if len(password) < 8 or not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        return jsonify({"success": False, "error": "Password must be at least 8 characters and include a letter and a number."}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    param = get_param_style()
    try:
        cursor.execute(f"SELECT id FROM users WHERE username = {param}", (username,))
        if cursor.fetchone():
            return jsonify({"success": False, "error": "That username is already registered."}), 409

        code = next_student_code(cursor)
        insert_sql = f'''
            INSERT INTO users
                (username, password_hash, role, first_name, last_name, student_code,
                 account_status, is_verified, registered_at, approved_at)
            VALUES ({param}, {param}, {param}, {param}, {param}, {param},
                    {param}, {param}, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        '''
        cursor.execute(insert_sql, (
            username, generate_password_hash(password), 'student', first_name,
            last_name, code, 'ACTIVE', 1
        ))
        conn.commit()
        return jsonify({
            "success": True,
            "message": "Student added and activated successfully.",
            "student_code": code,
            "username": username,
            "full_name": normalize_person_name(f"{first_name} {last_name}")
        }), 201
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
        cursor.execute(f"SELECT id, role, account_status, student_code FROM users WHERE id = {param}", (user_id,))
        student = cursor.fetchone()
        if not student or student['role'] != 'student':
            return jsonify({"success": False, "error": "Student registration not found."}), 404
        if student['account_status'] == 'ACTIVE' and student['student_code']:
            return jsonify({"success": True, "student_code": student['student_code'], "message": "Student is already approved."})
        if student['account_status'] != 'PENDING_APPROVAL':
            return jsonify({"success": False, "error": "Only pending registrations can be approved."}), 409
        code = next_student_code(cursor)
        cursor.execute(f"""
            UPDATE users
            SET account_status = {param}, student_code = {param}, is_verified = {param}, approved_at = CURRENT_TIMESTAMP
            WHERE id = {param} AND role = 'student' AND account_status = 'PENDING_APPROVAL'
        """, ('ACTIVE', code, 1, user_id))
        if cursor.rowcount != 1:
            conn.rollback()
            return jsonify({"success": False, "error": "Registration changed before approval. Refresh and try again."}), 409
        conn.commit()
        return jsonify({"success": True, "student_code": code, "message": "Student approved and code generated."})
    except Exception as error:
        conn.rollback()
        return jsonify({"success": False, "error": str(error)}), 500
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
    cursor.execute('''
        SELECT e.*, r.file_url, r.pdf_url 
        FROM exams e
        LEFT JOIN resources r ON e.resource_id = r.id
        ORDER BY e.id DESC
    ''')
    exams = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify([dict(exam) for exam in exams])

@app.route('/api/exams/<int:exam_id>/questions', methods=['GET'])
@login_required
@exam_access_required
def get_questions(exam_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    param = get_param_style()
    cursor.execute(f'''
        SELECT q.*, 
               u.unit_number, u.title as unit_title,
               s.section_number, s.title as section_title,
               t.topic_title, t.subtopic
        FROM questions q
        LEFT JOIN curriculum_units u ON q.curriculum_unit_id = u.id
        LEFT JOIN curriculum_sections s ON q.curriculum_section_id = s.id
        LEFT JOIN curriculum_topics t ON q.curriculum_topic_id = t.id
        WHERE q.exam_id = {param}
        ORDER BY q.id ASC
    ''', (exam_id,))
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
        return jsonify(dict(question))
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
        LEFT JOIN curriculum_topics t ON s.id = t.section_id
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
               t.id as topic_id, t.topic_title, t.subtopic,
               COUNT(DISTINCT q.id) as question_count
        FROM curriculum_units u
        JOIN curriculum_subjects cs ON u.subject_id = cs.id
        JOIN curriculum_grades g ON u.grade_id = g.id
        LEFT JOIN curriculum_sections s ON u.id = s.unit_id
        LEFT JOIN curriculum_topics t ON s.id = t.section_id
        LEFT JOIN questions q ON q.curriculum_topic_id = t.id
        WHERE cs.name = {param} AND g.number = {param}
        GROUP BY u.id, u.unit_number, u.title, s.id, s.section_number, s.title, t.id, t.topic_title, t.subtopic
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
                    "topics": []
                }
            if row['topic_id']:
                result[unit_key]["sections"][section_key]["topics"].append({
                    "id": row['topic_id'],
                    "topic_title": row['topic_title'],
                    "subtopic": row['subtopic'],
                    "question_count": row['question_count'] or 0
                })
    
    return jsonify(list(result.values()))

@app.route('/api/curriculum/unit/<int:unit_id>/questions', methods=['GET'])
@login_required
def get_unit_questions(unit_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    param = get_param_style()
    cursor.execute(f'''
        SELECT q.*, e.title as exam_title
        FROM questions q
        JOIN exams e ON q.exam_id = e.id
        WHERE q.curriculum_unit_id = {param}
        ORDER BY q.id
    ''', (unit_id,))
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
    cursor.execute(f'''
        SELECT q.*, e.title as exam_title
        FROM questions q
        JOIN exams e ON q.exam_id = e.id
        WHERE q.curriculum_section_id = {param}
        ORDER BY q.id
    ''', (section_id,))
    questions = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify([dict(q) for q in questions])

@app.route('/api/curriculum/topic/<int:topic_id>/questions', methods=['GET'])
@login_required
def get_topic_questions(topic_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    param = get_param_style()
    cursor.execute(f'''
        SELECT q.*, e.title as exam_title
        FROM questions q
        JOIN exams e ON q.exam_id = e.id
        WHERE q.curriculum_topic_id = {param}
        ORDER BY q.id
    ''', (topic_id,))
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
    cursor.execute(f'''
        SELECT q.*, e.title as exam_title
        FROM questions q
        JOIN exams e ON q.exam_id = e.id
        WHERE q.chapter_id = {param}
        ORDER BY q.id ASC
    ''', (chapter_id,))
    questions = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify([dict(q) for q in questions])

# ============================================
# RESULT API
# ============================================

@app.route('/api/rankings', methods=['GET'])
@login_required
def get_rankings():
    """Return platform rankings and the highest performer for each exam."""
    conn = get_db_connection()
    cursor = conn.cursor()
    param = get_param_style()
    exam_id = request.args.get('exam_id')
    filter_sql = ''
    values = []
    if exam_id:
        try:
            values.append(int(exam_id))
            filter_sql = f' AND r.exam_id = {param}'
        except ValueError:
            return jsonify({"error": "Invalid exam_id."}), 400
    cursor.execute(f'''
         SELECT r.id, r.user_id, r.exam_id, u.username, r.score, r.total_questions,
             r.accuracy, r.date_attempted, e.title AS exam_title, e.subject,
               CASE WHEN LOWER(e.resource_type) LIKE '%entrance%' OR LOWER(e.category) LIKE '%entrance%'
                    THEN 'entrance' ELSE 'mock' END AS exam_type
        FROM user_results r
        JOIN users u ON u.id = r.user_id
        JOIN exams e ON e.id = r.exam_id
        WHERE u.role = 'student'{filter_sql}
        ORDER BY r.date_attempted ASC, r.id ASC
    ''', values)
    rows = [dict(row) for row in cursor.fetchall()]
    cursor.close()
    conn.close()
    response = calculate_rankings(rows, current_user_id=session['user_id'])
    response['top_performers_by_exam'] = calculate_exam_top_performers(rows)
    response['entrance_top_performers'] = calculate_entrance_top_performers(rows)
    return jsonify(response)

@app.route('/api/results/submit', methods=['POST'])
@login_required
@exam_access_required
def submit_exam_results():
    data = request.get_json(silent=True) or {}
    conn = get_db_connection()
    cursor = conn.cursor()
    param = get_param_style()

    try:
        exam_id = int(data['exam_id'])
        submitted_answers = data.get('answers') or {}
        time_used = max(0, int(data.get('time_used', 0)))
    except (TypeError, ValueError):
        cursor.close()
        conn.close()
        return jsonify({"success": False, "error": "Invalid exam submission."}), 400

    cursor.execute(f'SELECT id FROM exams WHERE id = {param}', (exam_id,))
    if not cursor.fetchone():
        cursor.close()
        conn.close()
        return jsonify({"success": False, "error": "Exam not found."}), 404

    cursor.execute(f'''
        SELECT id, correct_answer
        FROM questions
        WHERE exam_id = {param}
        ORDER BY id ASC
    ''', (exam_id,))
    question_rows = cursor.fetchall()
    if not question_rows:
        cursor.close()
        conn.close()
        return jsonify({"success": False, "error": "Exam has no questions."}), 400

    score = sum(
        1 for question in question_rows
        if str(submitted_answers.get(str(question['id']), '')).upper() == str(question['correct_answer']).upper()
    )
    total = len(question_rows)
    accuracy = round(score / total * 100, 2)
    
    rec_prompt = f"The student scored {score}/{total} ({accuracy}% accuracy) in an exam. Provide a brief, supportive, 2-sentence study plan."
    try:
        response = client.models.generate_content(model="gemini-3.5-flash", contents=rec_prompt)
        recommendation = response.text
    except Exception:
        recommendation = "Focus on weak chapters and review explanations for incorrect attempts."

    sql = f'''
        INSERT INTO user_results (user_id, exam_id, score, total_questions, time_used_seconds, accuracy, date_attempted, ai_recommendation)
        VALUES ({param}, {param}, {param}, {param}, {param}, {param}, {param}, {param})
    '''
    if is_postgres():
        sql += " RETURNING id"
        cursor.execute(sql, (session['user_id'], exam_id, score, total, time_used, accuracy, time.strftime("%Y-%m-%d %H:%M"), recommendation))
        result_id = cursor.fetchone()['id']
    else:
        cursor.execute(sql, (session['user_id'], exam_id, score, total, time_used, accuracy, time.strftime("%Y-%m-%d %H:%M"), recommendation))
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
@login_required
def get_resources():
    conn = get_db_connection()
    cursor = conn.cursor()
    param = get_param_style()
    cursor.execute(f'''
        SELECT id, title, resource_type, subject, grade, file_url, pdf_url, description
        FROM resources
        WHERE status = {param}
        ORDER BY grade, subject, resource_type
    ''', ('published',))
    resources = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify([dict(r) for r in resources])

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
# SMART UPLOAD ENGINE WITH CLASSIFICATION
# ============================================

@app.route('/api/upload', methods=['POST'])
@admin_required
def upload_engine():
    title = request.form.get('title', 'Untitled Resource').strip()
    resource_type = request.form.get('resource_type', 'Exam').strip()
    category = request.form.get('category', 'General').strip()
    subject = request.form.get('subject', 'Mathematics').strip()
    grade = int(request.form.get('grade', 12))
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

    try:
        if filename.endswith('.json'):
            with open(filepath, 'r', encoding='utf-8') as f:
                ai_data = json.load(f)
        else:
            ai_data = parse_pdf_with_ai(filepath, subject, grade)

        if not ai_data or not ai_data.get('questions'):
            return jsonify({"success": False, "error": "No questions could be extracted from the file."}), 400

        questions = ai_data.get('questions', [])
        print(f"DEBUG: Extracted {len(questions)} questions")

        conn = get_db_connection()
        cursor = conn.cursor()
        param = get_param_style()

        resource_insert = """
            INSERT INTO resources (title, resource_type, subject, grade, file_name, description, status, created_by)
            VALUES ({}, {}, {}, {}, {}, {}, {}, {})
        """.format(param, param, param, param, param, param, param, param)
        if is_postgres():
            resource_insert += " RETURNING id"
        cursor.execute(resource_insert, (title, resource_type, subject, grade, filename, instructions, 'draft', session['user_id']))
        
        if is_postgres():
            resource_id = cursor.fetchone()['id']
        else:
            resource_id = cursor.lastrowid
        conn.commit()

        pending_insert = f"""
            INSERT INTO pending_exams (
                resource_id, title, resource_type, subject, grade, academic_year,
                school_name, instructions, source_filename, uploaded_by
            )
            VALUES ({param}, {param}, {param}, {param}, {param}, {param}, {param}, {param}, {param}, {param})
        """
        if is_postgres():
            pending_insert += " RETURNING id"
        cursor.execute(pending_insert, (
            resource_id, title, resource_type, subject, grade,
            ai_data.get('academic_year') or academic_year,
            ai_data.get('school_name') or request.form.get('school_name', '').strip(),
            ai_data.get('instructions') or instructions,
            filename, session['user_id']
        ))
        
        if is_postgres():
            pending_exam_id = cursor.fetchone()['id']
        else:
            pending_exam_id = cursor.lastrowid
        conn.commit()

        classified_count = 0
        error_count = 0
        
        for idx, q in enumerate(questions):
            try:
                q_text = q.get('question') or q.get('question_text', '')
                if not q_text:
                    continue

                # The full-PDF parser already classifies each question against the
                # textbook curriculum. Only call the per-question fallback when
                # an imported JSON question has no classification fields.
                if any(q.get(field) for field in (
                    'unit_number', 'unit_title', 'section_number', 'section_title',
                    'topic_title', 'subtopic'
                )):
                    classification = {
                        'unit_number': q.get('unit_number'),
                        'unit_title': q.get('unit_title'),
                        'section_number': q.get('section_number'),
                        'section_title': q.get('section_title'),
                        'topic_title': q.get('topic_title'),
                        'subtopic': q.get('subtopic'),
                        'confidence': q.get('confidence', 'Low'),
                        'reason': q.get('reason', 'Classified during full PDF extraction')
                    }
                else:
                    classification = classify_question_with_curriculum(q_text, subject, grade)
                
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
                        unit_number, unit_title, section_number, section_title, topic_title, subtopic,
                        confidence, classification_reason, status
                    )
                        VALUES ({param}, {param}, {param}, {param}, {param}, {param}, {param}, {param},
                            {param}, {param}, {param}, {param},
                            {param}, {param}, {param}, {param}, {param}, {param},
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
                    classification.get('unit_number'),
                    classification.get('unit_title'),
                    classification.get('section_number'),
                    classification.get('section_title'),
                    classification.get('topic_title'),
                    classification.get('subtopic'),
                    classification.get('confidence', 'Low'),
                    classification.get('reason', 'Auto-classified'),
                    'pending'
                ))
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
            "message": f"✅ File processed! {classified_count} questions extracted and classified. {error_count} errors.",
            "pending_exam_id": pending_exam_id,
            "total_questions": len(questions),
            "classified": classified_count,
            "errors": error_count
        })

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
        'unit_number', 'unit_title', 'section_number', 'section_title', 
        'topic_title', 'subtopic', 'confidence', 'classification_reason'
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
            SELECT pe.*, r.*
            FROM pending_exams pe
            JOIN resources r ON pe.resource_id = r.id
            WHERE pe.id = {param}
        """, (pending_exam_id,))
        pending_exam = cursor.fetchone()
        
        if not pending_exam:
            return jsonify({"error": "Pending exam not found"}), 404

        exam_insert = f"""
            INSERT INTO exams (
                resource_id, title, category, resource_type, subject, grade, 
                academic_year, school_name, instructions
            )
            VALUES ({param}, {param}, {param}, {param}, {param}, {param}, {param}, {param}, {param})
        """
        if is_postgres():
            exam_insert += " RETURNING id"
        cursor.execute(exam_insert, (
            pending_exam['resource_id'], 
            pending_exam['title'], 
            pending_exam['subject'],
            pending_exam['resource_type'],
            pending_exam['subject'],
            pending_exam['grade'],
            pending_exam['academic_year'] or '',
            pending_exam['school_name'] or '',
            pending_exam['instructions'] or ''
        ))
        
        if is_postgres():
            exam_id = cursor.fetchone()['id']
        else:
            exam_id = cursor.lastrowid
        conn.commit()

        cursor.execute(f"""
            SELECT * FROM pending_questions 
            WHERE pending_exam_id = {param} AND status = {param}
        """, (pending_exam_id, 'pending'))
        pending_questions = cursor.fetchall()

        if not pending_questions:
            return jsonify({"error": "No pending questions found for this exam"}), 404

        inserted_count = 0
        for pq in pending_questions:
            unit_id = section_id = topic_id = chapter_id = None
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
                pending_exam['subject'], pending_exam['grade'],
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
                    unit_id, pq['section_number'] or pq['section_title']
                ))
                section = cursor.fetchone()
                if section:
                    section_id = section['id']

                    if pq['topic_title']:
                        cursor.execute(f"""
                            SELECT id
                            FROM curriculum_topics
                            WHERE section_id = {param}
                              AND LOWER(TRIM(topic_title)) = LOWER(TRIM({param}))
                            LIMIT 1
                        """, (section_id, pq['topic_title']))
                        topic = cursor.fetchone()
                        if topic:
                            topic_id = topic['id']

            chapter_name = pq['topic_title'] or pq['unit_title'] or 'Unclassified'
            cursor.execute(f"""
                SELECT id FROM chapters
                WHERE subject = {param} AND grade = {param} AND name = {param}
            """, (pending_exam['subject'], pending_exam['grade'], chapter_name))
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
                cursor.execute(chapter_insert, (pending_exam['subject'], pending_exam['grade'], chapter_name))
                chapter_id = cursor.fetchone()['id'] if is_postgres() else cursor.lastrowid

            cursor.execute(f"""
                INSERT INTO questions (
                    exam_id, chapter_id, question_number, source_year, question_text,
                    option_a, option_b, option_c, option_d,
                    correct_answer, explanation, passage_text, diagram_instruction,
                    curriculum_unit_id, curriculum_section_id, curriculum_topic_id,
                    classification_confidence, classification_reason
                )
                VALUES ({param}, {param}, {param}, {param}, {param}, {param}, {param}, {param},
                    {param}, {param}, {param}, {param}, {param}, {param}, {param}, {param}, {param}, {param})
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
                topic_id,
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
        
        # --- Save AI Response ---
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

# ============================================
# AI TUTOR THREAD MANAGEMENT ENDPOINTS
# ============================================

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

# ============================================
# AI TUTOR SIMPLE CHAT (Legacy)
# ============================================

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

# ============================================
# AI TUTOR STATS ENDPOINT
# ============================================

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

# ============================================
# AI TUTOR SEARCH ENDPOINT
# ============================================

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
# CURRICULUM SEEDING API (Admin Only)
# ============================================

def normalize_curriculum_json(data):
    """Convert one textbook JSON or the older multi-subject format to one shape."""
    if data.get('subjects'):
        return data['subjects']

    subject_name = data.get('subject')
    grade_number = data.get('grade')
    if not subject_name or not grade_number:
        raise ValueError("JSON must contain subject, grade, and units.")

    return [{
        'name': subject_name,
        'grades': [{
            'number': grade_number,
            'units': data.get('units', [])
        }]
    }]


def seed_curriculum_file(file_path):
    """Seed one textbook JSON file directly into the curriculum tables."""
    with open(file_path, 'r', encoding='utf-8') as curriculum_file:
        subjects = normalize_curriculum_json(json.load(curriculum_file))

    conn = get_db_connection()
    cursor = conn.cursor()
    param = get_param_style()
    counts = {'subjects': 0, 'grades': 0, 'units': 0, 'sections': 0, 'topics': 0}

    try:
        for subject_data in subjects:
            subject_name = subject_data.get('name')
            if not subject_name:
                continue
            cursor.execute(
                f"INSERT INTO curriculum_subjects (name) VALUES ({param}) ON CONFLICT (name) DO NOTHING",
                (subject_name,)
            )
            cursor.execute(f"SELECT id FROM curriculum_subjects WHERE name = {param}", (subject_name,))
            subject_id = cursor.fetchone()['id']
            counts['subjects'] += 1

            for grade_data in subject_data.get('grades', []):
                grade_number = grade_data.get('number')
                if not grade_number:
                    continue
                cursor.execute(
                    f"INSERT INTO curriculum_grades (number) VALUES ({param}) ON CONFLICT (number) DO NOTHING",
                    (grade_number,)
                )
                cursor.execute(f"SELECT id FROM curriculum_grades WHERE number = {param}", (grade_number,))
                grade_id = cursor.fetchone()['id']
                counts['grades'] += 1

                for unit_data in grade_data.get('units', []):
                    unit_number = unit_data.get('unit_number')
                    unit_title = unit_data.get('unit_title') or unit_data.get('title')
                    if unit_number is None or not unit_title:
                        continue
                    cursor.execute(f"""
                        INSERT INTO curriculum_units (subject_id, grade_id, unit_number, title)
                        VALUES ({param}, {param}, {param}, {param})
                        ON CONFLICT (subject_id, grade_id, unit_number) DO UPDATE SET title = {param}
                    """, (subject_id, grade_id, unit_number, unit_title, unit_title))
                    cursor.execute(f"""
                        SELECT id FROM curriculum_units
                        WHERE subject_id = {param} AND grade_id = {param} AND unit_number = {param}
                    """, (subject_id, grade_id, unit_number))
                    unit_id = cursor.fetchone()['id']
                    counts['units'] += 1

                    for section_data in unit_data.get('sections', []):
                        section_number = section_data.get('section_number')
                        section_title = section_data.get('section_title') or section_data.get('title')
                        if not section_number or not section_title:
                            continue
                        cursor.execute(f"""
                            INSERT INTO curriculum_sections (unit_id, section_number, title)
                            VALUES ({param}, {param}, {param})
                            ON CONFLICT (unit_id, section_number) DO UPDATE SET title = {param}
                        """, (unit_id, section_number, section_title, section_title))
                        cursor.execute(f"""
                            SELECT id FROM curriculum_sections
                            WHERE unit_id = {param} AND section_number = {param}
                        """, (unit_id, section_number))
                        section_id = cursor.fetchone()['id']
                        counts['sections'] += 1

                        for topic_data in section_data.get('topics', []):
                            topic_title = topic_data.get('topic_title') or topic_data.get('title')
                            subtopics = topic_data.get('subtopics')
                            if subtopics is None:
                                subtopics = [topic_data.get('subtopic')]
                            if not topic_title:
                                continue
                            for subtopic in subtopics:
                                cursor.execute(f"""
                                    INSERT INTO curriculum_topics (section_id, topic_title, subtopic)
                                    VALUES ({param}, {param}, {param})
                                    ON CONFLICT (section_id, topic_title, subtopic) DO NOTHING
                                """, (section_id, topic_title, subtopic))
                                counts['topics'] += 1

        conn.commit()
        return counts
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


def seed_databasejson_folder():
    folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Databasejson')
    if not os.path.isdir(folder):
        return {'files': 0, 'subjects': 0, 'grades': 0, 'units': 0, 'sections': 0, 'topics': 0}
    totals = {'files': 0, 'subjects': 0, 'grades': 0, 'units': 0, 'sections': 0, 'topics': 0}
    for file_name in sorted(os.listdir(folder)):
        if not file_name.lower().endswith('.json'):
            continue
        counts = seed_curriculum_file(os.path.join(folder, file_name))
        totals['files'] += 1
        for key in totals:
            if key != 'files':
                totals[key] += counts[key]
    return totals

@app.route('/api/admin/seed_curriculum', methods=['POST'])
@admin_required
def seed_curriculum():
    try:
        file = request.files.get('file')
        if file and file.filename.lower().endswith('.json'):
            temp_path = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(file.filename))
            file.save(temp_path)
            try:
                counts = seed_curriculum_file(temp_path)
            finally:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
        else:
            counts = seed_databasejson_folder()
        return jsonify({"success": True, "message": "Curriculum seeded from Databasejson.", "counts": counts})
        
    except Exception as e:
        print(f"ERROR seeding curriculum: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

# ============================================
# SEED DEFAULT CURRICULUM ON STARTUP
# ============================================

def seed_default_curriculum_if_empty():
    conn = get_db_connection()
    cursor = conn.cursor()
    param = get_param_style()
    
    cursor.execute("SELECT COUNT(*) as count FROM curriculum_subjects")
    count = cursor.fetchone()
    
    if count and count['count'] == 0:
        print("Seeding default curriculum structure...")
        subjects = ['Mathematics', 'Physics', 'Chemistry', 'Biology', 'English', 'Geography', 'History', 'Economics', 'Aptitude']
        grades = [9, 10, 11, 12]
        
        for subject in subjects:
            cursor.execute(f"INSERT INTO curriculum_subjects (name) VALUES ({param}) ON CONFLICT (name) DO NOTHING", (subject,))
        
        for grade in grades:
            cursor.execute(f"INSERT INTO curriculum_grades (number) VALUES ({param}) ON CONFLICT (number) DO NOTHING", (grade,))
        
        conn.commit()
        print("Default curriculum seeded.")
    
    cursor.close()
    conn.close()

try:
    seed_default_curriculum_if_empty()
except Exception as e:
    print(f"Curriculum seeding error: {e}")

try:
    databasejson_counts = seed_databasejson_folder()
    print(f"Databasejson curriculum seeded: {databasejson_counts}")
except Exception as e:
    print(f"Databasejson seeding error: {e}")

# ============================================
# MAIN ENTRY POINT
# ============================================

if __name__ == '__main__':
    if not os.path.exists('uploads'):
        os.makedirs('uploads')
    debug_mode = os.getenv('FLASK_DEBUG', '0') == '1'
    app.run(debug=debug_mode, threaded=True, port=5000)