(() => {
  const csrf = document.querySelector('meta[name="csrf-token"]').content;
  const toastRoot = document.getElementById('toast-root');
  let summary, elapsedTimer, cameraControls, activeQuiz, quizInterval;
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const toast = (message,error=false) => {const node=document.createElement('div');node.className=`toast${error?' error':''}`;node.textContent=message;toastRoot.append(node);setTimeout(()=>node.remove(),4000);};
  async function api(path,options={}) {
    const response=await fetch(path,{credentials:'same-origin',...options,headers:{'Content-Type':'application/json','X-CSRFToken':csrf,...(options.headers||{})}});
    const data=await response.json().catch(()=>({}));if(!response.ok)throw new Error(data.error||`Request failed (${response.status})`);return data;
  }
  const duration=seconds=>`${String(Math.floor(seconds/60)).padStart(2,'0')}:${String(seconds%60).padStart(2,'0')}`;
  async function refresh() {
    try {
      summary=await api('/api/team/dashboard');
      document.getElementById('team-name').textContent=summary.team.team_name;
      document.getElementById('team-id').textContent=`${summary.team.team_id} · ${[summary.team.member_1,summary.team.member_2,summary.team.member_3].filter(Boolean).join(' · ')}`;
      document.getElementById('team-status').textContent=summary.team.status;
      document.getElementById('team-score').textContent=summary.score;
      document.getElementById('team-round').textContent=summary.current_round;
      document.getElementById('team-round-status').textContent=summary.round_status;
      const active=summary.round_status==='ACTIVE'&&summary.round_id;
      document.getElementById('action-heading').textContent=active?`Round ${summary.round_number} is live.`:summary.team.status==='COMPLETED'?'Quest complete.':'Ready when you are.';
      document.getElementById('action-copy').textContent=active?'Start your round timer, scan active QR clues, and submit answers here.':'Your event administrator controls when the next round opens.';
      document.getElementById('start-round').hidden=!active||summary.session_active;
      document.getElementById('scan-open').hidden=!(active&&summary.round_number===1&&summary.session_active);
      document.getElementById('manual-scan').hidden=!(active&&summary.round_number===1&&summary.session_active);
      document.getElementById('quiz-next').hidden=!(active&&summary.round_number===2&&summary.session_active);
      document.getElementById('complete-round').hidden=!(active&&summary.session_active);
      if(elapsedTimer)clearInterval(elapsedTimer);
      const elapsed=document.getElementById('team-elapsed');
      const updateElapsed=()=>elapsed.textContent=summary.round_started_at?duration(Math.floor((Date.now()-new Date(summary.round_started_at).getTime())/1000)):'00:00';
      updateElapsed();elapsedTimer=setInterval(updateElapsed,1000);
      const rounds=await api('/api/team/rounds');
      document.getElementById('team-round-track').innerHTML=rounds.map(round=>`<div class="team-round-step ${round.status==='ACTIVE'?'active':round.status==='COMPLETED'?'done':''}"><strong>0${round.number} · ${esc(round.name)}</strong><small>${esc(round.status)}</small></div>`).join('');
      await refreshLeaderboard();
    } catch(error) {toast(error.message,true);}
  }
  async function refreshLeaderboard(){try{const rows=await api('/api/leaderboard');document.getElementById('team-leaderboard').innerHTML=rows.length?rows.slice(0,10).map((row,index)=>`<div class="team-rank"><span class="rank-num ${index===0?'top':''}">${index+1}</span><div><strong>${esc(row.team_name)}</strong><small>${esc(row.team_id)} · R${row.round||'—'}</small></div><b>${row.score}</b></div>`).join(''):'<div class="empty-state">Scores will appear here.</div>';}catch(error){toast(error.message,true);}}
  document.getElementById('start-round').onclick=async()=>{try{await api(`/api/team/rounds/${summary.round_id}/start`,{method:'POST',body:'{}'});toast('Round timer started');refresh();}catch(error){toast(error.message,true);}};
  async function submitToken(value) {
    const raw=value.trim();if(!raw)return toast('Enter a QR token or scan link.',true);
    let token=raw;try{const parsed=new URL(raw);const match=parsed.pathname.match(/\/scan\/([^/]+)/);if(match)token=match[1];}catch{}
    try {
      const result=await api('/api/team/scan',{method:'POST',body:JSON.stringify({token})});
      const container=document.getElementById('scan-result');container.hidden=false;
      container.innerHTML=`<strong>${esc(result.qr_id)}</strong><p>${esc(result.prompt)}</p>${result.requires_answer?'<form id="clue-answer"><label>Your answer<input name="answer" maxlength="500" required></label><button class="button primary small" type="submit">Submit answer</button></form>':''}`;
      if(result.requires_answer)container.querySelector('form').onsubmit=async event=>{event.preventDefault();try{const data=await api(`/api/team/scan/${result.scan_id}/answer`,{method:'POST',body:JSON.stringify(Object.fromEntries(new FormData(event.currentTarget)))});container.insertAdjacentHTML('beforeend',`<p><b>${data.correct?'Correct':'Not quite'} · ${data.points} points</b></p>`);container.querySelector('form').remove();refresh();}catch(error){toast(error.message,true);}};
      document.getElementById('token-input').value='';toast('QR scan recorded by the server');
    }catch(error){toast(error.message,true);}
  }
  document.getElementById('manual-scan').onsubmit=event=>{event.preventDefault();submitToken(document.getElementById('token-input').value);};
  document.getElementById('scan-open').onclick=async()=>{
    const box=document.getElementById('camera-box');box.hidden=false;
    if(!window.ZXingBrowser){toast('Camera scanner could not load. Enter the code manually.',true);return;}
    try{const reader=new ZXingBrowser.BrowserMultiFormatReader();cameraControls=await reader.decodeFromVideoDevice(undefined,document.getElementById('camera-video'),(result,error)=>{if(result){cameraControls?.stop();box.hidden=true;submitToken(result.getText());}});}catch(error){toast('Camera access failed. Check browser permissions or enter the code manually.',true);}
  };
  document.getElementById('stop-camera').onclick=()=>{cameraControls?.stop();document.getElementById('camera-box').hidden=true;};
  document.getElementById('quiz-next').onclick=async()=>{
    try{const data=await api('/api/team/quiz/next',{method:'POST',body:'{}'});if(data.done){toast(data.message);return;}
      activeQuiz=data;const box=document.getElementById('quiz-box');box.hidden=false;
      box.innerHTML=`<small>QUESTION · ${data.points} POINTS</small><p><b>${esc(data.question)}</b></p><div>${Object.entries(data.options).map(([key,value])=>`<label class="quiz-option"><input type="radio" name="selected_answer" value="${key}"> <b>${key}</b> ${esc(value)}</label>`).join('')}</div><p>Time remaining: <b id="quiz-countdown">${data.time_limit}</b>s</p><button class="button primary small" id="quiz-submit">Submit answer</button>`;
      let remaining=Math.max(0,data.time_limit-Math.floor((Date.now()-new Date(data.started_at).getTime())/1000));clearInterval(quizInterval);if(remaining===0){submitQuiz('');return;}quizInterval=setInterval(()=>{remaining--;const count=document.getElementById('quiz-countdown');if(count)count.textContent=Math.max(0,remaining);if(remaining<=0)submitQuiz('');},1000);
      document.getElementById('quiz-submit').onclick=()=>submitQuiz(box.querySelector('input:checked')?.value||'');
    }catch(error){toast(error.message,true);}
  };
  async function submitQuiz(selected_answer){clearInterval(quizInterval);if(!activeQuiz)return;try{const result=await api(`/api/team/quiz/${activeQuiz.answer_id}/submit`,{method:'POST',body:JSON.stringify({selected_answer})});document.getElementById('quiz-box').innerHTML=`<b>${result.expired?'Time expired.':result.correct?'Correct answer.':'Answer recorded.'}</b><p>${result.points} points</p>`;activeQuiz=null;refresh();}catch(error){toast(error.message,true);}}
  document.getElementById('complete-round').onclick=async()=>{if(!confirm('Finish your current round? You cannot restart it.'))return;try{await api(`/api/team/rounds/${summary.round_id}/complete`,{method:'POST',body:'{}'});toast('Round completed');refresh();}catch(error){toast(error.message,true);}};
  if(window.io){const socket=io();socket.emit('join_participant');socket.on('leaderboard',refreshLeaderboard);}
  refresh();setInterval(refresh,20000);
  const scan=new URLSearchParams(location.search).get('scan');if(scan){history.replaceState({},'',location.pathname);setTimeout(()=>submitToken(scan),500);}
})();