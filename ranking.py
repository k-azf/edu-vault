"""Deterministic performance ranking for EduVault students."""

from collections import defaultdict
from math import isfinite


def _as_float(value, default=0.0):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if isfinite(number) else default


def _performance_percent(result):
    """Return a normalized percentage from one stored result."""
    accuracy = _as_float(result.get("accuracy"))
    total_questions = _as_float(result.get("total_questions"))
    score = _as_float(result.get("score"))
    if total_questions > 0:
        return max(0.0, min(100.0, score / total_questions * 100.0))
    return max(0.0, min(100.0, accuracy))


def calculate_rankings(result_rows, current_user_id=None, limit=3):
    """Build the Top 3 from every student's historical result.

    Ranking order is deterministic and performance-based:
    1. Latest normalized percentage, descending.
    2. Previous normalized percentage, descending; students without a previous
       attempt receive 0 for this tie-breaker.
    3. Average normalized percentage across all attempts, descending.
    4. Attempt count, descending.
    5. Username (case-insensitive), then user id, ascending for stable output.

    Results are never deleted or collapsed; every attempt contributes to the
    historical average while only the latest two attempts drive recency ties.
    """
    grouped = defaultdict(list)
    for row in result_rows:
        user_id = row.get("user_id")
        if user_id is not None:
            grouped[user_id].append(dict(row))

    students = []
    for user_id, attempts in grouped.items():
        attempts.sort(key=lambda item: (str(item.get("date_attempted") or ""), int(item.get("id") or 0)), reverse=True)
        performances = [_performance_percent(attempt) for attempt in attempts]
        latest = performances[0]
        previous = performances[1] if len(performances) > 1 else 0.0
        average = sum(performances) / len(performances)
        first = attempts[0]
        students.append({
            "user_id": user_id,
            "username": first.get("username") or "Student",
            "latest_score": round(latest, 2),
            "previous_score": round(previous, 2) if len(performances) > 1 else None,
            "average_score": round(average, 2),
            "attempt_count": len(attempts),
            "latest_attempted": first.get("date_attempted"),
        })

    students.sort(key=lambda student: (
        -student["latest_score"],
        -(student["previous_score"] or 0.0),
        -student["average_score"],
        -student["attempt_count"],
        str(student["username"]).casefold(),
        int(student["user_id"]),
    ))

    for position, student in enumerate(students, start=1):
        student["rank"] = position

    current_student = next(
        (student for student in students if student["user_id"] == current_user_id),
        None,
    )
    return {
        "top_students": students[:limit],
        "current_student": current_student,
        "total_students": len(students),
    }