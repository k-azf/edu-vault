import unittest

from exam_classification import EXAMINATION_DESTINATIONS, EXAMINATION_TYPES, examination_destination, normalize_examination_type


class ExaminationClassificationTests(unittest.TestCase):
    def test_every_supported_type_has_one_destination(self):
        self.assertEqual(set(EXAMINATION_TYPES), set(EXAMINATION_DESTINATIONS))
        self.assertEqual(examination_destination('official_entrance_exam'), 'entrance_exam_portal')
        for kind in ('entrance_exam_worksheet', 'school_final_exam', 'school_midterm_exam', 'school_test', 'other_core_subject'):
            self.assertEqual(examination_destination(kind), 'core_subjects')
        for kind in ('worksheet', 'practical_question', 'practical_worksheet'):
            self.assertEqual(examination_destination(kind), 'practical_questions')
        self.assertEqual(examination_destination('chapter_practice'), 'chapter_practice')

    def test_legacy_categories_and_worksheet_rule(self):
        self.assertEqual(normalize_examination_type(None, 'Exam', 'National Entrance (EUEE)'), 'official_entrance_exam')
        self.assertEqual(normalize_examination_type(None, 'Worksheet', 'Grade 12 Worksheet'), 'worksheet')
        self.assertEqual(normalize_examination_type(None, 'Exam', 'School Midterm'), 'school_midterm_exam')
        self.assertEqual(normalize_examination_type(None, 'Exam', 'AI Generated Practice'), 'chapter_practice')


if __name__ == '__main__':
    unittest.main()
