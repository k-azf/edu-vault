import os
import sqlite3
from werkzeug.security import generate_password_hash

# Detect if running on Render / Supabase PostgreSQL or local SQLite
DATABASE_URL = os.getenv("DATABASE_URL")
import sqlite3

import os
import sqlite3

def fix_database_schema():
    # 1. Folderni 'data' yoo hin jirre otomaatikiin uumuu
    os.makedirs('data', exist_ok=True)
    
    # 2. Path database lamaanuu check gochuu ('data/exams.db' fi 'exams.db')
    db_paths = ['data/exams.db', 'exams.db']
    
    for db_path in db_paths:
        if os.path.exists(db_path) or db_path == 'data/exams.db':
            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                
                # Column 'grade' table-oota hunda irratti check/add gochuu
                tables = ['exams', 'worksheets', 'questions', 'resources']
                
                for table in tables:
                    try:
                        cursor.execute(f"ALTER TABLE {table} ADD COLUMN grade TEXT;")
                        print(f"✅ Column 'grade' successfully added to '{table}' in {db_path}!")
                    except sqlite3.OperationalError:
                        # Column'n duraan jira ta'a
                        pass
                
                conn.commit()
                conn.close()
            except Exception as e:
                print(f"Error updating {db_path}: {e}")

if __name__ == "__main__":
    fix_database_schema()

# System jalqabutti waamuuf:
if __name__ == "__main__":
    fix_database_schema()
def init_db():
    if DATABASE_URL:
        # --- SUPABASE / POSTGRESQL MIGRATION ---
        import psycopg2
        print("Connecting to Cloud Database (Supabase)...")
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()

        # 1. Users Table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'student',
                telegram_id TEXT,
                is_verified INTEGER DEFAULT 0,
                streak_count INTEGER DEFAULT 0,
                last_activity TEXT,
                daily_goal_mins INTEGER DEFAULT 30
            )
        ''')

        # 2. Group Invites Table (Telegram bot invite tracking)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS group_invites (
                inviter_id TEXT PRIMARY KEY,
                inviter_username TEXT,
                invite_count INTEGER DEFAULT 0
            )
        ''')

        # 3. Exams & Resources Table (Categorized by Worksheet, Entrance, Subject & Grade)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS exams (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                category TEXT NOT NULL,
                resource_type TEXT DEFAULT 'Exam',
                subject TEXT DEFAULT 'General',
                grade INTEGER DEFAULT 12,
                school_name TEXT,
                department TEXT,
                academic_year TEXT,
                instructions TEXT,
                total_marks INTEGER DEFAULT 100
            )
        ''')

        # 4. Chapters Table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS chapters (
                id SERIAL PRIMARY KEY,
                subject TEXT NOT NULL,
                grade INTEGER DEFAULT 12,
                name TEXT NOT NULL,
                question_count INTEGER DEFAULT 0,
                estimated_time_mins INTEGER DEFAULT 45,
                difficulty TEXT DEFAULT 'Medium'
            )
        ''')

        # 5. Questions Table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS questions (
                id SERIAL PRIMARY KEY,
                exam_id INTEGER REFERENCES exams(id) ON DELETE CASCADE,
                chapter_id INTEGER REFERENCES chapters(id) ON DELETE SET NULL,
                question_text TEXT NOT NULL,
                option_a TEXT NOT NULL,
                option_b TEXT NOT NULL,
                option_c TEXT NOT NULL,
                option_d TEXT NOT NULL,
                correct_answer TEXT NOT NULL,
                explanation TEXT NOT NULL,
                passage_text TEXT,
                diagram_instruction TEXT
            )
        ''')

        # 6. User Exam Results Table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_results (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                exam_id INTEGER REFERENCES exams(id) ON DELETE CASCADE,
                score INTEGER NOT NULL,
                total_questions INTEGER NOT NULL,
                time_used_seconds INTEGER NOT NULL,
                accuracy REAL NOT NULL,
                date_attempted TEXT NOT NULL,
                ai_recommendation TEXT
            )
        ''')

        # Seed Default Administrator
        cursor.execute("SELECT * FROM users WHERE username = 'admin'")
        if not cursor.fetchone():
            cursor.execute('''
                INSERT INTO users (username, password_hash, role, is_verified) 
                VALUES (%s, %s, %s, %s)
            ''', ("admin", generate_password_hash("admin123"), "admin", 1))
            print("-> Admin account created: admin / admin123")

        conn.commit()
        cursor.close()
        conn.close()
        print("✅ Supabase PostgreSQL Database Initialized successfully.")

    else:
        # --- LOCAL SQLITE FALLBACK ---
        print("Connecting to Local SQLite Database (exams.db)...")
        conn = sqlite3.connect('exams.db')
        cursor = conn.cursor()

        # 1. Users Table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'student',
                telegram_id TEXT,
                is_verified INTEGER DEFAULT 0,
                streak_count INTEGER DEFAULT 0,
                last_activity TEXT,
                daily_goal_mins INTEGER DEFAULT 30
            )
        ''')

        # 2. Group Invites Table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS group_invites (
                inviter_id TEXT PRIMARY KEY,
                inviter_username TEXT,
                invite_count INTEGER DEFAULT 0
            )
        ''')

        # 3. Exams Table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS exams (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                category TEXT NOT NULL,
                resource_type TEXT DEFAULT 'Exam',
                subject TEXT DEFAULT 'General',
                grade INTEGER DEFAULT 12,
                school_name TEXT,
                department TEXT,
                academic_year TEXT,
                instructions TEXT,
                total_marks INTEGER DEFAULT 100
            )
        ''')

        # Alter columns if missing in local db
        try: cursor.execute("ALTER TABLE exams ADD COLUMN resource_type TEXT DEFAULT 'Exam';")
        except sqlite3.OperationalError: pass
        try: cursor.execute("ALTER TABLE exams ADD COLUMN subject TEXT DEFAULT 'General';")
        except sqlite3.OperationalError: pass
        try: cursor.execute("ALTER TABLE exams ADD COLUMN grade INTEGER DEFAULT 12;")
        except sqlite3.OperationalError: pass

        # 4. Chapters Table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS chapters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject TEXT NOT NULL,
                grade INTEGER DEFAULT 12,
                name TEXT NOT NULL,
                question_count INTEGER DEFAULT 0,
                estimated_time_mins INTEGER DEFAULT 45,
                difficulty TEXT DEFAULT 'Medium'
            )
        ''')

        # 5. Questions Table
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

        # 6. User Exam Results Table
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
        ''')

        # Seed Default Administrator
        cursor.execute("SELECT * FROM users WHERE username = 'admin'")
        if not cursor.fetchone():
            cursor.execute('''
                INSERT INTO users (username, password_hash, role, is_verified) 
                VALUES (?, ?, ?, ?)
            ''', ("admin", generate_password_hash("admin123"), "admin", 1))

        conn.commit()
        conn.close()
        print("✅ Local SQLite Database Initialized successfully.")

if __name__ == "__main__":
    init_db()