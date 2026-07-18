import os
import json
import time
import re
import sqlite3
from functools import wraps
from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash
from pypdf import PdfReader, PdfWriter
from google import genai
from google.genai import types
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash

load_dotenv()

app = Flask(__name__)
# Secure Key for encrypting cookies and user sessions
app.secret_key = os.getenv("SECRET_KEY", "super-secret-eduvault-key-12345")

# Configure Google's GenAI Client using GEMINI_API_KEY
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# Helper function to connect to the database
def get_db_connection():
    conn = sqlite3.connect('exams.db')
    conn.row_factory = sqlite3.Row
    return conn

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


# --- PDF Parser Functions (Auto-Chunked 1-Page Multimodal Processing) ---

def parse_single_chunk_with_ai(chunk_path):
    """Uploads, parses, and cleans up a single 1-page PDF segment to prevent 429 token limits."""
    print(f"DEBUG: Uploading temporary chunk {chunk_path} to Google File API...")
    uploaded_file = client.files.upload(file=chunk_path)
    
    # Wait for processing to finish
    while uploaded_file.state.name == "PROCESSING":
        time.sleep(1.5)
        uploaded_file = client.files.get(name=uploaded_file.name)

    prompt = """
    Analyze the uploaded exam document segment and convert it strictly into a structured JSON object.
    CRITICAL: This document may be a scanned exam, containing images of math formulas, chemistry bonds, or reading passages.
    Read all printed and handwritten content from the images. 

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

    models_to_try = ["gemini-2.0-flash"]
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
                
                # Delete cloud file reference immediately
                try:
                    client.files.delete(name=uploaded_file.name)
                except Exception as clean_err:
                    print(f"DEBUG: Storage cleanup warning: {clean_err}")

                # Safeguard against empty or invalid responses
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
                    if wait_time > 5:
                             raise Exception("API rate limit reached. Please wait a minute and try uploading again.")
                    time.sleep(wait_time)
                    backoff_delay *= 2
                    continue
                break

    # Force cleanup on total failure
    try:
        client.files.delete(name=uploaded_file.name)
    except Exception:
        pass
    raise Exception(f"Failed to process PDF segment. Detail: {last_error}")


def parse_pdf_with_ai(pdf_path):
    """Splits large PDFs into 1-page chunks to completely bypass the Free-tier TPM token limits."""
    reader = PdfReader(pdf_path)
    total_pages = len(reader.pages)
    print(f"DEBUG: Initiating parser. Total pages detected: {total_pages}")
    
    # Process page-by-page to keep token count extremely low
    chunk_size = 1
    all_questions = []
    school_name = None
    department = None
    academic_year = None
    instructions = None

    for start_page in range(0, total_pages, chunk_size):
        end_page = min(start_page + chunk_size, total_pages)
        print(f"DEBUG: Slicing PDF page {start_page + 1} of {total_pages}...")

        # Create temporary 1-page chunk file
        writer = PdfWriter()
        for page_num in range(start_page, end_page):
            writer.add_page(reader.pages[page_num])
            
        chunk_filename = f"temp_chunk_{start_page}_{end_page}.pdf"
        with open(chunk_filename, "wb") as f:
            writer.write(f)

        # Parse the 1-page chunk
        try:
            chunk_data = parse_single_chunk_with_ai(chunk_filename)
        except Exception as chunk_exc:
            print(f"DEBUG: Chunk processing failed at page {start_page + 1}: {chunk_exc}")
            chunk_data = None
        finally:
            if os.path.exists(chunk_filename):
                os.remove(chunk_filename)

        # Mer questionsge extracted metadata &
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


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form['username'].strip().lower()
        password = request.form['password']
        if not username or not password:
            flash("All fields are required", "error")
            return render_template('signup.html')
        
        conn = get_db_connection()
        try:
            conn.execute('INSERT INTO users (username, password_hash) VALUES (?, ?)', 
                         (username, generate_password_hash(password)))
            conn.commit()
            flash("Signup success! Please login.", "success")
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash("Username already taken", "error")
        finally:
            conn.close()
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip().lower()
        password = request.form['password']
        
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
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

# --- Page Routes ---
@app.route('/')
@login_required
def index():
    return render_template('index.html', username=session.get('username'), role=session.get('role'))

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

# --- API Services ---
@app.route('/api/exams', methods=['GET'])
@login_required
def get_exams():
    conn = get_db_connection()
    exams = conn.execute('SELECT * FROM exams').fetchall()
    conn.close()
    return jsonify([dict(exam) for exam in exams])

@app.route('/api/exams/<int:exam_id>/questions', methods=['GET'])
@login_required
def get_questions(exam_id):
    conn = get_db_connection()
    questions = conn.execute('SELECT * FROM questions WHERE exam_id = ?', (exam_id,)).fetchall()
    conn.close()
    return jsonify([dict(q) for q in questions])

@app.route('/api/chapters/<subject>', methods=['GET'])
@login_required
def get_chapters(subject):
    conn = get_db_connection()
    chaps = conn.execute('SELECT * FROM chapters WHERE subject = ?', (subject,)).fetchall()
    conn.close()
    return jsonify([dict(c) for c in chaps])

@app.route('/api/results/submit', methods=['POST'])
@login_required
def submit_exam_results():
    data = request.json
    conn = get_db_connection()
    
    score = int(data['score'])
    total = int(data['total_questions'])
    # Safely handle missing or None accuracy values
    accuracy_val = data.get('accuracy')
    accuracy = float(accuracy_val) if accuracy_val is not None else 0.0

    
    rec_prompt = f"The student scored {score}/{total} ({accuracy}% accuracy) in an exam. Provide a brief, supportive, 2-sentence study plan."
    try:
        response = client.models.generate_content(model="gemini-2.0-flash", contents=rec_prompt)
        recommendation = response.text
    except Exception:
        recommendation = "Focus on weak chapters and review explanations for incorrect attempts."

    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO user_results (user_id, exam_id, score, total_questions, time_used_seconds, accuracy, date_attempted, ai_recommendation)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (session['user_id'], data['exam_id'], score, total, data['time_used'], accuracy, time.strftime("%Y-%m-%d %H:%M"), recommendation))
    
    result_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return jsonify({"success": True, "result_id": result_id})

@app.route('/api/results/<int:result_id>', methods=['GET'])
@login_required
def get_result_details(result_id):
    conn = get_db_connection()
    result = conn.execute('''
        SELECT r.*, e.title as exam_title, e.category as exam_category
        FROM user_results r
        JOIN exams e ON r.exam_id = e.id
        WHERE r.id = ? AND r.user_id = ?
    ''', (result_id, session['user_id'])).fetchone()
    conn.close()
    if not result:
        return jsonify({"error": "Result not found"}), 404
    return jsonify(dict(result))

@app.route('/api/upload', methods=['POST'])
@admin_required
def upload_pdf():
    title = request.form['title']
    category = request.form['category']
    file = request.files['pdf_file']
    
    if not file:
        return jsonify({"error": "No file uploaded"}), 400
        
    filepath = os.path.join('uploads', file.filename)
    file.save(filepath)
    
    try:
        ai_data = parse_pdf_with_ai(filepath)
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO exams (title, category, school_name, department, academic_year, instructions) 
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (title, category, ai_data.get('school_name'), ai_data.get('department'), ai_data.get('academic_year'), ai_data.get('instructions')))
        exam_id = cursor.lastrowid
        
        for q in ai_data['questions']:
            cursor.execute('''
                INSERT INTO questions (exam_id, question_text, option_a, option_b, option_c, option_d, correct_answer, explanation, passage_text, diagram_instruction)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (exam_id, q['question'], q['A'], q['B'], q['C'], q['D'], q['correct'], q['explanation'], q.get('passage_text'), q.get('diagram_instruction')))
            
        conn.commit()
        conn.close()
        return jsonify({"success": True, "message": "Exam parsed and saved successfully!"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if os.path.exists(filepath):
            os.remove(filepath)

# --- AI Tutor Chat Service ---
@app.route('/api/tutor/chat', methods=['POST'])
@login_required
def tutor_chat():
    user_message = request.json.get("message")
    if not user_message:
        return jsonify({"error": "Message is required"}), 400
        
    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=f"You are an empathetic, world-class academic tutor. Help the student with this query: {user_message}"
        )
        return jsonify({"response": response.text})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    if not os.path.exists('uploads'):
        os.makedirs('uploads')
    app.run(debug=True, port=5000)