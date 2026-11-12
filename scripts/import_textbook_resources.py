"""Import the EduVault textbook archive into the local Resources file store."""

import argparse
import json
import os
import re
import shutil
import zipfile

from werkzeug.utils import secure_filename


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEXTBOOK_DIR = os.path.join(BASE_DIR, "uploads", "textbooks")
MANIFEST_PATH = os.path.join(BASE_DIR, "Databasejson", "textbook_resources.json")
SUBJECTS = ("Biology", "Chemistry", "English", "Mathematics", "Physics", "Economics", "Geography", "History")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", help="Path to EduVault Book.zip")
    args = parser.parse_args()
    os.makedirs(TEXTBOOK_DIR, exist_ok=True)
    books = []

    with zipfile.ZipFile(args.archive) as archive:
        for entry in archive.infolist():
            if entry.is_dir() or not entry.filename.lower().endswith(".pdf"):
                continue
            parts = entry.filename.split("/")
            grade_match = re.search(r"Grade\s*(9|10|11|12)", parts[1] if len(parts) > 1 else "", re.I)
            if not grade_match:
                continue
            raw_name = os.path.basename(entry.filename)
            filename = secure_filename(raw_name)
            if not filename.lower().endswith(".pdf"):
                filename += ".pdf"
            subject = next((name for name in SUBJECTS if name.lower() in raw_name.lower()), None)
            if not subject:
                continue
            grade = int(grade_match.group(1))
            title_text = os.path.splitext(raw_name)[0]
            is_teacher_guide = "(MT)" in title_text or "teacher guide" in title_text.lower()
            label = "Teacher guide and student textbook" if is_teacher_guide else "Student textbook"
            target = os.path.join(TEXTBOOK_DIR, filename)
            if not os.path.isfile(target) or os.path.getsize(target) != entry.file_size:
                with archive.open(entry) as source, open(target, "wb") as destination:
                    shutil.copyfileobj(source, destination, 1024 * 1024)
            books.append({
                "title": f"{subject} Grade {grade} {'teacher guide and textbook' if is_teacher_guide else 'textbook'}",
                "grade": grade,
                "subject": subject,
                "label": label,
                "resource_type": "Textbook",
                "file_name": filename,
                "source_name": raw_name,
            })

    books.sort(key=lambda item: (item["grade"], item["subject"]))
    with open(MANIFEST_PATH, "w", encoding="utf-8") as manifest:
        json.dump(books, manifest, ensure_ascii=False, indent=2)
        manifest.write("\n")
    print(f"Imported {len(books)} textbook PDFs into {TEXTBOOK_DIR}")


if __name__ == "__main__":
    main()
