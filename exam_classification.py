"""Canonical classification for imported EduVault examination content."""

EXAMINATION_TYPES = {
    "official_entrance_exam": "Official Entrance Exam",
    "entrance_exam_worksheet": "Entrance Exam Worksheet",
    "school_final_exam": "School Final Exam",
    "school_midterm_exam": "School Midterm Exam",
    "school_test": "School Test",
    "worksheet": "Worksheet",
    "practical_question": "Practical Question",
    "practical_worksheet": "Practical Worksheet",
    "chapter_practice": "Chapter Practice",
    "other_core_subject": "Other Core Subject Examination",
}

EXAMINATION_DESTINATIONS = {
    "official_entrance_exam": "entrance_exam_portal",
    "entrance_exam_worksheet": "core_subjects",
    "school_final_exam": "core_subjects",
    "school_midterm_exam": "core_subjects",
    "school_test": "core_subjects",
    "worksheet": "practical_questions",
    "practical_question": "practical_questions",
    "practical_worksheet": "practical_questions",
    "chapter_practice": "chapter_practice",
    "other_core_subject": "core_subjects",
}


def normalize_examination_type(value, resource_type="", category=""):
    """Resolve a selected type or legacy category to one canonical destination type."""
    raw = str(value or "").strip().casefold().replace("-", "_").replace(" ", "_")
    if raw in EXAMINATION_TYPES:
        return raw
    by_label = {label.casefold(): key for key, label in EXAMINATION_TYPES.items()}
    if raw.replace("_", " ") in by_label:
        return by_label[raw.replace("_", " ")]

    legacy = f"{category} {resource_type}".casefold()
    if "national entrance" in legacy or "university entrance" in legacy or "euee" in legacy or "official entrance" in legacy:
        return "official_entrance_exam"
    if "chapter worksheet" in legacy or "entrance worksheet" in legacy:
        return "entrance_exam_worksheet"
    if "midterm" in legacy:
        return "school_midterm_exam"
    if "final" in legacy:
        return "school_final_exam"
    if "test" in legacy:
        return "school_test"
    if "practical" in legacy:
        return "practical_worksheet" if "worksheet" in legacy else "practical_question"
    if "worksheet" in legacy:
        return "worksheet"
    if "chapter practice" in legacy or "practice" in legacy:
        return "chapter_practice"
    return "other_core_subject"


def examination_destination(examination_type):
    """Return the existing EduVault destination for a canonical examination type."""
    kind = normalize_examination_type(examination_type)
    return EXAMINATION_DESTINATIONS[kind]
