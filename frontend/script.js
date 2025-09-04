const API_BASE = "https://hamster-miniapp.onrender.com";  // backend base

// Elements
const balanceEl = document.getElementById('balance');
const perclickEl = document.getElementById('perclick');
const earnBtn = document.getElementById('earnBtn');
const buyClick = document.getElementById('buyClick');
const buyAuto = document.getElementById('buyAuto');
const dailyBtn = document.getElementById('dailyBtn');
const leaderBtn = document.getElementById('leaderBtn');
const message = document.getElementById('message');
const leaderModal = document.getElementById('leaderModal');
const leaderClose = document.querySelector('.close');
const leaderDiv = document.getElementById('leaderboard');

// Telegram WebApp
let tg = window.Telegram?.WebApp;
tg && tg.expand();

let user_id = tg?.initDataUnsafe?.user?.id || null;
let initData = tg?.initData || "";  // 🔹 secure string

if (!user_id) {
  const qs = new URLSearchParams(location.search);
  user_id = qs.get('user_id');
}

if (!user_id || !initData) {
  showMessage("❌ Error: open this game from Telegram bot.", "error");
  throw new Error("Missing user_id or initData");
}

// 🔹 message helper
function showMessage(text, type = "") {
  message.innerText = text || "";
  message.className = type || "";
  if (text) {
    clearTimeout(showMessage._t);
    showMessage._t = setTimeout(() => {
      message.innerText = "";
      message.className = "";
    }, 3000);
  }
}

// 🔹 fetch wrapper with error handling
async function safeFetch(url, options) {
  try {
    const res = await fetch(url, options);
    if (!res.ok) {
      let text = await res.text().catch(() => "");
      try { const j = JSON.parse(text); text = j.error || text; } catch {}
      throw new Error(text || `HTTP ${res.status}`);
    }
    return await res.json();
  } catch (err) {
    showMessage(err.message || "⚠️ Network error", "error");
    console.error(err);
    return {};
  }
}

// 🔹 run with loading state
async function withLoading(btn, fn) {
  btn.disabled = true;
  btn.classList.add("loading");
  try {
    await fn();
  } finally {
    btn.disabled = false;
    btn.classList.remove("loading");
  }
}

// ---------------- Fetch user ----------------
async function fetchUser() {
  const data = await safeFetch(`${API_BASE}/api/user/${user_id}?initData=${encodeURIComponent(initData)}`);
  if (data && data.balance !== undefined) {
    balanceEl.innerText = `Balance: ${data.balance}`;
    perclickEl.innerText = `Per Click: ${data.per_click}`;
  }
}

// ---------------- Earn ----------------
earnBtn.onclick = () => withLoading(earnBtn, async () => {
  const data = await safeFetch(`${API_BASE}/api/earn`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id, initData })
  });
  if (data && data.balance !== undefined) {
    balanceEl.innerText = `Balance: ${data.balance}`;
    showMessage(`+${data.per_click} coins!`, "success");
  }
});

// ---------------- Buy Click ----------------
buyClick.onclick = () => withLoading(buyClick, async () => {
  const data = await safeFetch(`${API_BASE}/api/buy`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id, item: "click", initData })
  });
  if (data && data.ok) {
    balanceEl.innerText = `Balance: ${data.balance}`;
    perclickEl.innerText = `Per Click: ${data.per_click}`;
    showMessage("✅ Per Click upgraded!", "success");
  }
});

// ---------------- Buy Auto ----------------
buyAuto.onclick = () => withLoading(buyAuto, async () => {
  const data = await safeFetch(`${API_BASE}/api/buy`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id, item: "auto", initData })
  });
  if (data && data.ok) {
    balanceEl.innerText = `Balance: ${data.balance}`;
    showMessage(`⚡ Auto Clicker level: ${data.auto_clicker_level}`, "success");
  }
});

// ---------------- Daily Bonus ----------------
dailyBtn.onclick = () => withLoading(dailyBtn, async () => {
  const data = await safeFetch(`${API_BASE}/api/daily`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id, initData })
  });
  if (data && data.ok) {
    balanceEl.innerText = `Balance: ${data.balance}`;
    showMessage(`🎁 Daily bonus +${data.bonus}`, "success");
  }
});

// ---------------- Leaderboard ----------------
leaderBtn.onclick = () => withLoading(leaderBtn, async () => {
  let html = "";
  const top = await safeFetch(`${API_BASE}/api/leaderboard?initData=${encodeURIComponent(initData)}`);
  if (Array.isArray(top)) {
    html = top.map((r, i) => {
      return `<div data-username="${r.username || "Guest"}">${i + 1}. ${r.username || "Guest"} — ${r.balance} 💰</div>`;
    }).join("");
  }
  leaderDiv.innerHTML = html;

  // fetch your rank
  const me = await safeFetch(`${API_BASE}/api/rank/${user_id}?initData=${encodeURIComponent(initData)}`);
  if (me && me.username) {
    let found = false;
    leaderDiv.querySelectorAll("div[data-username]").forEach((n, idx) => {
      if (n.getAttribute("data-username") === me.username) {
        n.classList.add("you");
        n.innerHTML = `⭐ You — Rank ${idx + 1} — ${me.balance} 💰`;
        found = true;
      }
    });
    if (!found) {
      leaderDiv.innerHTML += `<div style="margin-top:10px;padding-top:8px;border-top:1px solid #ccc;" class="you">
        ⭐ Your Rank: ${me.rank} — ${me.username || "You"} (${me.balance} 💰)
      </div>`;
    }
  }

  leaderModal.style.display = "block";
});

// ---------------- Modal close ----------------
leaderClose.onclick = () => leaderModal.style.display = "none";
window.onclick = (e) => { if (e.target === leaderModal) leaderModal.style.display = "none"; };

// ---------------- Init ----------------
fetchUser();
setInterval(fetchUser, 10000);  // auto refresh
