(() => {
  const shell = document.getElementById('exam-shell');
  const examId = Number(shell?.dataset.examId);
  const picker = document.getElementById('exam-mode-picker');
  if (!shell || !examId || !picker) return;

  let attemptId = null;
  let mode = 'exam';
  let questions = [];
  let answers = {};
  let flags = new Set();
  let currentIndex = 0;
  let timeLeft = 0;
  let timerId = null;
  let finished = false;
  let activeExam = null;

  const byId = id => document.getElementById(id);
  const safe = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));

  window.startEduVaultExam = async requestedMode => {
    const error = byId('exam-start-error');
    error.textContent = '';
    document.querySelectorAll('#exam-mode-picker button').forEach(button => button.disabled = true);
    try {
      const startResponse = await fetch(`/api/exams/${examId}/attempts/start`, {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({mode: requestedMode}), cache: 'no-store'
      });
      const start = await startResponse.json();
      if (!startResponse.ok) throw new Error(start.error || 'Could not start the examination.');
      attemptId = start.attempt_id;
      mode = start.mode;
      Object.entries(start.answers || {}).forEach(([questionId, state]) => {
        if (state.answer) answers[questionId] = state.answer;
        if (state.flagged) flags.add(questionId);
      });
      const [examResponse, questionResponse, profileResponse] = await Promise.all([
        fetch('/api/exams', {cache:'no-store'}),
        fetch(`/api/exams/${examId}/questions?attempt_id=${encodeURIComponent(attemptId)}`, {cache:'no-store'}),
        fetch('/api/profile', {cache:'no-store'})
      ]);
      const exams = await examResponse.json();
      const questionBody = await questionResponse.json();
      const profile = profileResponse.ok ? await profileResponse.json() : {};
      if (!examResponse.ok || !questionResponse.ok || !Array.isArray(questionBody))
        throw new Error(questionBody.error || 'Could not load examination questions.');
      activeExam = exams.find(item => Number(item.id) === examId);
      questions = questionBody;
      if (!activeExam || !questions.length) throw new Error('This examination has no available questions.');
      picker.classList.add('hidden');
      shell.classList.remove('hidden');
      byId('exam-header-title').textContent = activeExam.title || 'Examination';
      const configuredMinutes = Math.max(1, Math.ceil(Number(start.duration_seconds || 0) / 60));
      byId('exam-header-meta').textContent = `${activeExam.subject || 'General'} · ${activeExam.examination_type || activeExam.category || 'Exam'} · ${configuredMinutes} minutes · ${mode === 'practice' ? 'Practice Mode' : 'Exam Mode'}`;
      byId('exam-student-identity').textContent = `${profile.full_name || profile.username || 'Student'} · Student Code ${profile.student_code || '—'}`;
      renderRichContent(byId('exam-instructions-content'), activeExam.instructions || '');
      byId('exam-instructions').classList.toggle('hidden', !activeExam.instructions);
      byId('exam-clock-container').classList.toggle('hidden', mode === 'practice');
      byId('exam-arena').replaceChildren();
      byId('question-nav-grid').replaceChildren();
      renderQuestions();
      currentIndex = Math.min(currentIndex, questions.length - 1);
      renderCurrentQuestion();
      byId('previous-question-btn').onclick = () => moveQuestion(-1);
      byId('next-question-btn').onclick = () => moveQuestion(1);
      byId('flag-question-btn').onclick = toggleFlag;
      if (mode === 'exam') {
        timeLeft = Number(start.remaining_seconds ?? start.duration_seconds);
        updateClock();
        if (timeLeft <= 0) endExam(true);
        else timerId = window.setInterval(() => {
          timeLeft = Math.max(0, timeLeft - 1);
          updateClock();
          if (timeLeft <= 0) endExam(true);
        }, 1000);
      }
    } catch (cause) {
      error.textContent = cause.message || String(cause);
      document.querySelectorAll('#exam-mode-picker button').forEach(button => button.disabled = false);
    }
  };

  function renderQuestions() {
    questions.forEach((question, index) => {
      const card = document.createElement('article');
      card.id = `question-card-${question.id}`;
      card.className = 'hidden bg-white dark:bg-slate-900 p-6 rounded-2xl border border-slate-200 dark:border-slate-800';
      const passage = document.createElement('div'); passage.className = 'question-passage exam-rich-content bg-blue-50/50 dark:bg-blue-950/20 border border-blue-100 dark:border-blue-900 rounded-xl p-4 mb-4 text-sm font-medium';
      const heading = document.createElement('h2'); heading.className = 'question-title text-lg sm:text-xl font-bold text-slate-800 dark:text-white mb-4'; heading.textContent = `Question ${index + 1} of ${questions.length}`;
      const text = document.createElement('div'); text.className = 'question-body exam-rich-content text-slate-800 dark:text-slate-100 mb-4';
      const diagram = document.createElement('div'); diagram.className = 'question-diagram exam-rich-content border border-slate-200 dark:border-slate-800 p-4 rounded-xl mb-4 text-sm bg-slate-50 dark:bg-slate-950 font-mono';
      const options = document.createElement('div'); options.className = 'grid gap-3'; options.id = `options-box-${question.id}`;
      const feedback = document.createElement('div'); feedback.id = `feedback-${question.id}`; feedback.className = 'hidden mt-4 rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm dark:border-emerald-900 dark:bg-emerald-950/30';
      renderRichContent(passage, question.passage_text || '');
      passage.classList.toggle('hidden', !question.passage_text);
      renderRichContent(text, question.question_text || '');
      renderRichContent(diagram, question.diagram_instruction || '');
      diagram.classList.toggle('hidden', !question.diagram_instruction);
      ['A','B','C','D'].forEach(letter => {
        const button = document.createElement('button');
        button.type = 'button'; button.dataset.option = letter;
        button.className = 'option-btn text-left p-4 border border-slate-200 dark:border-slate-800 rounded-xl hover:bg-slate-50 dark:hover:bg-slate-800/50 transition font-medium text-sm text-slate-700 dark:text-slate-300';
        button.innerHTML = `<b class="mr-2">${letter}.</b>`;
        const optionContent = document.createElement('span'); optionContent.className = 'exam-rich-content';
        button.appendChild(optionContent);
        renderRichContent(optionContent, question[`option_${letter.toLowerCase()}`] || '');
        button.addEventListener('click', () => chooseAnswer(question, letter));
        options.appendChild(button);
      });
      card.append(passage, heading, text, diagram, options, feedback);
      byId('exam-arena').appendChild(card);

      const nav = document.createElement('button');
      nav.type = 'button'; nav.id = `nav-btn-${question.id}`; nav.textContent = String(index + 1);
      nav.setAttribute('aria-label', `Go to question ${index + 1}`);
      nav.className = 'h-9 w-9 border border-slate-200 dark:border-slate-800 rounded-lg text-xs font-bold hover:bg-slate-100 dark:hover:bg-slate-800 transition text-slate-600 dark:text-slate-400';
      nav.addEventListener('click', () => { currentIndex = index; renderCurrentQuestion(); });
      byId('question-nav-grid').appendChild(nav);
    });
  }

  async function chooseAnswer(question, letter) {
    if (finished) return;
    const qid = String(question.id);
    answers[qid] = letter;
    paintAnswer(question);
    const response = await saveState(question.id);
    if (!response.ok) return;
    if (mode === 'practice') {
      const feedback = byId(`feedback-${question.id}`);
      const correct = String(question.correct_answer || '').toUpperCase();
      feedback.classList.remove('hidden');
      feedback.innerHTML = `<b class="block ${letter === correct ? 'text-emerald-700' : 'text-rose-700'}">${letter === correct ? 'Correct' : 'Incorrect'} · Correct answer: ${safe(correct)}</b><div class="mt-2">${safe(question.explanation || 'No additional explanation was provided.')}</div>`;
      window.renderEduVaultMath?.(feedback);
    }
  }

  async function saveState(questionId) {
    try {
      const response = await fetch(`/api/exam-attempts/${attemptId}/answers/${questionId}`, {
        method:'PUT', headers:{'Content-Type':'application/json'},
        body:JSON.stringify({answer:answers[String(questionId)] || null, flagged:flags.has(String(questionId))})
      });
      if (!response.ok) {
        const data = await response.json();
        if (data.error) window.alert(data.error);
      }
      return response;
    } catch (error) {
      window.alert('Your answer could not be saved. Check your connection and try again.');
      return {ok:false};
    }
  }

  function paintAnswer(question) {
    document.querySelectorAll(`#options-box-${question.id} .option-btn`).forEach(button => {
      button.classList.toggle('ring-2', button.dataset.option === answers[String(question.id)]);
      button.classList.toggle('ring-blue-500', button.dataset.option === answers[String(question.id)]);
    });
  }

  function renderCurrentQuestion() {
    questions.forEach((question, index) => {
      const card = byId(`question-card-${question.id}`);
      card?.classList.toggle('hidden', index !== currentIndex);
      const nav = byId(`nav-btn-${question.id}`);
      nav?.classList.toggle('bg-blue-600', index === currentIndex);
      nav?.classList.toggle('text-white', index === currentIndex);
      nav?.classList.toggle('bg-emerald-100', index !== currentIndex && Boolean(answers[String(question.id)]));
      nav?.classList.toggle('border-amber-500', flags.has(String(question.id)));
      nav?.classList.toggle('border-dashed', flags.has(String(question.id)));
      paintAnswer(question);
    });
    byId('previous-question-btn').disabled = currentIndex === 0;
    byId('next-question-btn').classList.toggle('hidden', currentIndex === questions.length - 1);
    byId('submit-paper-btn').classList.toggle('hidden', currentIndex !== questions.length - 1);
    const question = questions[currentIndex];
    byId('flag-question-btn').textContent = flags.has(String(question.id)) ? 'Remove Review Flag' : 'Flag for Review';
  }

  function moveQuestion(delta) {
    currentIndex = Math.max(0, Math.min(questions.length - 1, currentIndex + delta));
    renderCurrentQuestion();
  }

  async function toggleFlag() {
    const id = String(questions[currentIndex].id);
    flags.has(id) ? flags.delete(id) : flags.add(id);
    renderCurrentQuestion();
    await saveState(questions[currentIndex].id);
  }

  function updateClock() {
    const minutes = Math.floor(timeLeft / 60);
    const seconds = timeLeft % 60;
    byId('exam-clock').textContent = `${String(minutes).padStart(2,'0')}:${String(seconds).padStart(2,'0')}`;
  }

  async function endExam(automatic = false) {
    if (finished || !attemptId) return;
    const answered = Object.keys(answers).length;
    const unanswered = questions.length - answered;
    const flagged = flags.size;
    if (!automatic && !window.confirm(`Submit this examination?\nAnswered: ${answered}\nUnanswered: ${unanswered}\nFlagged for review: ${flagged}\n\nYou cannot change answers after submission.`)) return;
    finished = true;
    window.clearInterval(timerId);
    document.querySelectorAll('.option-btn, #previous-question-btn, #next-question-btn, #flag-question-btn, #submit-paper-btn').forEach(button => button.disabled = true);
    try {
      const response = await fetch('/api/results/submit', {
        method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({attempt_id:attemptId})
      });
      const data = await response.json();
      if (!response.ok || !data.success) throw new Error(data.error || 'Submission failed.');
      window.location.href = `/result/${data.result_id}`;
    } catch (error) {
      finished = false;
      window.alert(error.message || 'Submission failed. Your saved answers are still on the server.');
    }
  }
  window.endExam = endExam;

  function renderRichContent(element, value) {
    if (!element) return;
    const raw = String(value || '');
    if (window.DOMPurify) element.innerHTML = DOMPurify.sanitize(raw, {USE_PROFILES:{html:true}, ADD_ATTR:['alt','title','loading']});
    else element.textContent = raw;
    window.renderEduVaultMath?.(element);
  }
})();
