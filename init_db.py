import os
import sqlite3
from werkzeug.security import generate_password_hash

DATABASE_URL = os.getenv("DATABASE_URL")

def init_db():
    os.makedirs('data', exist_ok=True)

    if DATABASE_URL:
        # --- SUPABASE / POSTGRESQL MIGRATION ---
        import psycopg2
        print("Connecting to Cloud Database (Supabase / PostgreSQL)...")
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
            );
        ''')

        # 2. Exams Table
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
            );
        ''')

        # 3. Chapters Table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS chapters (
                id SERIAL PRIMARY KEY,
                subject TEXT NOT NULL,
                grade INTEGER DEFAULT 12,
                name TEXT NOT NULL,
                question_count INTEGER DEFAULT 0,
                estimated_time_mins INTEGER DEFAULT 45,
                difficulty TEXT DEFAULT 'Medium'
            );
        ''')

        # 4. Questions Table
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
            );
        ''')

        # --- POSTGRESQL CRITICAL MIGRATIONS (Fixes 'column grade does not exist') ---
        pg_migrations = [
            "ALTER TABLE exams ADD COLUMN IF NOT EXISTS resource_type TEXT DEFAULT 'Exam';",
            "ALTER TABLE exams ADD COLUMN IF NOT EXISTS subject TEXT DEFAULT 'General';",
            "ALTER TABLE exams ADD COLUMN IF NOT EXISTS grade INTEGER DEFAULT 12;",
            "ALTER TABLE chapters ADD COLUMN IF NOT EXISTS grade INTEGER DEFAULT 12;",
            "ALTER TABLE chapters ADD COLUMN IF NOT EXISTS subject TEXT DEFAULT 'General';",
            "ALTER TABLE questions ADD COLUMN IF NOT EXISTS chapter_id INTEGER;"
        ]
        for query in pg_migrations:
            try:
                cursor.execute(query)
                conn.commit()
            except Exception as e:
                conn.rollback()

        # Seed Default Administrator
        cursor.execute("SELECT * FROM users WHERE username = 'admin'")
        if not cursor.fetchone():
            cursor.execute('''
                INSERT INTO users (username, password_hash, role, is_verified) 
                VALUES (%s, %s, %s, %s)
            ''', ("admin", generate_password_hash("admin123"), "admin", 1))

        conn.commit()
        cursor.close()
        conn.close()
        print("✅ Supabase PostgreSQL Database Initialized & Schema Altered successfully.")

    else:
        # --- LOCAL SQLITE FALLBACK ---
        print("Connecting to Local SQLite Database...")
        db_locations = ['data/exams.db', 'exams.db']

        for db_file in db_locations:
            conn = sqlite3.connect(db_file)
            cursor = conn.cursor()

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

            # Local SQLite Migrations
            sqlite_migrations = [
                ("exams", "ADD COLUMN resource_type TEXT DEFAULT 'Exam'"),
                ("exams", "ADD COLUMN subject TEXT DEFAULT 'General'"),
                ("exams", "ADD COLUMN grade INTEGER DEFAULT 12"),
                ("chapters", "ADD COLUMN grade INTEGER DEFAULT 12"),
            ]
            for table, action in sqlite_migrations:
                try:
                    cursor.execute(f"ALTER TABLE {table} {action};")
                except sqlite3.OperationalError:
                    pass

            conn.commit()
            conn.close()

if __name__ == "__main__":
    init_db()