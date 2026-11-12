"""Pure helpers for server-owned exam timing and scoring."""

def remaining_exam_seconds(started_at_epoch, duration_seconds, now_epoch):
    """Calculate nonnegative remaining time from the persisted start instant."""
    elapsed = max(0, int(float(now_epoch) - float(started_at_epoch)))
    return max(0, int(duration_seconds) - elapsed)


def score_saved_answers(question_rows, saved_answers):
    """Score only answers already saved against trusted server question rows."""
    total = len(question_rows)
    correct = 0
    answered = 0
    for question in question_rows:
        selected = str(saved_answers.get(question['id']) or '').strip().upper()
        if selected:
            answered += 1
            correct += int(selected == str(question.get('correct_answer') or '').strip().upper())
    unanswered = total - answered
    incorrect = answered - correct
    percentage = round(correct / total * 100, 2) if total else 0.0
    return {
        'total_questions': total,
        'correct_answers': correct,
        'incorrect_answers': incorrect,
        'unanswered_questions': unanswered,
        'percentage': percentage,
    }
