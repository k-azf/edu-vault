EDU-VAULT — UNIFIED EXAM SYSTEM DATABASE UPDATE

Unified Exam System now stores its online records in the same SQL database used by the main Edu-Vault Flask application.
postgresql://postgres.avhddkggzxpiabimbbpf:%25KayoAlemu4694%25@aws-1-eu-west-1.pooler.supabase.com:6543/postgres
Database selection:
- Production: set DATABASE_URL to the existing PostgreSQL/Supabase connection string.
- Local development: when DATABASE_URL is not set, the app uses data/exams.db (SQLite).
- The table unified_exam_records is created automatically on first API use. It stores examPackages, examSchedules, examFiles, students and results records.
- Uploaded exam PDFs are stored as binary data in the same SQL database and served by the Flask app, so cross-device access does not depend on an ephemeral local uploads folder.

Run locally:
1. Install requirements.txt.
2. Configure environment variables in your own .env file (see .env.example).
3. Run: python app.py
4. Open /eduvault-system.
5. Check GET /api/unified-exam/health to confirm the database connection.

Important migration note:
This update removes the previous external cloud database integration. It does not automatically fetch historical cloud records because no data export or service credentials were provided. Export the old collections before shutting down the old service, then import those records into the new SQL table if you need the historical cloud data. New and updated exam records will use Edu-Vault SQL going forward.

Security note: before public production use, ensure the existing admin/student authorization is enforced server-side for Unified Exam System write APIs and apply appropriate upload access controls.
