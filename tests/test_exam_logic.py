import unittest

from exam_logic import remaining_exam_seconds, score_saved_answers


class ExamLogicTests(unittest.TestCase):
    def test_timer_is_server_time_based_and_never_negative(self):
        self.assertEqual(remaining_exam_seconds(1000, 3600, 1123), 3477)
        self.assertEqual(remaining_exam_seconds(1000, 3600, 4700), 0)
        self.assertEqual(remaining_exam_seconds(1000, 3600, 999), 3600)

    def test_scoring_counts_correct_incorrect_and_unanswered(self):
        questions = [
            {'id': 1, 'correct_answer': 'A'},
            {'id': 2, 'correct_answer': 'C'},
            {'id': 3, 'correct_answer': 'B'},
        ]
        scored = score_saved_answers(questions, {1: 'a', 2: 'D'})
        self.assertEqual(scored, {
            'total_questions': 3,
            'correct_answers': 1,
            'incorrect_answers': 1,
            'unanswered_questions': 1,
            'percentage': 33.33,
        })


if __name__ == '__main__':
    unittest.main()
