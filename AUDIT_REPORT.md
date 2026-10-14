# Edu-Vault Website Integration Audit

## Fixes implemented

1. **Worksheet navigation**
   - Changed the Worksheets card on the home page (`templates/index.html`) from `/resources` to `/worksheets`, matching the Flask route.
   - Updated worksheet cards to use the actual `pdf_url` / `file_url` returned by `/api/worksheets` instead of incorrectly opening `/exam/<resource-id>`.
   - If a published worksheet has no file URL, the page now clearly shows that the file is unavailable rather than sending students to an unrelated exam.
   - Added defensive handling for missing worksheet titles/subjects and HTML escaping for rendered worksheet values.

2. **Chapter filtering / category selection**
   - Fixed the recursive render/filter loop: `renderChapters()` called `filterChapters()`, which called `renderChapters()` again when filters were empty. This could cause an infinite recursion.
   - Added a category selector populated from the real unit titles returned by the curriculum API. Selecting a unit filters to that unit; search filters units, sections, topics, and subtopics.
   - Removed the nonfunctional difficulty filter because the current curriculum response does not include per-question difficulty data; the old filter accepted every topic regardless of selected difficulty.
   - Added API response validation and a useful HTTP error message for failed curriculum requests.
   - Direct chapter links with `?grade=9`, `?grade=10`, `?grade=11`, or `?grade=12` now initialize the matching grade.

3. **Subject navigation**
   - Kept the existing `/subject/<name>` and `/chapters/<subject>` Flask routes and existing subject links intact; the subject page's chapter links match the existing route structure.

## Checks performed

- JavaScript syntax check (`node --check`) passed for inline scripts in `index.html`, `worksheet.html`, `chapter.html`, `subject.html`, and all three inline scripts in `base.html`.
- Python syntax compilation passed for `app.py`, `init_db.py`, and `ranking.py`.
- Confirmed that the homepage Worksheets card now points to `/worksheets`.

## Remaining limitations / manual checks

- The project archive does not provide a live configured database/session or a running browser session here, so authenticated, end-to-end interactions and actual worksheet file downloads could not be exercised against live data.
- The database/API does not define a separate `category` field for curriculum chapters. The category selector therefore uses the existing curriculum unit titles as categories and does not invent new subject taxonomy.
- Please test the final archive locally with a populated database and a student login, especially worksheet file URLs and practice-question endpoints.


## Additional fixes (2026-10-13)

4. **Subject hub navigation**
   - Updated the homepage subject cards for Mathematics, Biology, Physics, Chemistry, English, Aptitude, Geography, History, and Economics to open `/subject/<name>` first. The subject hub then links to grade-specific chapter practice.

5. **Batch AI curriculum classification**
   - Added `classify_questions_in_batches()` to classify missing labels in batches of 20, instead of making one Gemini request for each question.
   - Uses the official curriculum loaded from the database and a few previously classified questions as prompt-only examples when available. Examples are not inserted as exam questions.
   - Validates unit and section labels against curriculum records; questionable labels are marked Low confidence for review.
   - If Gemini quota is exhausted, questions are still saved with Low confidence instead of failing the entire upload.
   - PDF extraction now focuses on extracting the questions first; curriculum classification is a separate batch step.

6. **Duplicate questions**
   - Exact duplicate question text inside a single uploaded file is deduplicated, keeping the last occurrence. This avoids repeated copies in the newly uploaded exam. Sample examples used by AI are never inserted into the database. Existing approved exams are not destructively changed.

## Additional checks

- `python -m py_compile app.py init_db.py ranking.py` passed after the changes.
- This is a code-level fix; Gemini quota, curriculum completeness, and end-to-end approval still require a configured API key and populated database to verify live.
