const API_BASE = "https://hamster-miniapp.onrender.com";  // backend base

const balanceEl = document.getElementById('balance');
const perclickEl = document.getElementById('perclick');
const earnBtn = document.getElementById('earnBtn');
const buyClick = document.getElementById('buyClick');
const buyAuto = document.getElementById('buyAuto');
const dailyBtn = document.getElementById('dailyBtn');
const leaderBtn = document.getElementById('leaderBtn');
const message = document.getElementById('message');

// Modal refs
const leaderModal = document.getElementById('leaderModal');
const leaderClose = document.querySelector('.close');
const leaderDiv = document.getElementById('leaderboard');

// Telegram WebApp
let tg = window.Telegram?.WebApp;
tg && tg.expand();

let user_id = tg?.initDataUnsafe?.user?.id;
let initData = tg?.initData || "";  // 🔹 Security validation string

if(!user_id){
  const qs = new URLSearchParams(location.search);
  user_id = qs.get('user_id');
}

if(!user_id){
  showMessage('❌ Error: user_id missing. Open from the Telegram bot.', "error");
}

// 🔹 helper to show messages with class
function showMessage(text, type = ""){
  message.innerText = text || "";
  message.className = type ? type : "";
  if (text) {
    clearTimeout(showMessage._t);
    showMessage._t = setTimeout(()=> { message.innerText=""; message.className=""; }, 3000);
  }
}

// safe fetch wrapper
async function safeFetch(url, options){
  try {
    const res = await fetch(url, options);
    if(!res.ok) {
      let text = await res.text().catch(()=> "");
      try { const j = JSON.parse(text); text = j.error || text; } catch(e){}
      throw new Error(text || `HTTP ${res.status}`);
    }
    return await res.json();
  } catch(err){
    showMessage(err.message || "⚠️ Network error, try again.", "error");
    console.error(err);
    return {};
  }
}

// 🔹 Helper: run function with loading state
async function withLoading(btn, fn){
  btn.disabled = true;
  btn.classList.add("loading");
  try {
    await fn();
  } finally {
    btn.disabled = false;
    btn.classList.remove("loading");
  }
}

// fetch user data
async function fetchUser(){
  const data = await safeFetch(`${API_BASE}/api/user/${user_id}?initData=${encodeURIComponent(initData)}`);
  if(data && data.balance !== undefined){
    balanceEl.innerText = `Balance: ${data.balance}`;
    perclickEl.innerText = `Per Click: ${data.per_click}`;
  }
}

// Earn coins
earnBtn.onclick = ()=> withLoading(earnBtn, async ()=>{
  const data = await safeFetch(`${API_BASE}/api/earn`, {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({user_id, initData})
  });
  if(data && data.balance !== undefined){
    balanceEl.innerText = `Balance: ${data.balance}`;
    showMessage(`+${data.per_click} coins!`, "success");
  }
});

// Buy Per Click
buyClick.onclick = ()=> withLoading(buyClick, async ()=>{
  const data = await safeFetch(`${API_BASE}/api/buy`, {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({user_id, item:'click', initData})
  });
  if(data && data.ok){
    balanceEl.innerText = `Balance: ${data.balance}`;
    perclickEl.innerText = `Per Click: ${data.per_click}`;
    showMessage('✅ Per Click upgraded!', "success");
  }
});

// Buy Auto Clicker
buyAuto.onclick = ()=> withLoading(buyAuto, async ()=>{
  const data = await safeFetch(`${API_BASE}/api/buy`, {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({user_id, item:'auto', initData})
  });
  if(data && data.ok){
    balanceEl.innerText = `Balance: ${data.balance}`;
    showMessage(`⚡ Auto Clicker level: ${data.auto_clicker_level}`, "success");
  }
});

// Daily Bonus
dailyBtn.onclick = ()=> withLoading(dailyBtn, async ()=>{
  const data = await safeFetch(`${API_BASE}/api/daily`, {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({user_id, initData})
  });
  if(data && data.ok){
    balanceEl.innerText = `Balance: ${data.balance}`;
    showMessage(`🎁 Daily bonus +${data.bonus}`, "success");
  }
});

// Leaderboard
leaderBtn.onclick = ()=> withLoading(leaderBtn, async ()=>{
  let html = "";
  const top = await safeFetch(`${API_BASE}/api/leaderboard?initData=${encodeURIComponent(initData)}`);
  if(Array.isArray(top)){
    html = top.map((r,i)=>{
      return `<div data-username="${(r.username||'Guest')}">${i+1}. ${r.username || 'Guest'} — ${r.balance} 💰</div>`;
    }).join('');
  }

  leaderDiv.innerHTML = html;

  // fetch your exact rank & highlight
  const me = await safeFetch(`${API_BASE}/api/rank/${user_id}?initData=${encodeURIComponent(initData)}`);
  if(me && me.username){
    let highlightDone = false;
    const nodes = leaderDiv.querySelectorAll('div[data-username]');
    nodes.forEach((n, idx)=>{
      if(n.getAttribute('data-username') === me.username){
        n.classList.add('you');
        n.innerHTML = `⭐ You — Rank ${idx+1} — ${me.balance} 💰`;
        highlightDone = true;
      }
    });

    if(!highlightDone){
      leaderDiv.innerHTML += `<div style="margin-top:10px;padding-top:8px;border-top:1px solid #ccc;" class="you">
        ⭐ Your Rank: ${me.rank} — ${me.username || 'You'} (${me.balance} 💰)
      </div>`;
    }
  }

  leaderModal.style.display = "block";
});

// Close modal
leaderClose.onclick = ()=> leaderModal.style.display = "none";
window.onclick = (e)=>{ if(e.target === leaderModal){ leaderModal.style.display = "none"; } };

// init
fetchUser();

// 🔹 Auto refresh balance every 10s
setInterval(fetchUser, 10000);
