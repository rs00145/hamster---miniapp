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
if(!user_id){
  const qs = new URLSearchParams(location.search);
  user_id = qs.get('user_id');
}

if(!user_id){
  message.innerText = '❌ Error: user_id missing. Open from the Telegram bot.';
}

// safe fetch wrapper
async function safeFetch(url, options){
  try {
    const res = await fetch(url, options);
    if(!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch(err){
    message.innerText = "⚠️ Network error, try again.";
    console.error(err);
    return {};
  }
}

async function fetchUser(){
  const data = await safeFetch(`${API_BASE}/api/user/${user_id}`);
  if(data.balance !== undefined){
    balanceEl.innerText = `Balance: ${data.balance}`;
    perclickEl.innerText = `Per Click: ${data.per_click}`;
  }
}

earnBtn.onclick = async ()=>{
  const data = await safeFetch(`${API_BASE}/api/earn`, {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({user_id})
  });
  if(data.balance !== undefined){
    balanceEl.innerText = `Balance: ${data.balance}`;
    message.innerText = `+${data.per_click} coins!`;
  }
};

buyClick.onclick = async ()=>{
  const data = await safeFetch(`${API_BASE}/api/buy`, {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({user_id, item:'click'})
  });
  if(data.ok){
    balanceEl.innerText = `Balance: ${data.balance}`;
    perclickEl.innerText = `Per Click: ${data.per_click}`;
    message.innerText = '✅ Per Click upgraded!';
  } else {
    message.innerText = data.error || '❌ Failed';
  }
};

buyAuto.onclick = async ()=>{
  const data = await safeFetch(`${API_BASE}/api/buy`, {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({user_id, item:'auto'})
  });
  if(data.ok){
    balanceEl.innerText = `Balance: ${data.balance}`;
    message.innerText = `⚡ Auto Clicker level: ${data.auto_clicker_level}`;
  } else {
    message.innerText = data.error || '❌ Failed';
  }
};

dailyBtn.onclick = async ()=>{
  const data = await safeFetch(`${API_BASE}/api/daily`, {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({user_id})
  });
  if(data.ok){
    balanceEl.innerText = `Balance: ${data.balance}`;
    message.innerText = `🎁 Daily bonus +${data.bonus}`;
  } else {
    message.innerText = data.error || '❌ Already claimed';
  }
};

leaderBtn.onclick = async ()=>{
  const top = await safeFetch(`${API_BASE}/api/leaderboard`);
  let html = "";
  let youInTop = false;

  if(Array.isArray(top)){
    html += top.map((r,i)=>{
      // /api/leaderboard returns {username, balance}
      // Compare by username later when we know "you"
      return `<div data-username="${(r.username||'Guest')}">${i+1}. ${r.username || 'Guest'} — ${r.balance} 💰</div>`;
    }).join('');
  }

  // fetch your exact rank
  const me = await safeFetch(`${API_BASE}/api/rank/${user_id}`);
  if(me && me.username){
    // highlight if present in top
    const nodes = leaderDiv.querySelectorAll('div[data-username]');
    nodes.forEach((n, idx)=>{
      if(n.getAttribute('data-username') === me.username){
        n.classList.add('you');
        n.innerHTML = `⭐ You — Rank ${idx+1} — ${me.balance} 💰`;
        youInTop = true;
      }
    });

    if(!youInTop){
      html += `<div style="margin-top:10px;padding-top:8px;border-top:1px solid #ccc;" class="you">
        ⭐ Your Rank: ${me.rank} — ${me.username} (${me.balance} 💰)
      </div>`;
    }
  }

  leaderDiv.innerHTML = html;
  leaderModal.style.display = "block";
};

// Close modal
leaderClose.onclick = ()=> leaderModal.style.display = "none";
window.onclick = (e)=>{ if(e.target === leaderModal){ leaderModal.style.display = "none"; } };

// init
fetchUser();
