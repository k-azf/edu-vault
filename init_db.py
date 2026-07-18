import sqlite3
from werkzeug.security import generate_password_hash

def init_db():
    conn = sqlite3.connect('exams.db')
    cursor = conn.cursor()
    
    # 1. Users Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'student',
            streak_count INTEGER DEFAULT 0,
            last_activity TEXT,
            daily_goal_mins INTEGER DEFAULT 30
        )
    ''')
    
    # 2. Exams Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS exams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            category TEXT NOT NULL,
            school_name TEXT,
            department TEXT,
            academic_year TEXT,
            instructions TEXT,
            total_marks INTEGER DEFAULT 100
        )
    ''')
    
    # 3. Chapters Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS chapters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT NOT NULL,
            name TEXT NOT NULL,
            question_count INTEGER DEFAULT 0,
            estimated_time_mins INTEGER DEFAULT 45,
            difficulty TEXT DEFAULT 'Medium'
        )
    ''')
    
    # 4. Questions Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exam_id INTEGER,
            chapter_id INTEGER,
            question_text TEXT NOT NULL,
            option_a TEXT NOT NULL,
            option_b TEXT NOT NULL,
            option_c TEXT NOT NULL,
            option_d TEXT NOT NULL,
            correct_answer TEXT NOT NULL,
            explanation TEXT NOT NULL,
            passage_text TEXT,
            diagram_instruction TEXT,
            FOREIGN KEY (exam_id) REFERENCES exams (id),
            FOREIGN KEY (chapter_id) REFERENCES chapters (id)
        )
    ''')

    # 5. User Exam Results Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            exam_id INTEGER NOT NULL,
            score INTEGER NOT NULL,
            total_questions INTEGER NOT NULL,
            time_used_seconds INTEGER NOT NULL,
            accuracy REAL NOT NULL,
            date_attempted TEXT NOT NULL,
            ai_recommendation TEXT,
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (exam_id) REFERENCES exams (id)
        )
    ''');

    # 6. Bookmarks Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bookmarks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            question_id INTEGER NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (question_id) REFERENCES questions (id)
        )
    ''')

    # 7. Notes Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            chapter_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (chapter_id) REFERENCES chapters (id)
        )
    ''')

    # Seed Default Admin
    cursor.execute("SELECT * FROM users WHERE username = 'admin'")
    if not cursor.fetchone():
        cursor.execute('''
            INSERT INTO users (username, password_hash, role) 
            VALUES (?, ?, ?)
        ''', ("admin", generate_password_hash("admin123"), "admin"))
        print("-> Default administrator created: admin / admin123")

    # Seed Default Chapters
    cursor.execute("SELECT COUNT(*) FROM chapters")
    if cursor.fetchone()[0] == 0:
        default_chapters = [
            ("Mathematics", "Sequence and Series", 24, 60, "Medium"),
            ("Mathematics", "Limits and Continuity", 18, 45, "Hard"),
            ("Mathematics", "Introduction to Calculus", 30, 90, "Hard"),
            ("Biology", "Cell Biology", 45, 40, "Easy"),
            ("Biology", "Human Anatomy", 50, 55, "Medium"),
        ]
        cursor.executemany('''
            INSERT INTO chapters (subject, name, question_count, estimated_time_mins, difficulty)
            VALUES (?, ?, ?, ?, ?)
        ''', default_chapters)

    conn.commit()
    conn.close()
    print("Database Initialized successfully.")

if __name__ == "__main__":
    init_db()