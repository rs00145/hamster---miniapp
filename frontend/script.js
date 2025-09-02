const qs = new URLSearchParams(location.search);
const user_id = qs.get('user_id');
const API_BASE = '';

const balanceEl = document.getElementById('balance');
const perclickEl = document.getElementById('perclick');
const earnBtn = document.getElementById('earnBtn');
const buyClick = document.getElementById('buyClick');
const buyAuto = document.getElementById('buyAuto');
const dailyBtn = document.getElementById('dailyBtn');
const leaderBtn = document.getElementById('leaderBtn');
const message = document.getElementById('message');
const leaderDiv = document.getElementById('leaderboard');

if(!user_id){
  message.innerText = 'Error: user_id missing. Open app from the bot.';
}

async function fetchUser(){
  const res = await fetch(`/api/user/${user_id}`);
  const data = await res.json();
  balanceEl.innerText = `Balance: ${data.balance}`;
  perclickEl.innerText = `Per Click: ${data.per_click}`;
}

earnBtn.onclick = async ()=>{
  const res = await fetch('/api/earn', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id})});
  const data = await res.json();
  if(data.balance!==undefined){
    balanceEl.innerText = `Balance: ${data.balance}`;
    message.innerText = `+${data.per_click} coins!`;
  }
}

buyClick.onclick = async ()=>{
  const res = await fetch('/api/buy',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id,item:'click'})});
  const data = await res.json();
  if(data.ok){
    balanceEl.innerText = `Balance: ${data.balance}`;
    perclickEl.innerText = `Per Click: ${data.per_click}`;
    message.innerText = 'Per Click upgraded!';
  } else {
    message.innerText = data.error || 'Failed';
  }
}

buyAuto.onclick = async ()=>{
  const res = await fetch('/api/buy',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id,item:'auto'})});
  const data = await res.json();
  if(data.ok){
    balanceEl.innerText = `Balance: ${data.balance}`;
    message.innerText = `Auto Clicker level: ${data.auto_clicker_level}`;
  } else {
    message.innerText = data.error || 'Failed';
  }
}

dailyBtn.onclick = async ()=>{
  const res = await fetch('/api/daily',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id})});
  const data = await res.json();
  if(data.ok){
    balanceEl.innerText = `Balance: ${data.balance}`;
    message.innerText = `Daily bonus +${data.bonus}`;
  } else {
    message.innerText = data.error || 'Already claimed';
  }
}

leaderBtn.onclick = async ()=>{
  const res = await fetch('/api/leaderboard');
  const rows = await res.json();
  leaderDiv.style.display = 'block';
  leaderDiv.innerHTML = '<h3>Leaderboard</h3>' + rows.map((r,i)=>`<div>${i+1}. ${r.user_id} — ${r.balance}</div>`).join('');
}

// init
fetchUser();
