(() => {
  const csrf = document.querySelector('meta[name="csrf-token"]').content;
  const root = document.getElementById('toast-root');
  const views = ['overview', 'teams', 'qrs', 'questions', 'rounds', 'monitoring', 'scores', 'leaderboard', 'results', 'activity', 'settings'];
  const titles = {overview:'Dashboard',teams:'Teams',qrs:'QR Management',questions:'Questions',rounds:'Round Control',monitoring:'Live Monitoring',scores:'Scores',leaderboard:'Leaderboard',results:'Final Results',activity:'Activity Logs',settings:'Settings'};
  let chart;

  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const date = value => value ? new Date(value).toLocaleString([], {hour:'2-digit',minute:'2-digit',second:'2-digit',month:'short',day:'numeric'}) : '—';
  const clock = value => {
    const seconds = Math.max(0, Number(value) || 0);
    return `${Math.floor(seconds / 3600) ? `${String(Math.floor(seconds / 3600)).padStart(2,'0')}:` : ''}${String(Math.floor(seconds / 60) % 60).padStart(2,'0')}:${String(seconds % 60).padStart(2,'0')}`;
  };
  const status = value => `<span class="badge ${esc(String(value).toLowerCase())}">${esc(value)}</span>`;
  const toast = (message, error=false) => {
    const node = document.createElement('div'); node.className = `toast${error ? ' error' : ''}`; node.textContent = message; root.append(node); setTimeout(() => node.remove(), 4000);
  };
  async function api(path, options={}) {
    const response = await fetch(path, {credentials:'same-origin', ...options, headers:{'Content-Type':'application/json','X-CSRFToken':csrf,...(options.headers || {})}});
    const data = response.status === 204 ? {} : await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
    return data;
  }
  function modal(title, body, onOpen) {
    const host = document.getElementById('modal-root');
    host.innerHTML = `<div class="modal-backdrop"><div class="modal" role="dialog" aria-modal="true"><div class="modal-head"><h3>${esc(title)}</h3><button class="modal-close" aria-label="Close">×</button></div><div class="modal-content">${body}</div></div></div>`;
    host.querySelector('.modal-close').onclick = () => host.innerHTML = '';
    host.querySelector('.modal-backdrop').addEventListener('click', event => { if (event.target.classList.contains('modal-backdrop')) host.innerHTML = ''; });
    onOpen?.(host);
  }
  function showView(name) {
    if (!views.includes(name)) return;
    document.querySelectorAll('.view').forEach(view => view.classList.toggle('active', view.id === `view-${name}`));
    document.querySelectorAll('.nav-item').forEach(item => item.classList.toggle('active', item.dataset.view === name));
    document.getElementById('page-title').textContent = titles[name];
    document.getElementById('sidebar').classList.remove('open');
    if (name === 'overview') loadOverview();
    if (name === 'teams') loadTeams();
    if (name === 'qrs') loadQrs();
    if (name === 'questions') loadQuestions();
    if (name === 'rounds') loadRounds();
    if (name === 'monitoring') loadMonitoring();
    if (name === 'scores') loadScores();
    if (name === 'leaderboard') loadLeaderboard();
    if (name === 'results') loadResults();
    if (name === 'activity') loadActivity();
  }
  document.querySelectorAll('.nav-item').forEach(item => item.addEventListener('click', () => showView(item.dataset.view)));
  document.querySelectorAll('[data-goto]').forEach(item => item.addEventListener('click', () => showView(item.dataset.goto)));
  document.getElementById('menu-toggle').onclick = () => document.getElementById('sidebar').classList.toggle('open');
  function drawLeaderboard(rows, target, includeStatus=true) {
    const body = document.getElementById(target);
    if (!body) return;
    body.innerHTML = rows.length ? rows.map((row,index) => `<tr><td><span class="rank-num ${index===0?'top':''}">${index+1}</span></td><td>${esc(row.team_id)}</td><td class="team-cell">${esc(row.team_name)}</td><td>R${row.round || '—'}</td><td><b>${row.score}</b></td><td>${clock(row.time)}</td>${includeStatus?`<td>${status(row.status)}</td>`:''}</tr>`).join('') : `<tr><td colspan="${includeStatus?7:6}" class="empty-cell">No teams have scored yet.</td></tr>`;
  }
  async function loadOverview() {
    try {
      const data = await api('/api/overview');
      document.getElementById('stat-teams').textContent = data.total_teams;
      document.getElementById('stat-active').textContent = data.active_teams;
      document.getElementById('stat-completed').textContent = data.completed_teams;
      document.getElementById('stat-scans').textContent = data.total_scans;
      document.getElementById('current-round').textContent = data.current_round;
      document.getElementById('rounds-done').textContent = `${data.completed_rounds} / 3 complete`;
      document.getElementById('overview-rounds').innerHTML = data.rounds.map(round => `<div class="round-row ${round.status==='ACTIVE'?'active':''}"><span class="round-number">0${round.number}</span><div><strong>${esc(round.name)}</strong><small>${status(round.status)}</small></div></div>`).join('');
      document.getElementById('overview-activity').innerHTML = data.activity.length ? data.activity.map(item => `<div class="activity-item"><time>${date(item.timestamp)}</time><span>${esc(item.action)} · ${esc(item.target)}</span></div>`).join('') : '<div class="empty-state">No activity recorded yet.</div>';
      const rows = data.leaderboard || [];
      document.getElementById('overview-leaderboard').innerHTML = rows.length ? rows.slice(0,6).map((row,index) => `<tr><td><span class="rank-num ${index===0?'top':''}">${index+1}</span></td><td><span class="team-cell">${esc(row.team_name)}</span><small style="display:block;color:#929bae;margin-top:3px">${esc(row.team_id)}</small></td><td>R${row.round || '—'}</td><td><b>${row.score}</b></td><td>${clock(row.time)}</td></tr>`).join('') : '<tr><td colspan="5" class="empty-cell">No teams yet</td></tr>';
      const ctx = document.getElementById('score-chart');
      const labels = data.rounds.map(round => `Round ${round.number}`);
      const scores = data.rounds.map(round => data.round_scores[String(round.number)] || 0);
      if (window.Chart && ctx) {
        if (chart) chart.destroy();
        chart = new Chart(ctx, {type:'bar',data:{labels,datasets:[{data:scores,backgroundColor:['#3768eb','#7954d9','#19a7bb'],borderRadius:5,maxBarThickness:34}]},options:{plugins:{legend:{display:false}},scales:{x:{grid:{display:false},ticks:{color:'#8993a7',font:{size:10}}},y:{beginAtZero:true,grid:{color:'#eef0f5'},ticks:{color:'#8993a7',font:{size:9}}}}}});
      }
    } catch (error) { toast(error.message, true); }
  }
  let teamsCache = [];
  async function loadTeams() {
    try {
      teamsCache = await api('/api/teams');
      const term = document.getElementById('team-search').value.toLowerCase();
      const rows = teamsCache.filter(team => `${team.team_id} ${team.team_name}`.toLowerCase().includes(term));
      document.getElementById('team-count').textContent = `${rows.length} teams`;
      document.getElementById('teams-table').innerHTML = rows.length ? rows.map(team => `<tr><td class="team-cell">${esc(team.team_id)}</td><td>${esc(team.team_name)}</td><td>${[team.member_1,team.member_2,team.member_3].filter(Boolean).map(esc).join(', ') || '—'}</td><td><b>${team.score}</b></td><td><select class="status-select" data-team-status="${team.id}">${['READY','ACTIVE','COMPLETED','DISQUALIFIED','DISABLED'].map(value=>`<option ${team.status===value?'selected':''}>${value}</option>`).join('')}</select></td><td><div class="row-actions"><button class="text-button" data-edit-team="${team.id}">Edit</button><button class="text-button" data-timeline="${team.id}">Timeline</button><button class="text-button" data-reset-pin="${team.id}">Reset PIN</button><button class="text-button danger-text" data-delete-team="${team.id}">Delete</button></div></td></tr>`).join('') : '<tr><td colspan="6" class="empty-cell">No teams match this search.</td></tr>';
      document.getElementById('judge-team').innerHTML = teamsCache.map(team => `<option value="${team.id}">${esc(team.team_id)} · ${esc(team.team_name)}</option>`).join('');
      bindTeamActions();
    } catch (error) { toast(error.message, true); }
  }
  document.getElementById('team-search').addEventListener('input', loadTeams);
  function teamForm(team={}) {
    modal(team.id ? `Edit ${team.team_id}` : 'Add team', `<form id="team-form" class="form-panel"><label>Team name<input name="team_name" required maxlength="120" value="${esc(team.team_name||'')}"></label><div class="form-grid two"><label>Member 1<input name="member_1" maxlength="100" value="${esc(team.member_1||'')}"></label><label>Member 2<input name="member_2" maxlength="100" value="${esc(team.member_2||'')}"></label></div><label>Member 3<input name="member_3" maxlength="100" value="${esc(team.member_3||'')}"></label>${team.id?'':'<label>Login PIN · optional, generated if blank<input name="login_pin" inputmode="numeric" minlength="4" maxlength="12"></label>'}<button class="button primary" type="submit">${team.id?'Save changes':'Create team'}</button></form>`, host => {
      host.querySelector('#team-form').onsubmit = async event => {
        event.preventDefault(); const form = Object.fromEntries(new FormData(event.currentTarget));
        try { const data = await api(team.id ? `/api/teams/${team.id}` : '/api/teams', {method:team.id?'PUT':'POST',body:JSON.stringify(form)}); host.innerHTML=''; toast(team.id?'Team updated':`Created ${data.team.team_id} · PIN ${data.login_pin}`); loadTeams(); }
        catch(error) { toast(error.message,true); }
      };
    });
  }
  document.getElementById('add-team').onclick = () => teamForm();
  function bindTeamActions() {
    document.querySelectorAll('[data-edit-team]').forEach(button => button.onclick = () => teamForm(teamsCache.find(team => team.id === Number(button.dataset.editTeam))));
    document.querySelectorAll('[data-delete-team]').forEach(button => button.onclick = async () => { if(!confirm('Delete this team and its activity records?'))return; try{await api(`/api/teams/${button.dataset.deleteTeam}`,{method:'DELETE'});toast('Team deleted');loadTeams();}catch(error){toast(error.message,true);} });
    document.querySelectorAll('[data-reset-pin]').forEach(button => button.onclick = async () => { try{const data=await api(`/api/teams/${button.dataset.resetPin}/reset-pin`,{method:'POST',body:'{}'});modal('New team PIN',`<p>Share this one-time display with the team:</p><p><strong>${esc(data.team_id)} · ${esc(data.login_pin)}</strong></p>`);}catch(error){toast(error.message,true);} });
    document.querySelectorAll('[data-timeline]').forEach(button => button.onclick = async () => { try{const data=await api(`/api/teams/${button.dataset.timeline}/timeline`);modal(`${data.team.team_id} · Timeline`,data.timeline.length?`<ul class="timeline">${data.timeline.map(item=>`<li><time>${date(item.at)}</time>${esc(item.label)}</li>`).join('')}</ul>`:'<div class="empty-state">No events recorded for this team.</div>');}catch(error){toast(error.message,true);} });
    document.querySelectorAll('[data-team-status]').forEach(select => select.onchange = async () => {try{await api(`/api/teams/${select.dataset.teamStatus}`,{method:'PUT',body:JSON.stringify({status:select.value})});toast('Team status updated');loadTeams();}catch(error){toast(error.message,true);loadTeams();}});
  }
  async function loadQrs() {
    try {
      const rows = await api('/api/qrs');
      document.getElementById('qrs-table').innerHTML = rows.length ? rows.map(qr => `<tr><td class="team-cell">${esc(qr.qr_id)}</td><td>R${qr.round} · ${esc(qr.round_name)}</td><td>${esc(qr.room || 'Unassigned')}</td><td>${status(qr.status)}</td><td>${date(qr.created_at)}</td><td>${date(qr.activated_at)}</td><td>${qr.scans}</td><td><div class="row-actions"><button class="text-button" data-qr-image="${qr.id}">Download</button><button class="text-button" data-qr-scans="${qr.id}">Scans</button><button class="text-button" data-qr-action="${qr.status==='ACTIVE'?'deactivate':'activate'}" data-qr-id="${qr.id}">${qr.status==='ACTIVE'?'Deactivate':'Activate'}</button><button class="text-button danger-text" data-qr-action="delete" data-qr-id="${qr.id}">Delete</button></div></td></tr>`).join('') : '<tr><td colspan="8" class="empty-cell">Generate your first QR challenge.</td></tr>';
      document.querySelectorAll('[data-qr-action]').forEach(button => button.onclick = async () => {try{await api(`/api/qrs/${button.dataset.qrId}/${button.dataset.qrAction}`,{method:'POST',body:'{}'});toast(`QR ${button.dataset.qrAction}d`);loadQrs();}catch(error){toast(error.message,true);}});
      document.querySelectorAll('[data-qr-image]').forEach(button => button.onclick = () => {const image=`/api/qrs/${button.dataset.qrImage}/image`;modal('QR challenge',`<img class="qr-preview" src="${image}" alt="QR challenge"><p class="subtle">This QR contains an opaque secure token. Correct answers are never encoded in the image.</p><a class="button primary" href="${image}" download>Download PNG</a>`);});
      document.querySelectorAll('[data-qr-scans]').forEach(button => button.onclick = async () => {try{const scans=await api(`/api/qrs/${button.dataset.qrScans}/scans`);modal('QR scan history',scans.length?`<div class="table-wrap"><table><thead><tr><th>Team</th><th>Scan time</th><th>Answer time</th><th>Status</th><th>Points</th></tr></thead><tbody>${scans.map(scan=>`<tr><td>${esc(scan.team_id)} · ${esc(scan.team_name)}</td><td>${date(scan.scan_time)}</td><td>${date(scan.answer_time)}</td><td>${status(scan.answer_status)}</td><td>${scan.points}</td></tr>`).join('')}</tbody></table></div>`:'<div class="empty-state">No scans recorded for this QR.</div>');}catch(error){toast(error.message,true);}});
    } catch (error) { toast(error.message,true); }
  }
  document.getElementById('add-qr').onclick = () => modal('Generate QR challenge',`<form id="qr-form" class="form-panel"><label>Round<select name="round_id"><option value="1">Round 1 · QR Riddle</option><option value="2">Round 2 · Quiz</option><option value="3">Round 3 · Pen & Paper</option></select></label><label>Room<input name="room" maxlength="120" placeholder="Room or location"></label><label>Question / clue<select name="question_id"><option value="">No attached clue</option></select></label><label>Expires at · optional<input name="expires_at" type="datetime-local"></label><p class="subtle">QR data is a unique random token; no answer is embedded.</p><button class="button primary" type="submit">Generate QR</button></form>`,async host=>{try{const questions=await api('/api/admin/questions');host.querySelector('[name=question_id]').innerHTML='<option value="">No attached clue</option>'+questions.map(q=>`<option value="${q.id}">R${q.round} · ${esc(q.prompt.slice(0,75))}</option>`).join('');}catch{} host.querySelector('#qr-form').onsubmit=async event=>{event.preventDefault();try{const payload=Object.fromEntries(new FormData(event.currentTarget));if(payload.expires_at)payload.expires_at=new Date(payload.expires_at).toISOString();const data=await api('/api/qrs',{method:'POST',body:JSON.stringify(payload)});host.innerHTML='';showView('qrs');setTimeout(()=>{document.querySelector(`[data-qr-image="${data.qr.id}"]`)?.click();},150);toast(`${data.qr.qr_id} generated`);}catch(error){toast(error.message,true);}};});
  async function loadQuestions() {
    try {
      const rows = await api('/api/admin/questions');
      document.getElementById('questions-list').innerHTML = rows.length ? rows.map(q => `<div class="question-row"><strong>R${q.round} · ${esc(q.prompt)}</strong><small>${q.points} pts · ${q.time_limit}s · key ${q.correct_answer} <button class="text-button" data-question-edit="${q.id}">Edit</button> <button class="text-button" data-question-toggle="${q.id}" data-active="${q.active}">${q.active?'Deactivate':'Activate'}</button> <button class="text-button danger-text" data-question-delete="${q.id}">Delete</button></small></div>`).join('') : '<div class="empty-state">No questions added yet.</div>';
      document.querySelectorAll('[data-question-edit]').forEach(button => button.onclick = () => {
        const question = rows.find(item => item.id === Number(button.dataset.questionEdit));
        modal('Edit question', `<form id="edit-question" class="form-panel"><label>Question<textarea name="prompt" maxlength="2000" required rows="3">${esc(question.prompt)}</textarea></label><div class="form-grid two">${['a','b','c','d'].map(key => `<label>Option ${key.toUpperCase()}<input name="option_${key}" value="${esc(question[`option_${key}`])}" maxlength="300"></label>`).join('')}</div><div class="form-grid two"><label>Correct answer / key<input name="correct_answer" maxlength="300" required value="${esc(question.correct_answer)}"></label><label>Points<input name="points" type="number" min="0" max="10000" value="${question.points}"></label><label>Time limit · seconds<input name="time_limit" type="number" min="5" max="3600" value="${question.time_limit}"></label></div><button class="button primary" type="submit">Save changes</button></form>`, host => {
          host.querySelector('#edit-question').onsubmit = async event => {
            event.preventDefault();
            try { await api(`/api/admin/questions/${question.id}`, {method:'PATCH',body:JSON.stringify(Object.fromEntries(new FormData(event.currentTarget)))}); host.innerHTML=''; toast('Question updated'); loadQuestions(); }
            catch(error) { toast(error.message,true); }
          };
        });
      });
      document.querySelectorAll('[data-question-toggle]').forEach(button=>button.onclick=async()=>{try{await api(`/api/admin/questions/${button.dataset.questionToggle}`,{method:'PATCH',body:JSON.stringify({active:button.dataset.active!=='true'})});loadQuestions();}catch(error){toast(error.message,true);}});
      document.querySelectorAll('[data-question-delete]').forEach(button=>button.onclick=async()=>{if(!confirm('Delete this question?'))return;try{await api(`/api/admin/questions/${button.dataset.questionDelete}`,{method:'DELETE'});loadQuestions();}catch(error){toast(error.message,true);}});
    }
    catch(error){toast(error.message,true);}
  }
  document.getElementById('question-form').onsubmit=async event=>{event.preventDefault();const data=Object.fromEntries(new FormData(event.currentTarget));try{await api('/api/admin/questions',{method:'POST',body:JSON.stringify(data)});event.currentTarget.reset();toast('Question saved');loadQuestions();}catch(error){toast(error.message,true);}};
  async function loadRounds(){try{const rounds=await api('/api/rounds');document.getElementById('round-control-list').innerHTML=rounds.map(round=>`<article class="round-control-card"><span class="round-number">0${round.number}</span><h3>${esc(round.name)}</h3><p>${status(round.status)}${round.started_at?` · Started ${date(round.started_at)}`:''}</p><div class="round-actions">${round.status==='LOCKED'?`<button class="button secondary" data-round-action="unlock" data-round-id="${round.id}">Unlock</button>`:''}${round.status==='READY'?`<button class="button primary" data-round-action="start" data-round-id="${round.id}">Start round</button>`:''}${round.status==='ACTIVE'?`<button class="button secondary" data-round-action="pause" data-round-id="${round.id}">Pause</button><button class="button primary" data-round-action="end" data-round-id="${round.id}">End round</button>`:''}</div></article>`).join('');document.querySelectorAll('[data-round-action]').forEach(button=>button.onclick=async()=>{try{await api(`/api/rounds/${button.dataset.roundId}/${button.dataset.roundAction}`,{method:'POST',body:'{}'});toast(`Round ${button.dataset.roundAction}d`);loadRounds();loadOverview();}catch(error){toast(error.message,true);}});}catch(error){toast(error.message,true);}}
  async function loadMonitoring(){try{const rows=await api('/api/admin/monitoring');const filter=document.getElementById('monitor-filter').value;const filtered=rows.filter(row=>filter==='all'||(filter==='active'?row.status==='ACTIVE':filter==='completed'?row.status==='COMPLETED':row.round===Number(filter)));document.getElementById('monitor-table').innerHTML=filtered.length?filtered.map(row=>`<tr><td><b>${esc(row.team_id)}</b><small style="display:block;margin-top:3px;color:#929bae">${esc(row.team_name)}</small></td><td>${row.round?`R${row.round}`:'—'}</td><td>${esc(row.current_qr)}</td><td>${date(row.last_scan)}</td><td><b>${row.score}</b></td><td>${date(row.round_start)}</td><td>${date(row.last_activity)}</td><td>${status(row.status)}</td></tr>`).join(''):'<tr><td colspan="8" class="empty-cell">No teams match this filter.</td></tr>';}catch(error){toast(error.message,true);}}
  document.getElementById('monitor-filter').onchange=loadMonitoring;
  async function loadScores(){try{const rows=await api('/api/admin/scores');document.getElementById('scores-table').innerHTML=rows.length?rows.map(row=>`<tr><td>${esc(row.team_id)}</td><td>${esc(row.team_name)}</td><td>Round ${row.round}</td><td><b>${row.points}</b></td><td>${date(row.updated_at)}</td></tr>`).join(''):'<tr><td colspan="5" class="empty-cell">No scores have been recorded.</td></tr>';loadTeams();}catch(error){toast(error.message,true);}}
  document.getElementById('judge-form').onsubmit=async event=>{event.preventDefault();const data=Object.fromEntries(new FormData(event.currentTarget));try{await api('/api/admin/round-three/score',{method:'POST',body:JSON.stringify(data)});toast('Round 3 score saved');loadScores();}catch(error){toast(error.message,true);}};
  async function loadLeaderboard(){try{const rows=await api('/api/leaderboard');drawLeaderboard(rows,'leaderboard-table');document.getElementById('podium').innerHTML=rows.slice(0,3).map((row,index)=>`<div class="podium-card"><span class="podium-rank">${['1st place','2nd place','3rd place'][index]}</span><strong>${esc(row.team_name)}</strong><small>${esc(row.team_id)} · ${row.score} points · ${clock(row.time)}</small></div>`).join('');}catch(error){toast(error.message,true);}}
  async function loadResults(){try{const rows=await api('/api/results');document.getElementById('results-table').innerHTML=rows.length?rows.map(row=>`<tr><td><span class="rank-num ${row.rank===1?'top':''}">${row.rank}</span></td><td><b>${esc(row.team_id)}</b> · ${esc(row.team_name)}</td><td>${row.score}</td><td>${clock(row.time)}</td><td>${date(row.completed_at)}</td><td>${row.locked?'LOCKED':'Editable'}</td></tr>`).join(''):'<tr><td colspan="6" class="empty-cell">Results have not been generated.</td></tr>';document.getElementById('results-podium').innerHTML=rows.slice(0,3).map((row,index)=>`<div class="podium-card"><span class="podium-rank">${['1st place','2nd place','3rd place'][index]}</span><strong>${esc(row.team_name)}</strong><small>${row.score} pts · ${clock(row.time)}</small></div>`).join('');}catch(error){toast(error.message,true);}}
  document.getElementById('generate-results').onclick=async()=>{if(!confirm('Generate the final ranking from current server-side scores?'))return;try{await api('/api/results/generate',{method:'POST',body:'{}'});toast('Final results generated');loadResults();}catch(error){toast(error.message,true);}};
  document.getElementById('lock-results').onclick=async()=>{if(!confirm('Lock final results? Only a super-admin can unlock them.'))return;try{await api('/api/results/lock',{method:'POST',body:'{}'});toast('Final results locked');loadResults();}catch(error){toast(error.message,true);}};
  async function loadActivity(){try{const rows=await api('/api/admin/activity');document.getElementById('activity-table').innerHTML=rows.length?rows.map(row=>`<tr><td>${date(row.timestamp)}</td><td><b>${esc(row.action)}</b></td><td>${esc(row.target)}</td><td class="activity-table-cell">${esc(JSON.stringify(row.metadata||{}))}</td></tr>`).join(''):'<tr><td colspan="4" class="empty-cell">No audit events yet.</td></tr>';}catch(error){toast(error.message,true);}}
  const updateClock=()=>document.getElementById('clock').textContent=new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'});
  updateClock();setInterval(updateClock,1000);loadOverview();
  if(window.io){const socket=io();socket.emit('join_admin');socket.emit('join_participant');socket.on('activity',item=>{toast(item.message);if(document.getElementById('view-activity').classList.contains('active'))loadActivity();if(document.getElementById('view-overview').classList.contains('active'))loadOverview();if(document.getElementById('view-monitoring').classList.contains('active'))loadMonitoring();});socket.on('leaderboard',()=>{if(document.getElementById('view-leaderboard').classList.contains('active'))loadLeaderboard();if(document.getElementById('view-overview').classList.contains('active'))loadOverview();});}
  setInterval(()=>{if(document.getElementById('view-monitoring').classList.contains('active'))loadMonitoring();},15000);
})();