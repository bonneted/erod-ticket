(() => {
  const waitingListEl = document.getElementById('waiting-list');
  const passedListEl = document.getElementById('passed-list');
  const timerDisplayEl = document.getElementById('timer-display');
  const timerProgressEl = document.getElementById('timer-progress');
  const pauseBtn = document.getElementById('pause-btn');
  const nextBtn = document.getElementById('next-btn');
  const backBtn = document.getElementById('back-btn');
  const tourInput = document.getElementById('tour-length');
  const setTourBtn = document.getElementById('set-tour-btn');
  const tourLengthDisplay = document.getElementById('tour-length-display');
  const statusLabel = document.getElementById('status-label');
  const toggleDragBtn = document.getElementById('toggle-drag-btn');

  let sortable = null;
  let dragEnabled = false;

  async function api(path, opts = {}){
    const res = await fetch(path, opts);
    if (!res.ok) {
      throw new Error('API error: ' + res.status + ' ' + res.statusText);
    }
    return await res.json();
  }

  async function fetchStatus(){
    try{
      const data = await api('/api/status');
      // Update lists
      updateWaiting(data.waiting, data.tour_length_seconds);
      updatePassed(data.passed);
      updateTimer(data.time_remaining_seconds, data.tour_length_seconds, data.timer_paused);
      tourLengthDisplay.innerText = Math.round(data.tour_length_seconds/60);
      tourInput.value = Math.round(data.tour_length_seconds/60);
      statusLabel.innerText = data.timer_paused ? 'Paused' : (data.time_remaining_seconds === null ? 'Idle' : 'Running');
    }catch(e){
      console.error('status fetch failed', e);
    }
  }

  function updateWaiting(waiting, tourLengthSec){
    // Build new HTML
    waitingListEl.innerHTML = '';
    waiting.forEach((p, idx) => {
      const li = document.createElement('li');
      li.className = 'list-group-item d-flex justify-content-between align-items-center';
      li.dataset.id = p.id;
      // ETA in minutes
      const eta_mins = Math.max(0, Math.floor(((p.position - 1) * tourLengthSec) / 60));
      li.innerHTML = `<div><strong>${escapeHtml(p.name)}</strong> <small class="text-muted">(#${p.position})</small></div><span class="badge bg-primary rounded-pill">${eta_mins} min</span>`;
      // Add a small pass button to send person to passed list
      const btn = document.createElement('button');
      btn.className = 'btn btn-sm btn-outline-secondary ms-3';
      btn.innerText = 'Pass';
      btn.addEventListener('click', async (ev)=>{
        ev.stopPropagation();
        try{
          await api('/api/move', {method:'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({id: p.id, toStatus: 'passed'})});
          fetchStatus();
        }catch(e){ console.error('move failed', e); }
      });
      li.appendChild(btn);
      waitingListEl.appendChild(li);
    });
    // Re-init sortable if enabled
    if (dragEnabled && !sortable){
      sortable = Sortable.create(waitingListEl, {
        animation: 150,
        onEnd: sendReorder
      });
    }
  }

  function sendReorder(){
    const ids = Array.from(waitingListEl.children).map(li => parseInt(li.dataset.id));
    api('/api/reorder', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ids})
    }).then(()=> {
      fetchStatus();
    }).catch(err=> console.error('reorder failed', err));
  }

  function updatePassed(passed){
    passedListEl.innerHTML = '';
    passed.forEach((p)=>{
      const li = document.createElement('li');
      li.className = 'list-group-item';
      li.innerText = `${p.name}`;
  const btn = document.createElement('button');
  btn.className = 'btn btn-sm btn-outline-primary float-end ms-2';
  btn.innerText = 'Requeue';
      btn.addEventListener('click', async (ev)=>{
        ev.stopPropagation();
        try{
          await api('/api/move', {method:'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({id: p.id, toStatus: 'waiting', toPosition: 1})});
          fetchStatus();
        }catch(e){ console.error('move failed', e); }
      });
      li.appendChild(btn);
      const delBtn = document.createElement('button');
      delBtn.className = 'btn btn-sm btn-outline-danger float-end';
      delBtn.innerText = 'Delete';
      delBtn.addEventListener('click', async (ev)=>{
        ev.stopPropagation();
        if (!confirm('Delete this person? This cannot be undone.')) return;
        try{
          const res = await fetch(`/api/person/${p.id}`, {method:'DELETE'});
          if (!res.ok) throw new Error('Delete failed');
          fetchStatus();
        }catch(e){ console.error('delete failed', e); }
      });
      li.appendChild(delBtn);
      passedListEl.appendChild(li);
    });
  }

  function updateTimer(timeRemainingSec, tourLengthSec, paused){
    if (timeRemainingSec === null){
      timerDisplayEl.innerText = '--:--';
      timerProgressEl.style.width = '0%';
      return;
    }
    const percent = (1 - (timeRemainingSec / tourLengthSec)) * 100;
    timerProgressEl.style.width = `${Math.max(0, Math.min(100, percent))}%`;
    timerDisplayEl.innerText = fmtTime(timeRemainingSec);
    pauseBtn.innerText = paused ? 'Resume' : 'Pause';
  }

  function fmtTime(sec){
    if (sec === null) return '--:--';
    const m = Math.floor(sec / 60).toString().padStart(2, '0');
    const s = Math.floor(sec % 60).toString().padStart(2, '0');
    return `${m}:${s}`;
  }

  function escapeHtml(unsafe) {
    return unsafe
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#039;');
  }

  pauseBtn.addEventListener('click', async ()=>{
    try{
      await api('/api/pause', {method:'POST'});
      fetchStatus();
    }catch(e){ console.error(e); }
  });

  nextBtn.addEventListener('click', async ()=>{
    try{
      await api('/api/next', {method: 'POST'});
      fetchStatus();
    }catch(e){ console.error(e); }
  });

  backBtn.addEventListener('click', async ()=>{
    try{
      await api('/api/back', {method: 'POST'});
      fetchStatus();
    }catch(e){ console.error(e); }
  });

  setTourBtn.addEventListener('click', async ()=>{
    const mins = parseInt(tourInput.value) || 0;
    if (mins <= 0 ) return alert('Invalid minutes');
    try{
      await api('/api/set-tour-length', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({minutes: mins})
      });
      fetchStatus();
    }catch(e){ console.error(e); }
  });

  toggleDragBtn.addEventListener('click', ()=>{
    dragEnabled = !dragEnabled;
    toggleDragBtn.innerText = dragEnabled ? 'Disable reorder' : 'Enable reorder';
    if (!dragEnabled && sortable){
      sortable.destroy();
      sortable = null;
    } else if (dragEnabled && !sortable){
      sortable = Sortable.create(waitingListEl, {
        animation: 150,
        onEnd: sendReorder
      });
    }
  });

  // initial fetch and periodic polling
  fetchStatus();
  setInterval(fetchStatus, 1000);
})();