import os
import sqlite3
from werkzeug.security import generate_password_hash

DATABASE_URL = os.getenv("DATABASE_URL")

def fix_sqlite_schema(db_path):
    """Ensures all missing columns (like grade, subject, resource_type) exist in SQLite."""
    if not os.path.exists(db_path):
        return

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # List of ALTER statements to run safely on SQLite tables
        migrations = [
            ("exams", "ADD COLUMN resource_type TEXT DEFAULT 'Exam'"),
            ("exams", "ADD COLUMN subject TEXT DEFAULT 'General'"),
            ("exams", "ADD COLUMN grade INTEGER DEFAULT 12"),
            ("chapters", "ADD COLUMN grade INTEGER DEFAULT 12"),
        ]

        for table, action in migrations:
            try:
                cursor.execute(f"ALTER TABLE {table} {action};")
                print(f"✅ Migration applied: {table} -> {action} in [{db_path}]")
            except sqlite3.OperationalError:
                # Column already exists or table doesn't exist yet
                pass

        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error checking schema for {db_path}: {e}")


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

        # 2. Group Invites Table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS group_invites (
                inviter_id TEXT PRIMARY KEY,
                inviter_username TEXT,
                invite_count INTEGER DEFAULT 0
            );
        ''')

        # 3. Exams & Resources Table
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

        # Safely add missing columns in PostgreSQL if existing table lacks them
        pg_migrations = [
            "ALTER TABLE exams ADD COLUMN IF NOT EXISTS resource_type TEXT DEFAULT 'Exam';",
            "ALTER TABLE exams ADD COLUMN IF NOT EXISTS subject TEXT DEFAULT 'General';",
            "ALTER TABLE exams ADD COLUMN IF NOT EXISTS grade INTEGER DEFAULT 12;"
        ]
        for query in pg_migrations:
            try:
                cursor.execute(query)
            except Exception:
                conn.rollback()

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
            );
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
            );
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
            );
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
        print("Connecting to Local SQLite Database...")

        db_locations = ['data/exams.db', 'exams.db']

        for db_file in db_locations:
            conn = sqlite3.connect(db_file)
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

            # Run column migration fix on SQLite database file
            fix_sqlite_schema(db_file)

        print("✅ Local SQLite Database Initialized & Schema Fixed successfully.")

if __name__ == "__main__":
    init_db()