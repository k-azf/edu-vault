/* Entrance month/week selection and schedule-controlled Mock exams. */
(() => {
  const EV5 = { selectionKey: 'ev_entrance_week_selection_v1' };
  const style = document.createElement('style');
  style.textContent = `
    .scheduleCoverage{white-space:pre-wrap;max-width:720px;color:#52627a;font-size:13px;line-height:1.5}
    .examStatePill{display:inline-block;border-radius:999px;padding:5px 10px;font-size:12px;font-weight:850}
    .examStatePill.open{background:#dcfce7;color:#166534}.examStatePill.locked{background:#fff7ed;color:#9a3412}.examStatePill.past{background:#eef2f7;color:#475569}
    .examLockMark{display:inline-flex;align-items:center;gap:6px}.examLockMark svg{width:14px;height:14px;flex:none;stroke:currentColor;fill:none;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
    .periodSelectors{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;max-width:600px}
    .mockPeriodSelectors{margin:14px 0}
    @media(max-width:560px){.periodSelectors{grid-template-columns:1fr}}
  `;
  document.head.append(style);

  const monthForWeek = week => Math.ceil(Number(week) / 4);
  const weeksForMonth = month => {
    const first = (Number(month) - 1) * 4 + 1;
    return Array.from({length:Math.max(0, Math.min(4, 31 - first))}, (_, index) => first + index).filter(week => week <= 30);
  };
  const examWeek = item => Number(item?.weekNumber || item?.exam?.weekNumber || 0);
  const examMonth = item => Number(item?.monthNumber || item?.exam?.monthNumber || monthForWeek(examWeek(item)) || 0);
  const examOpensAt = item => item?.opensAt || item?.exam?.opensAt || '';
  const cycleId = (month, week, year) => `entrance-y${Number(year) || new Date().getFullYear()}-m${Number(month)}-w${Number(week)}`;
  const formatDate = value => value ? new Date(value).toLocaleString() : 'Not set';
  const lockMark = label => `<span class="examLockMark"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="10" width="16" height="11" rx="2"></rect><path d="M8 10V7a4 4 0 0 1 8 0v3"></path></svg><span>${esc(label)}</span></span>`;
  const streamName = value => String(value || '').toLowerCase().includes('social') ? 'Social Science' : 'Natural Science';
  const streamSubjects = value => streamName(value) === 'Social Science' ? SOCIAL_EXAM_SUBJECTS : NATURAL_EXAM_SUBJECTS;
  const studentStream = () => streamName(student?.stream || 'Natural Science');
  const selectedMockPeriod = () => getSelection();
  const mockPeriodMatches = item => (!item.weekNumber || Number(item.weekNumber) === Number(selectedMockPeriod().week)) && (!item.monthNumber || Number(item.monthNumber) === Number(selectedMockPeriod().month));
  const etFormatDate = value => {
    if(!value)return 'Not set';
    const parts=Object.fromEntries(new Intl.DateTimeFormat('en-GB',{timeZone:'Africa/Addis_Ababa',year:'numeric',month:'short',day:'numeric',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(new Date(value)).map(part=>[part.type,part.value]));
    const clock=(Number(parts.hour)+18)%24,ampm=clock>=12?'PM':'AM',hour=clock%12||12;
    return `${parts.day} ${parts.month} ${parts.year}, ${hour}:${parts.minute} ${ampm} (Ethiopian)`;
  };
  function ethiopianDateTime(dateValue, hourValue, minuteValue, meridiem) {
    const [year,month,day]=dateValue.split('-').map(Number), hour=Number(hourValue)%12, civilHour=hour+6+(meridiem==='PM'?12:0);
    const utc=Date.UTC(year,month-1,day,civilHour-3,Number(minuteValue)||0);
    return new Date(utc).toISOString();
  }
  const currentStudentSubjects = () => Array.isArray(SUBJECTS) ? SUBJECTS : streamSubjects(studentStream());
  function periodControls(selected, prefix, handler) {
    const month=Math.min(8,Math.max(1,Number(selected.month)||1)), weeks=weeksForMonth(month),week=weeks.includes(Number(selected.week))?Number(selected.week):(weeks[0]||1);
    return `<div class="periodSelectors mockPeriodSelectors"><div class="field"><label>Month</label><select id="${prefix}Month" onchange="${handler}('month',this.value)">${Array.from({length:8},(_,i)=>`<option value="${i+1}" ${month===i+1?'selected':''}>Month ${i+1}</option>`).join('')}</select></div><div class="field"><label>Week</label><select id="${prefix}Week" onchange="${handler}('week',this.value)">${weeks.map(value=>`<option value="${value}" ${week===value?'selected':''}>Week ${value}</option>`).join('')}</select></div></div>`;
  }
  window.ev5SelectMockPeriod = (kind,value) => {const current=getSelection();if(kind==='month')setSelection(value,weeksForMonth(value)[0]||1,current.year);else setSelection(current.month,value,current.year);if(page==='mockExam')mockExamPage();else ev4ArchivePage();};

  function setSelection(month, week, year) {
    const selection = {month:Number(month) || 1, week:Number(week) || 1, year:Number(year) || new Date().getFullYear()};
    window.ev5SelectedEntrance = selection;
    localStorage.setItem(EV5.selectionKey, JSON.stringify(selection));
    return selection;
  }
  function getSelection() {
    if (window.ev5SelectedEntrance) return window.ev5SelectedEntrance;
    try {
      const saved = JSON.parse(localStorage.getItem(EV5.selectionKey) || 'null');
      if (saved?.month && saved?.week) return window.ev5SelectedEntrance = saved;
    } catch (error) {}
    return setSelection(1, 1, new Date().getFullYear());
  }
  function periodYear(month, week, archives) {
    const latest = archives.filter(item => item.type === 'entrance' && examWeek(item) === Number(week) && examMonth(item) === Number(month))
      .sort((a,b) => String(b.uploadedAt || '').localeCompare(String(a.uploadedAt || '')))[0];
    const date = examOpensAt(latest) || latest?.uploadedAt;
    return date ? new Date(date).getFullYear() : new Date().getFullYear();
  }
  function scheduleWindow(schedule) {
    const start = Date.parse(schedule?.dateTime || '');
    if (!Number.isFinite(start)) return {start:0,end:0,state:'locked'};
    const explicitEnd = Date.parse(schedule?.endDateTime || '');
    const duration = Number(schedule?.durationSeconds || schedule?.examDurationSeconds || 3600) * 1000;
    const end = Number.isFinite(explicitEnd) && explicitEnd > start ? explicitEnd : start + duration;
    const now = Date.now();
    return {start,end,state:now < start ? 'locked' : now <= end ? 'open' : 'past'};
  }
  function archiveForSchedule(schedule) {
    const archives = window.evArchivedExams || [];
    if (schedule.examVersionId) {
      const exact = archives.find(item => String(item.versionId || item.id) === String(schedule.examVersionId));
      if (exact) return exact;
    }
    return archives.filter(item => item.type === 'mock' && item.subject === schedule.subject)
      .sort((a,b) => String(b.uploadedAt || '').localeCompare(String(a.uploadedAt || '')))[0] || null;
  }

  weeklyExam = async function() {
    await Promise.all([ev4SyncArchive(), ev4SyncMyResults()]);
    const archives = (window.evArchivedExams || []).filter(item => item.type === 'entrance' && examWeek(item) >= 1 && examWeek(item) <= 30);
    const saved = getSelection(), month = Math.min(8, Math.max(1, Number(saved.month) || 1));
    const weeks = weeksForMonth(month), week = weeks.includes(Number(saved.week)) ? Number(saved.week) : (weeks[0] || 1);
    const year = periodYear(month, week, archives);
    setSelection(month, week, year);
    const latestBySubject = new Map();
    archives.filter(item => examWeek(item) === week && examMonth(item) === month).forEach(item => {
      const old = latestBySubject.get(item.subject);
      if (!old || String(item.uploadedAt || '') > String(old.uploadedAt || '')) latestBySubject.set(item.subject, item);
    });
    const selectedCycle = cycleId(month, week, year);
    const rows = SUBJECTS.map(subject => {
      const item = latestBySubject.get(subject), exam = item?.exam, opensAt = examOpensAt(item);
      const locked = Boolean(opensAt) && Date.now() < new Date(opensAt).getTime();
      const submitted = ev4ResultsFor(student.code).some(result => result.cycleId === selectedCycle && result.subject === subject);
      const status = submitted ? 'Submitted' : !item ? 'Not published' : locked ? `Locked until ${formatDate(opensAt)}` : 'Open';
      return `<div class="subject"><div><strong>${esc(subject)}</strong><div class="muted small">${esc(item?.title || exam?.title || 'No exam uploaded for this week')}${exam ? ` · ${exam.questions?.length || 0} questions` : ''}</div><div class="subjectSubmitted" style="color:${submitted ? '#059669' : locked ? '#b45309' : '#2563eb'}">${submitted ? 'Submitted' : locked ? lockMark(status) : status}</div></div><button class="primary" type="button" ${!item || locked || submitted ? 'disabled' : ''} onclick="ev5StartEntranceWeek('${esc(item?.versionId || item?.id || '')}')">${submitted ? 'Submitted' : locked ? lockMark('Locked') : 'Open'}</button></div>`;
    }).join('');
    document.getElementById('app').innerHTML = `<section class="hero"><h1>Entrance Examination</h1><p>Choose a month and week to view its six-subject examination. Individual scores stay hidden after each submission.</p></section>
      <div class="card"><div class="periodSelectors"><div class="field"><label for="entranceMonthSelect">Month</label><select id="entranceMonthSelect" onchange="ev5SelectEntranceMonth(this.value)">${Array.from({length:8},(_,i) => `<option value="${i+1}" ${month === i+1 ? 'selected' : ''}>Month ${i+1}</option>`).join('')}</select></div>
      <div class="field"><label for="entranceWeekSelect">Week</label><select id="entranceWeekSelect" onchange="ev5SelectEntranceWeek(this.value)">${weeks.map(value => `<option value="${value}" ${week === value ? 'selected' : ''}>Week ${value}</option>`).join('')}</select></div></div><p class="muted small">Weeks 1–4 are Month 1; Weeks 29–30 are Month 8.</p></div>
      <div class="card"><h2>Month ${month} · Week ${week}</h2>${rows}</div>`;
  };
  window.ev5SelectEntranceMonth = value => {const weeks = weeksForMonth(value);setSelection(value, weeks[0] || 1, periodYear(Number(value), weeks[0] || 1, window.evArchivedExams || []));weeklyExam();};
  window.ev5SelectEntranceWeek = value => {const current = getSelection();setSelection(current.month, value, periodYear(current.month, Number(value), window.evArchivedExams || []));weeklyExam();};

  window.ev5StartEntranceWeek = async versionId => {
    if (!student?.code || !student?.name) {toast('Please log in with your Examination ID and Name.');return;}
    await Promise.all([ev4SyncArchive(), ev4SyncMyResults()]);
    const item = (window.evArchivedExams || []).find(entry => String(entry.versionId || entry.id) === String(versionId));
    if (!item?.exam || item.type !== 'entrance') {toast('This Entrance exam is unavailable.');return;}
    const month = examMonth(item), week = examWeek(item), opensAt = examOpensAt(item);
    if (opensAt && Date.now() < new Date(opensAt).getTime()) {toast(`This exam is locked until ${formatDate(opensAt)}.`);return;}
    const year = opensAt ? new Date(opensAt).getFullYear() : periodYear(month, week, [item]);
    const selectedCycle = cycleId(month, week, year);
    if (ev4ResultsFor(student.code).some(result => result.cycleId === selectedCycle && result.subject === item.subject)) {toast('This subject has already been submitted for this week.');return;}
    const exam = normalizeExam(JSON.parse(JSON.stringify(item.exam)), 'entrance');
    exam.weekNumber = week;exam.monthNumber = month;exam.opensAt = opensAt;exam.title = item.title || exam.title;
    setSelection(month, week, year);
    examState = {subject:item.subject,e:exam,examType:'entrance',weekNumber:week,monthNumber:month,idx:0,answers:Array(exam.questions.length).fill(null),marked:[],left:exam.duration,start:Date.now(),startedAt:new Date().toISOString(),cycleId:selectedCycle,cyclePackageIds:{week,month,year}};
    renderQuestionV2();
  };

  weekly = async function() {
    const selection = getSelection(), selectedCycle = cycleId(selection.month, selection.week, selection.year);
    const mine = ev4ResultsFor(student.code).filter(result => result.cycleId === selectedCycle), bySubject = new Map();
    mine.forEach(result => {const old = bySubject.get(result.subject);if (!old || String(result.submittedAt || '') > String(old.submittedAt || '')) bySubject.set(result.subject,result);});
    if (!SUBJECTS.every(subject => bySubject.has(subject))) {toast('Submit all six subjects in this week before opening its final result.');page='weeklyExam';render();return;}
    const total = SUBJECTS.reduce((sum,subject) => sum + Number(bySubject.get(subject).score || 0),0),average = total / SUBJECTS.length;
    window.currentEntranceCycleId = selectedCycle;ev4MarkViewed(selectedCycle);
    document.getElementById('app').innerHTML = `<div class="finalResultWrap"><div class="finalResultCard" id="finalResultCard"><div class="finalResultHead"><div class="finalResultName">${esc(student.name || 'Student')}</div><div class="finalResultUni">ENTRANCE EXAM · MONTH ${selection.month} · WEEK ${selection.week}</div></div><div class="finalResultBody"><div class="finalInfoRow"><span class="finalInfoLabel">Examination ID</span><span class="finalInfoValue">${esc(student.code || '')}</span></div><div class="finalScoreGrid"><div class="finalScoreBox"><div class="finalScoreLabel">TOTAL / 600</div><div class="finalScoreValue">${total.toFixed(2)}</div></div><div class="finalScoreBox"><div class="finalScoreLabel">AVERAGE</div><div class="finalScoreValue">${average.toFixed(2)}</div></div></div>${SUBJECTS.map(subject => `<div class="finalSubjectRow"><span>${esc(subject)}</span><span>${Number(bySubject.get(subject).score || 0).toFixed(2)}%</span></div>`).join('')}</div></div><button class="downloadResultBtn" type="button" onclick="downloadFinalResult()">Download Result Image</button><button class="primary" style="width:100%;margin-top:10px" onclick="saveEntranceExplanationResource()">Save Explanation PDF to EduVault Resources</button><button class="secondary" style="width:100%;margin-top:10px" onclick="page='weeklyExam';render()">Back to Entrance Exam</button></div>`;
  };

  const queueCloudBeforePeriods = queueCloud;
  queueCloud = async function(result) {
    if (examState) {
      result.weekNumber = Number(examState.weekNumber || examState.e?.weekNumber) || 0;
      result.monthNumber = Number(examState.monthNumber || examState.e?.monthNumber) || 0;
      result.scheduleId = examState.scheduleId || '';
      result.examScheduleId = examState.scheduleId || '';
      result.cycleId = examState.cycleId || result.cycleId || '';
      result.sourceExamType = examState.practiceSourceType || result.sourceExamType || '';
      result.archiveVersionId = examState.archiveVersionId || result.archiveVersionId || '';
    }
    save(LS.results, results);
    return queueCloudBeforePeriods(result);
  };

  function mockSchedules() {return loadSchedules().filter(schedule => schedule.active !== false && schedule.type === 'mock').sort((a,b) => String(a.dateTime || '').localeCompare(String(b.dateTime || '')));}
  function pastScheduleForVersion(versionId) {return mockSchedules().find(schedule => String(schedule.examVersionId || '') === String(versionId || '') && scheduleWindow(schedule).state === 'past') || null;}

  mockExamPage = async function() {
    await Promise.all([ev4SyncMyResults(),syncSchedulesCloud(),ev4SyncArchive()]);
    const chosen=getSelection(), rows = mockSchedules().filter(schedule=>mockPeriodMatches(schedule)&&(!schedule.stream||streamName(schedule.stream)===studentStream())).map(schedule => {
      const window = scheduleWindow(schedule);if (window.state === 'past') return '';
      const archive = archiveForSchedule(schedule),exam = archive?.exam;
      const submitted = results.some(result => result.studentCode === student.code && String(result.scheduleId || result.examScheduleId || '') === String(schedule.id));
      const status = submitted ? 'Submitted' : !archive ? 'Exam file not available' : window.state === 'locked' ? `Locked until ${etFormatDate(schedule.dateTime)}` : 'Open';
      return `<div class="subject"><div><strong>${esc(schedule.title || archive?.title || schedule.subject)} · ${esc(schedule.subject)}</strong><div class="muted small">Month ${esc(schedule.monthNumber||Math.ceil((schedule.weekNumber||1)/4))} · Week ${esc(schedule.weekNumber||'—')} · ${esc(schedule.weekday||'')} · ${esc(schedule.grade || 'Grade not set')} · Opens ${etFormatDate(schedule.dateTime)} · Closes ${etFormatDate(schedule.endDateTime || new Date(window.end).toISOString())}</div>${schedule.coverage ? `<p class="scheduleCoverage">Coverage: ${esc(schedule.coverage)}</p>` : ''}<span class="examStatePill ${window.state}">${window.state==='locked'?lockMark(status):esc(status)}</span></div><button class="primary" ${!archive || window.state !== 'open' || submitted ? 'disabled' : ''} onclick="ev5StartScheduledMock('${esc(schedule.id)}')">${submitted ? 'Submitted' : window.state === 'open' ? 'Open' : lockMark('Locked')}</button></div>`;
    }).filter(Boolean).join('');
    document.getElementById('app').innerHTML = `<section class="hero"><h1>Mock Examination</h1><p>Mock exams open at their scheduled time. After the schedule closes, they move to Past Exams.</p></section><div class="card">${periodControls(chosen,'mock','ev5SelectMockPeriod')}<p class="muted small">Only the scheduled subject for today opens. Ethiopian clock times are shown.</p></div><div class="card">${rows || "<p class='muted'>No Mock exam is scheduled for this week and month.</p>"}</div>`;
  };

  window.ev5StartScheduledMock = async scheduleId => {
    if (!student?.code || !student?.name) {toast('Please log in with your Examination ID and Name.');return;}
    await Promise.all([syncSchedulesCloud(),ev4SyncArchive(),ev4SyncMyResults()]);
    const schedule = loadSchedules().find(item => String(item.id) === String(scheduleId));
    if (!schedule || schedule.type !== 'mock' || schedule.active === false || (schedule.stream&&streamName(schedule.stream)!==studentStream()) || scheduleWindow(schedule).state !== 'open') {toast('This Mock exam is locked outside its scheduled time or is assigned to another student stream.');return;}
    const archive = archiveForSchedule(schedule);if (!archive?.exam) {toast('The scheduled Mock exam file is unavailable.');return;}
    if (results.some(result => result.studentCode === student.code && String(result.scheduleId || result.examScheduleId || '') === String(schedule.id))) {toast('You have already submitted this scheduled Mock exam.');return;}
    const exam = normalizeExam(JSON.parse(JSON.stringify(archive.exam)), 'mock'),remaining = Math.max(1,Math.ceil((scheduleWindow(schedule).end - Date.now()) / 1000));
    exam.duration=remaining;
    exam.title = schedule.title || archive.title || exam.title;
    if (schedule.coverage) exam.instructions = `${exam.instructions || ''}\n\nScheduled exam coverage:\n${schedule.coverage}`.trim();
    examState = {subject:schedule.subject,e:exam,examType:'mock',scheduleId:schedule.id,weekNumber:schedule.weekNumber||0,monthNumber:schedule.monthNumber||0,idx:0,answers:Array(exam.questions.length).fill(null),marked:[],left:remaining,start:Date.now(),startedAt:new Date().toISOString(),cycleId:'',cyclePackageIds:{}};
    renderQuestionV2();
  };

  function addMockResultActions(result) {
    const wrap = document.querySelector('.mockResultWrap'),saveButton = document.getElementById('saveExplanationResource');
    if (wrap && saveButton && !document.getElementById('downloadMockResultImageButton')) {
      const button = document.createElement('button');button.id='downloadMockResultImageButton';button.className='downloadResultBtn';button.type='button';button.textContent='Download Result Image';button.onclick=()=>downloadMockResultImage();wrap.insertBefore(button,saveButton);
    }
    const back = wrap?.querySelector('button.secondary');
    if (back) back.onclick = () => {page = result?.archiveVersionId && result?.sourceExamType === 'mock' ? 'examArchive' : result?.examType === 'practice' ? 'generatedPractice' : 'mockExam';render();};
  }
  const showMockResultBeforePeriods = showMockResultV2;
  showMockResultV2 = function(result) {showMockResultBeforePeriods(result);addMockResultActions(result);};

  adminSchedulePage = function() {
    if (!window.EduVaultAccess?.requireAdmin()) return;
    const list = loadSchedules().sort(scheduleSort),subjects = ALL_EXAM_SUBJECTS.map(subject => `<option>${esc(subject)}</option>`).join('');
    document.getElementById('app').innerHTML = `<section class="hero"><h1>Exam Schedule Management</h1><p>Publish the weekly subject sequence, Ethiopian clock time, duration, and exam coverage.</p></section>
      <div class="card"><h2>Add Examination Schedule</h2><div class="grid"><div><div class="field"><label>Examination Type</label><select id="schType"><option value="mock">Mock Examination</option><option value="entrance">Entrance Examination</option></select></div><div class="field"><label>Student stream</label><select id="schStream" onchange="ev5UpdateScheduleSubjects()"><option>Natural Science</option><option>Social Science</option></select></div><div class="field"><label>Month</label><select id="schMonth" onchange="ev5UpdateScheduleWeeks()">${Array.from({length:8},(_,i)=>`<option value="${i+1}">Month ${i+1}</option>`).join('')}</select></div><div class="field"><label>Week</label><select id="schWeek">${weeksForMonth(1).map(w=>`<option value="${w}">Week ${w}</option>`).join('')}</select></div><div class="field"><label>Exam day</label><select id="schDay" onchange="ev5UpdateScheduleSubjects()">${DAYS.map((day,i)=>`<option value="${i}">${day}</option>`).join('')}</select></div><div class="field"><label>Subject</label><select id="schSubject">${subjects}</select></div><div class="field"><label>Grade</label><input id="schGrade" placeholder="e.g. Grade 11"></div></div><div><div class="field"><label>Calendar date for selected day</label><input id="schDate" type="date" required></div><div class="grid"><div class="field"><label>Ethiopian clock hour</label><select id="schHour">${Array.from({length:12},(_,i)=>`<option value="${i+1}" ${i===1?'selected':''}>${i+1}</option>`).join('')}</select></div><div class="field"><label>Minute</label><select id="schMinute">${['00','15','30','45'].map(m=>`<option value="${m}">${m}</option>`).join('')}</select></div><div class="field"><label>AM/PM</label><select id="schMeridiem"><option>PM</option><option>AM</option></select></div><div class="field"><label>Duration (hours)</label><input id="schDuration" type="number" min="1" max="12" value="3"></div></div><p class="muted small">Ethiopian 2:00 PM is 8:00 PM on a 24-hour clock. Default exam duration is 3 hours.</p><div class="field"><label>Exam location</label><input id="schLocation" placeholder="e.g. Ambo University Hall"></div></div></div><div class="field"><label>Exam coverage</label><textarea id="schCoverage" rows="4" placeholder="Enter units, chapters, topics, or other content covered by this exam"></textarea></div><button class="primary" onclick="saveExamScheduleAdmin()">Publish Schedule</button></div>
      <div class="card" style="margin-top:14px"><h2>Published Schedules</h2>${list.length ? list.map(schedule => `<article class="subject"><div><b>${esc(String(schedule.type || '').toUpperCase())} · ${esc(schedule.subject || '')}</b><div class="muted small">${esc(schedule.stream||'')} · Month ${esc(schedule.monthNumber||'—')} · Week ${esc(schedule.weekNumber||'—')} · ${esc(schedule.weekday||'')} · ${esc(schedule.grade || '')} · Opens ${etFormatDate(schedule.dateTime)} · Closes ${etFormatDate(schedule.endDateTime || '')}</div>${schedule.coverage ? `<p class="scheduleCoverage">${esc(schedule.coverage)}</p>` : ''}</div><button class="danger" onclick="deleteExamScheduleAdmin('${esc(schedule.id)}')">Delete</button></article>`).join('') : "<p class='muted'>No schedules have been published.</p>"}</div>`;
  };
  window.ev5UpdateScheduleSubjects=()=>{const stream=document.getElementById('schStream').value,index=Number(document.getElementById('schDay').value),subject=streamSubjects(stream)[index];document.getElementById('schSubject').innerHTML=streamSubjects(stream).map(value=>`<option ${value===subject?'selected':''}>${esc(value)}</option>`).join('');};
  window.ev5UpdateScheduleWeeks=()=>{const month=Number(document.getElementById('schMonth').value);document.getElementById('schWeek').innerHTML=weeksForMonth(month).map(week=>`<option value="${week}">Week ${week}</option>`).join('');};
  saveExamScheduleAdmin = async function() {
    const type=document.getElementById('schType').value,stream=document.getElementById('schStream').value,dayIndex=Number(document.getElementById('schDay').value),weekday=DAYS[dayIndex],subject=document.getElementById('schSubject').value,startDate=document.getElementById('schDate').value,weekNumber=Number(document.getElementById('schWeek').value),monthNumber=Number(document.getElementById('schMonth').value);
    if(!startDate){toast('Choose the calendar date for the exam day.');return;}
    const calendarDay=new Date(`${startDate}T12:00:00`).getDay();if(calendarDay!==(dayIndex+1)%7){toast(`Choose a ${weekday} date.`);return;}
    if(subject!==streamSubjects(stream)[dayIndex]){toast(`${weekday} is scheduled for ${streamSubjects(stream)[dayIndex]} in ${stream}.`);return;}
    const scheduleYear=Number(startDate.slice(0,4)),duplicate=loadSchedules().some(item=>item.active!==false&&item.type==='mock'&&Number(item.weekNumber)===weekNumber&&Number(item.monthNumber)===monthNumber&&Number(item.weekdayIndex)===dayIndex&&Number(item.scheduleYear||new Date(item.dateTime).getFullYear())===scheduleYear&&streamName(item.stream)===streamName(stream));if(type==='mock'&&duplicate){toast(`A ${stream} Mock exam is already scheduled for ${weekday}, Week ${weekNumber} in ${scheduleYear}.`);return;}
    const exam=getPackage(type,subject);if(type==='mock'&&!exam){toast(`Upload the ${subject} Mock exam package before scheduling it.`);return;}
    const start=new Date(ethiopianDateTime(startDate,document.getElementById('schHour').value,document.getElementById('schMinute').value,document.getElementById('schMeridiem').value)),hours=Math.max(1,Math.min(12,Number(document.getElementById('schDuration').value)||3)),end=new Date(start.getTime()+hours*3600000);
    const schedule={id:crypto.randomUUID?crypto.randomUUID():`schedule-${Date.now()}`,type,subject,stream,weekday,weekdayIndex:dayIndex,weekNumber,monthNumber,scheduleYear,grade:document.getElementById('schGrade').value.trim()||'Grade 11',dateTime:start.toISOString(),endDateTime:end.toISOString(),durationSeconds:hours*3600,examVersionId:String(exam?.versionId||exam?.id||''),title:exam?.title||`${subject} ${type}`,coverage:document.getElementById('schCoverage').value.trim(),location:document.getElementById('schLocation').value.trim()||'To be announced',active:true,updatedAt:new Date().toISOString()};
    const schedules=loadSchedules();schedules.push(schedule);saveSchedules(schedules.sort(scheduleSort));const synced=await publishScheduleCloud(schedule);toast(synced ? 'Schedule published and synced online' : 'Schedule saved locally; it will sync when online');adminSchedulePage();
  };
  deleteExamScheduleAdmin = async function(id) {if (!confirm('Delete this examination schedule?')) return;saveSchedules(loadSchedules().filter(schedule => String(schedule.id) !== String(id)));try {if (db && online && await ensureDatabaseReady()) await db.collection('examSchedules').doc(id).delete();} catch(error) {console.warn('Schedule delete sync failed',error);}adminSchedulePage();};
  examSchedulePage = async function() {
    await syncSchedulesCloud();const list=loadSchedules().filter(schedule=>schedule.active!==false).sort(scheduleSort);
    const rows=list.map(schedule=>{const status=scheduleWindow(schedule).state;return `<tr><td>${esc(String(schedule.type||'').toUpperCase())}</td><td>${esc(schedule.subject||'')}</td><td>${esc(schedule.stream||'')} · ${esc(schedule.grade||'')}</td><td>Month ${esc(schedule.monthNumber||'—')} · Week ${esc(schedule.weekNumber||'—')} · ${esc(schedule.weekday||'')}</td><td>${etFormatDate(schedule.dateTime)}</td><td>${etFormatDate(schedule.endDateTime||'')}</td><td>${esc(schedule.location||'')}</td><td>${schedule.coverage?`<div class="scheduleCoverage">${esc(schedule.coverage)}</div>`:'—'}</td><td><span class="examStatePill ${status}">${status==='locked'?lockMark('Locked'):status==='open'?'Open':'Past'}</span></td></tr>`;}).join('');
    document.getElementById('app').innerHTML=`<section class="hero"><h1>Exam Schedule</h1><p>See weekly subjects, Ethiopian clock times, locations, and exam coverage.</p></section><div class="card" style="overflow:auto"><table class="table"><tr><th>Type</th><th>Subject</th><th>Stream / grade</th><th>Period</th><th>Opens (Ethiopian time)</th><th>Closes</th><th>Location</th><th>Exam coverage</th><th>Status</th></tr>${rows || "<tr><td colspan='9' class='muted'>No examination schedule has been published yet.</td></tr>"}</table></div>`;
  };

  ev4ArchivePage = async function() {
    await Promise.all([syncSchedulesCloud(),ev4SyncArchive()]);
    const selected=getSelection(),past=mockSchedules().filter(schedule=>scheduleWindow(schedule).state==='past'&&mockPeriodMatches(schedule)&&(!schedule.stream||streamName(schedule.stream)===studentStream())).map(schedule=>({schedule,archive:archiveForSchedule(schedule)})).filter(row=>row.archive?.exam);
    document.getElementById('app').innerHTML=`<section class="hero"><h1>Past Mock Exams</h1><p>Choose a month and week to practice completed Mock exams at any time.</p></section><div class="card">${periodControls(selected,'past','ev5SelectMockPeriod')}</div><div class="card">${past.length ? past.map(({schedule,archive})=>`<article class="subject"><div><strong>${esc(schedule.title||archive.title||schedule.subject)}</strong><div class="muted small">${esc(schedule.subject)} · ${esc(schedule.stream||studentStream())} · Month ${esc(schedule.monthNumber||'—')} · Week ${esc(schedule.weekNumber||'—')} · ${esc(schedule.weekday||'')} · Closed ${etFormatDate(schedule.endDateTime)}</div>${schedule.coverage?`<p class="scheduleCoverage">Coverage: ${esc(schedule.coverage)}</p>`:''}</div><button class="primary" onclick="ev4StartArchived('${esc(schedule.id)}')">Practice past exam</button></article>`).join('') : "<p class='muted'>No scheduled Mock exams have ended for this week.</p>"}</div>`;
  };
  ev4StartArchived = async function(scheduleId) {
    if (!student?.code || !student?.name) {toast('Please log in with your Examination ID and Name.');return;}
    await Promise.all([syncSchedulesCloud(),ev4SyncArchive()]);
    const schedule=loadSchedules().find(item=>String(item.id)===String(scheduleId));
    if (!schedule || schedule.type!=='mock' || (schedule.stream&&streamName(schedule.stream)!==studentStream()) || scheduleWindow(schedule).state!=='past') {toast('This exam appears under Past Exams after its scheduled closing time for your stream.');return;}
    const archive=archiveForSchedule(schedule);if (!archive?.exam) {toast('The past Mock exam file is unavailable.');return;}
    const exam=normalizeExam(JSON.parse(JSON.stringify(archive.exam)),'practice');exam.title=schedule.title||archive.title||exam.title;
    if (schedule.coverage) exam.instructions=`${exam.instructions||''}\n\nScheduled exam coverage:\n${schedule.coverage}`.trim();
    examState={subject:schedule.subject,e:exam,examType:'practice',practiceSourceType:'mock',archiveVersionId:archive.versionId||archive.id,scheduleId:schedule.id,idx:0,answers:Array(exam.questions.length).fill(null),marked:[],left:exam.duration,start:Date.now(),startedAt:new Date().toISOString(),cycleId:'',cyclePackageIds:{}};
    renderQuestionV2();
  };
  setTimeout(()=>{if(page==='admin')adminExamFiles();},0);
})();
</script></body>
