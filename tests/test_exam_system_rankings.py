import unittest

from ranking import calculate_exam_system_entrance_top_performers, calculate_exam_system_mock_top_performers


class ExamSystemRankingTests(unittest.TestCase):
    def test_entrance_requires_all_six_and_uses_best_complete_cycle(self):
        rows = []
        subjects = ('Mathematics', 'Biology', 'Physics', 'Chemistry', 'English', 'SAT')
        for subject in subjects:
            rows.append({'studentCode': 'ST001', 'studentName': 'A Student', 'examType': 'entrance',
                         'cycleId': 'old', 'subject': subject, 'score': 50, 'submittedAt': '2025-01-01'})
            rows.append({'studentCode': 'ST001', 'studentName': 'A Student', 'examType': 'entrance',
                         'cycleId': 'best', 'subject': subject, 'score': 80, 'submittedAt': '2025-02-01'})
        rows.append({'studentCode': 'ST002', 'studentName': 'Incomplete', 'examType': 'entrance',
                     'cycleId': 'partial', 'subject': 'Mathematics', 'score': 100})
        rows.append({'studentCode': 'ST003', 'examType': 'practice', 'subject': 'SAT', 'score': 100})
        leaders = calculate_exam_system_entrance_top_performers(rows)
        self.assertEqual(len(leaders), 1)
        self.assertEqual(leaders[0]['student_code'], 'ST001')
        self.assertEqual(leaders[0]['score'], 480)
        self.assertEqual(leaders[0]['rank'], 1)

    def test_mock_board_uses_each_students_highest_mock_score(self):
        rows = [
            {'studentCode': 'ST001', 'studentName': 'Student One', 'examType': 'mock', 'score': 65, 'submittedAt': '2025-01-01'},
            {'studentCode': 'ST001', 'studentName': 'Student One', 'examType': 'mock', 'score': 91, 'subject': 'Physics', 'submittedAt': '2025-02-01'},
            {'studentCode': 'ST001', 'studentName': 'Student One', 'examType': 'practice', 'score': 100, 'submittedAt': '2025-03-01'},
            {'studentCode': 'ST002', 'studentName': 'Student Two', 'examType': 'mock', 'score': 80},
        ]
        leaders = calculate_exam_system_mock_top_performers(rows)
        self.assertEqual([item['student_code'] for item in leaders], ['ST001', 'ST002'])
        self.assertEqual(leaders[0]['score'], 91)


if __name__ == '__main__':
    unittest.main()
