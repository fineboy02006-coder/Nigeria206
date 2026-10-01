#!/usr/bin/env python3
"""
Nigeria206 v3 backend prototype
- Python standard library only
- SQLite database
- Cookie sessions
- Server-side wallet/task/withdrawal logic
- Demo only: no real money transfer, no production deployment
Run: python server.py
Then open http://127.0.0.1:8000
Demo admin: admin@Nigeria206.test / Admin123!
"""

import hashlib, hmac, http.server, json, os, secrets, sqlite3, time, urllib.parse
from http import cookies
from pathlib import Path

BASE = Path(__file__).resolve().parent
DB = BASE / "nigeria206.db"
STATIC = BASE / "static"
INDEX_HTML = '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width,initial-scale=1">\n<title>Nigeria206 — Earn From Verified Tasks</title>\n<meta name="description" content="Nigeria206 task and rewards platform prototype">\n<style>\n:root{--bg:#07130d;--panel:#0d2116;--panel2:#102a1b;--line:#214532;--text:#f5fff8;--muted:#9fb6a7;--green:#35df82;--red:#ff6b6b;--yellow:#ffd166}\n*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at top right,#123821 0,#07130d 38%,#040b07 100%);color:var(--text);font-family:Inter,system-ui,-apple-system,Segoe UI,Arial}\nheader{position:sticky;top:0;z-index:10;background:#07130de8;backdrop-filter:blur(14px);border-bottom:1px solid var(--line)}\n.wrap{max-width:1120px;margin:auto;padding:16px}.top{display:flex;justify-content:space-between;align-items:center;gap:15px}.brand{font-size:24px;font-weight:950;letter-spacing:-.7px}.brand b{color:var(--green)}.status{font-size:12px;color:var(--green);border:1px solid var(--line);border-radius:99px;padding:6px 9px}\nnav{display:flex;gap:7px;overflow:auto;padding-top:12px}button{border:1px solid var(--line);background:var(--panel2);color:var(--text);padding:10px 13px;border-radius:11px;cursor:pointer;white-space:nowrap}button:hover{filter:brightness(1.15)}button.primary{background:var(--green);color:#031108;border-color:var(--green);font-weight:850}button.danger{background:#321515;border-color:#632525}.hero{padding:38px 0 24px}.hero h1{font-size:clamp(36px,7vw,66px);line-height:.98;max-width:760px;margin:12px 0}.hero p{max-width:680px;color:var(--muted);font-size:17px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:14px}.card{background:#0c1e14d9;border:1px solid var(--line);border-radius:18px;padding:18px;box-shadow:0 16px 50px #0004}.metric{font-size:32px;font-weight:950;margin-top:7px}.muted{color:var(--muted)}.small{font-size:13px}.tag{display:inline-block;border:1px solid var(--line);color:var(--green);border-radius:99px;padding:5px 9px;font-size:12px}.hidden{display:none}.section{padding:20px 0}.task{display:flex;flex-direction:column;gap:9px}.row{display:flex;justify-content:space-between;gap:10px;align-items:center}input,textarea,select{width:100%;padding:12px;border:1px solid var(--line);border-radius:11px;background:#07130d;color:var(--text);margin:5px 0 10px}textarea{min-height:100px;resize:vertical}.notice{padding:12px;border:1px solid var(--line);border-radius:11px;background:#10291a;margin:12px 0}.notice.err{background:#321515;border-color:#632525}.table{overflow:auto}.table table{border-collapse:collapse;width:100%;min-width:650px}.table th,.table td{text-align:left;padding:10px;border-bottom:1px solid var(--line);font-size:13px}.footer{padding:40px 0;color:var(--muted);font-size:12px}.pill{padding:4px 8px;border-radius:99px;background:#183a24;font-size:11px}.warning{color:var(--yellow)}a{color:var(--green)}\n</style>\n</head>\n<body>\n<header><div class="wrap"><div class="top"><div class="brand">🇳🇬 Nigeria<b>206</b></div><div class="status">● Prototype online</div></div><nav id="nav"></nav></div></header>\n<main class="wrap">\n\n<section id="home" class="hero">\n<span class="tag">TASKS • REWARDS • WITHDRAWALS</span>\n<h1>Earn from verified tasks. Build your wallet.</h1>\n<p>Nigeria206 is a task-and-rewards prototype. Users complete genuine tasks, submit proof, receive approved rewards and request withdrawals from ₦1,000.</p>\n<div style="display:flex;gap:9px;flex-wrap:wrap"><button class="primary" onclick="show(\'tasks\')">Explore tasks</button><button onclick="show(\'auth\')">Create account</button></div>\n<div class="section"><div class="grid">\n<div class="card"><b>1. Register</b><p class="muted small">Create your account and receive a referral code.</p></div>\n<div class="card"><b>2. Complete</b><p class="muted small">Choose an available task and follow its instructions.</p></div>\n<div class="card"><b>3. Verify</b><p class="muted small">Submit truthful proof for admin review.</p></div>\n<div class="card"><b>4. Withdraw</b><p class="muted small">Approved rewards enter your wallet. Minimum withdrawal is ₦1,000.</p></div>\n</div></div>\n</section>\n\n<section id="auth" class="section hidden"><div class="grid">\n<div class="card"><h2>Create account</h2><input id="rname" placeholder="Full name"><input id="remail" placeholder="Email"><input id="rpass" type="password" placeholder="Password — 8+ characters"><input id="rref" placeholder="Referral code (optional)"><button class="primary" onclick="register()">Create account</button></div>\n<div class="card"><h2>Login</h2><input id="lemail" placeholder="Email"><input id="lpass" type="password" placeholder="Password"><button class="primary" onclick="login()">Login</button><p class="muted small">Demo admin: admin@Nigeria206.test / Admin123!</p></div>\n</div></section>\n\n<section id="dashboard" class="section hidden"><div class="grid">\n<div class="card"><div class="muted">Available balance</div><div class="metric" id="balance">₦0</div><button class="primary" onclick="show(\'withdraw\')">Withdraw</button></div>\n<div class="card"><div class="muted">Your referral code</div><div class="metric" id="refcode">—</div><p class="muted small">Referral rewards should be funded by legitimate business revenue, not by requiring users to pay to join.</p></div>\n<div class="card"><div class="muted">Account</div><h3 id="dashname">—</h3><p class="muted small" id="dashemail"></p><button onclick="show(\'account\')">Account settings</button></div>\n</div></section>\n\n<section id="tasks" class="section hidden"><div class="row"><h2>Available tasks</h2><button onclick="loadTasks()">Refresh</button></div><div id="tasklist" class="grid"></div></section>\n\n<section id="wallet" class="section hidden"><h2>Wallet & transaction history</h2><div class="card"><div class="metric" id="walletBalance">₦0</div><p class="muted">Every reward and withdrawal request is recorded in the server-side ledger.</p></div><div class="card table"><table><thead><tr><th>Type</th><th>Amount</th><th>Note</th><th>Time</th></tr></thead><tbody id="tx"></tbody></table></div></section>\n\n<section id="withdraw" class="section hidden"><div class="card"><h2>Request withdrawal</h2><div class="notice"><b>Minimum: ₦1,000</b><br><span class="muted small">This prototype queues requests for admin review. It does not transfer real money.</span></div><input id="wamount" type="number" min="1000" placeholder="Amount"><select id="wmethod"><option>OPay</option><option>Bank transfer</option></select><input id="wname" placeholder="Account/wallet name"><input id="wnumber" placeholder="Account/wallet number"><button class="primary" onclick="withdraw()">Submit request</button></div></section>\n\n<section id="account" class="section hidden"><div class="card"><h2>Account</h2><div id="accountInfo"></div><button class="danger" onclick="logout()">Log out</button></div></section>\n\n<section id="admin" class="section hidden"><h2>Admin control center</h2><div id="adminStats" class="grid"></div>\n<div class="card"><h3>Task submissions</h3><div id="subs" class="table"></div></div>\n<div class="card"><h3>Withdrawal queue</h3><div id="withdrawals" class="table"></div></div>\n</section>\n\n<div id="msg"></div>\n<footer class="footer">Nigeria206 prototype • Real payouts require a verified payment provider, secure production hosting, proper business/compliance setup and server-side webhook verification.</footer>\n</main>\n<script>\nlet me=null;\nconst $=id=>document.getElementById(id);\nconst money=n=>\'₦\'+Number(n||0).toLocaleString(\'en-NG\');\nfunction esc(s){return String(s??\'\').replace(/[&<>"\']/g,m=>({\'&\':\'&amp;\',\'<\':\'&lt;\',\'>\':\'&gt;\',\'"\':\'&quot;\',"\'":\'&#39;\'}[m]))}\nfunction notice(t,err=false){$(\'msg\').innerHTML=`<div class="notice ${err?\'err\':\'\'}">${esc(t)}</div>`;setTimeout(()=>$(\'msg\').innerHTML=\'\',3500)}\nfunction show(id){document.querySelectorAll(\'main section\').forEach(x=>x.classList.add(\'hidden\'));$(id).classList.remove(\'hidden\');if(id===\'tasks\')loadTasks();if(id===\'wallet\')loadWallet();if(id===\'dashboard\')loadMe();if(id===\'admin\')loadAdmin();if(id===\'account\')renderAccount()}\nasync function api(url,opt={}){const r=await fetch(url,{headers:{\'Content-Type\':\'application/json\'},...opt});const d=await r.json();if(!r.ok)throw Error(d.error||\'Request failed\');return d}\nfunction renderNav(){ $(\'nav\').innerHTML=me?`<button onclick="show(\'dashboard\')">Dashboard</button><button onclick="show(\'tasks\')">Tasks</button><button onclick="show(\'wallet\')">Wallet</button><button onclick="show(\'withdraw\')">Withdraw</button>${me.role===\'admin\'?\'<button onclick="show(\\\\\'admin\\\\\')">Admin</button>\':\'\'}<button onclick="show(\'account\')">Account</button>`:`<button onclick="show(\'home\')">Home</button><button onclick="show(\'tasks\')">Tasks</button><button onclick="show(\'auth\')">Login / Register</button>`}\nasync function loadMe(){const d=await api(\'/api/me\');me=d.user;renderNav();if(me){$(\'balance\').textContent=money(me.balance);$(\'refcode\').textContent=me.referral_code;$(\'dashname\').textContent=me.name;$(\'dashemail\').textContent=me.email}}\nasync function register(){try{const d=await api(\'/api/register\',{method:\'POST\',body:JSON.stringify({name:rname.value,email:remail.value,password:rpass.value,referral_code:rref.value})});notice(d.message);show(\'auth\')}catch(e){notice(e.message,true)}}\nasync function login(){try{await api(\'/api/login\',{method:\'POST\',body:JSON.stringify({email:lemail.value,password:lpass.value})});await loadMe();notice(\'Login successful\');show(\'dashboard\')}catch(e){notice(e.message,true)}}\nasync function logout(){await api(\'/api/logout\',{method:\'POST\'});me=null;renderNav();show(\'home\');notice(\'Logged out\')}\nasync function loadTasks(){const d=await api(\'/api/tasks\');$(\'tasklist\').innerHTML=d.tasks.map(t=>`<div class="card task"><div class="row"><b>${esc(t.title)}</b><span class="tag">${money(t.reward)}</span></div><p class="muted">${esc(t.description)}</p>${me?`<textarea id="proof${t.id}" placeholder="Enter truthful proof/details"></textarea><button class="primary" onclick="submitTask(${t.id})">Submit for review</button>`:`<button onclick="show(\'auth\')">Login to submit</button>`}</div>`).join(\'\')||\'<div class="card">No active tasks right now.</div>\'}\nasync function submitTask(id){try{await api(\'/api/tasks/submit\',{method:\'POST\',body:JSON.stringify({task_id:id,proof:$(\'proof\'+id).value})});notice(\'Task submitted for admin review\');loadTasks()}catch(e){notice(e.message,true)}}\nasync function loadWallet(){await loadMe();const d=await api(\'/api/wallet\');$(\'walletBalance\').textContent=money(d.balance);$(\'tx\').innerHTML=d.transactions.map(x=>`<tr><td>${esc(x.kind)}</td><td>${money(x.amount)}</td><td>${esc(x.note)}</td><td>${new Date(x.created_at*1000).toLocaleString()}</td></tr>`).join(\'\')||\'<tr><td colspan="4">No transactions yet.</td></tr>\'}\nasync function withdraw(){try{const d=await api(\'/api/withdraw\',{method:\'POST\',body:JSON.stringify({amount:$(\'wamount\').value,method:$(\'wmethod\').value,account_name:$(\'wname\').value,account_number:$(\'wnumber\').value})});notice(d.message);await loadMe();show(\'dashboard\')}catch(e){notice(e.message,true)}}\nasync function loadAdmin(){try{const d=await api(\'/api/admin/summary\');$(\'adminStats\').innerHTML=`<div class="card"><div class="muted">Users</div><div class="metric">${d.users}</div></div><div class="card"><div class="muted">Pending submissions</div><div class="metric">${d.pending_submissions}</div></div><div class="card"><div class="muted">Pending withdrawals</div><div class="metric">${d.pending_withdrawals}</div></div>`;\n$(\'subs\').innerHTML=\'<table><tr><th>ID</th><th>User</th><th>Task</th><th>Reward</th><th>Status/action</th></tr>\'+d.submissions.map(s=>`<tr><td>${s.id}</td><td>${esc(s.name)}</td><td>${esc(s.title)}</td><td>${money(s.reward)}</td><td>${s.status===\'pending\'?`<button onclick="reviewSub(${s.id},\'approve\')">Approve</button> <button class="danger" onclick="reviewSub(${s.id},\'reject\')">Reject</button>`:esc(s.status)}</td></tr>`).join(\'\')+\'</table>\';\n$(\'withdrawals\').innerHTML=\'<table><tr><th>ID</th><th>User</th><th>Amount</th><th>Method</th><th>Account</th><th>Status/action</th></tr>\'+d.withdrawals.map(w=>`<tr><td>${w.id}</td><td>${esc(w.name)}</td><td>${money(w.amount)}</td><td>${esc(w.method)}</td><td>${esc(w.account_number)}</td><td>${w.status===\'pending\'?`<button onclick="reviewW(${w.id},\'approve\')">Approve</button> <button class="danger" onclick="reviewW(${w.id},\'reject\')">Reject</button>`:esc(w.status)}</td></tr>`).join(\'\')+\'</table>`}catch(e){notice(e.message,true)}}\nasync function reviewSub(id,decision){try{await api(\'/api/admin/review-submission\',{method:\'POST\',body:JSON.stringify({submission_id:id,decision})});notice(\'Submission updated\');loadAdmin()}catch(e){notice(e.message,true)}}\nasync function reviewW(id,decision){try{await api(\'/api/admin/review-withdrawal\',{method:\'POST\',body:JSON.stringify({withdrawal_id:id,decision})});notice(\'Withdrawal updated\');loadAdmin()}catch(e){notice(e.message,true)}}\nfunction renderAccount(){if(me)$(\'accountInfo\').innerHTML=`<p><b>Name:</b> ${esc(me.name)}</p><p><b>Email:</b> ${esc(me.email)}</p><p><b>Role:</b> ${esc(me.role)}</p><p><b>Referral code:</b> ${esc(me.referral_code)}</p><p><b>Balance:</b> ${money(me.balance)}</p>`}\nloadMe().then(()=>show(me?\'dashboard\':\'home\'));\n</script>\n</body>\n</html>'
HOST, PORT = "0.0.0.0", int(os.environ.get("PORT", "8000"))
MIN_WITHDRAW = 1000

def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    return c

def init_db():
    c = db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL,
      email TEXT UNIQUE NOT NULL,
      password_hash TEXT NOT NULL,
      referral_code TEXT UNIQUE NOT NULL,
      referred_by INTEGER,
      role TEXT NOT NULL DEFAULT 'user',
      balance INTEGER NOT NULL DEFAULT 0,
      created_at INTEGER NOT NULL,
      FOREIGN KEY(referred_by) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS tasks(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      title TEXT NOT NULL,
      description TEXT NOT NULL,
      reward INTEGER NOT NULL CHECK(reward > 0),
      active INTEGER NOT NULL DEFAULT 1,
      created_at INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS submissions(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL,
      task_id INTEGER NOT NULL,
      proof TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'pending',
      created_at INTEGER NOT NULL,
      reviewed_at INTEGER,
      FOREIGN KEY(user_id) REFERENCES users(id),
      FOREIGN KEY(task_id) REFERENCES tasks(id)
    );
    CREATE TABLE IF NOT EXISTS transactions(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL,
      kind TEXT NOT NULL,
      amount INTEGER NOT NULL,
      note TEXT NOT NULL,
      created_at INTEGER NOT NULL,
      FOREIGN KEY(user_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS withdrawals(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL,
      amount INTEGER NOT NULL,
      method TEXT NOT NULL,
      account_name TEXT NOT NULL,
      account_number TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'pending',
      created_at INTEGER NOT NULL,
      reviewed_at INTEGER,
      FOREIGN KEY(user_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS sessions(
      token TEXT PRIMARY KEY,
      user_id INTEGER NOT NULL,
      expires_at INTEGER NOT NULL,
      FOREIGN KEY(user_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS audit_logs(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      actor_id INTEGER,
      action TEXT NOT NULL,
      details TEXT NOT NULL,
      created_at INTEGER NOT NULL
    );
    """)
    if c.execute("SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0] == 0:
        salt = secrets.token_hex(16)
        ph = hashlib.scrypt(b"Admin123!", salt=salt.encode(), n=16384, r=8, p=1).hex()
        c.execute("INSERT INTO users(name,email,password_hash,referral_code,role,created_at) VALUES(?,?,?,?,?,?)",
                  ("Nigeria206 Admin","admin@Nigeria206.test",salt+":"+ph,"ADMIN2006","admin",int(time.time())))
    if c.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0:
        now=int(time.time())
        c.executemany("INSERT INTO tasks(title,description,reward,created_at) VALUES(?,?,?,?)", [
            ("Daily app research","Complete a short research task and submit a truthful proof note.",300,now),
            ("Social engagement task","Follow the stated campaign instruction and submit the requested proof.",250,now),
            ("Content feedback","Read the supplied content and send a useful feedback response.",500,now),
        ])
    c.commit(); c.close()

def hash_password(password):
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1).hex()
    return salt+":"+digest

def verify_password(password, stored):
    try:
        salt,digest=stored.split(":",1)
        check=hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1).hex()
        return hmac.compare_digest(check,digest)
    except Exception:
        return False

def json_out(handler, data, status=200):
    raw=json.dumps(data).encode()
    handler.send_response(status)
    handler.send_header("Content-Type","application/json; charset=utf-8")
    handler.send_header("Content-Length",str(len(raw)))
    handler.end_headers(); handler.wfile.write(raw)

def body(handler):
    n=int(handler.headers.get("Content-Length","0"))
    return json.loads(handler.rfile.read(n) or b"{}")

def now(): return int(time.time())

def current_user(handler):
    jar=cookies.SimpleCookie(handler.headers.get("Cookie",""))
    token=jar.get("session")
    if not token: return None
    c=db()
    row=c.execute("""SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id
                     WHERE s.token=? AND s.expires_at>?""",(token.value,now())).fetchone()
    c.close()
    return row

def require_user(handler):
    u=current_user(handler)
    if not u:
        json_out(handler,{"error":"Login required"},401); return None
    return u

def audit(actor, action, details):
    c=db(); c.execute("INSERT INTO audit_logs(actor_id,action,details,created_at) VALUES(?,?,?,?)",
                      (actor,action,details,now())); c.commit(); c.close()

class App(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args): pass

    def do_GET(self):
        path=urllib.parse.urlparse(self.path).path
        if path=="/health":
            return json_out(self,{"status":"ok","service":"Nigeria206"})
        if path=="/api/me":
            u=current_user(self)
            if not u: return json_out(self,{"user":None})
            return json_out(self,{"user":{"id":u["id"],"name":u["name"],"email":u["email"],"role":u["role"],"balance":u["balance"],"referral_code":u["referral_code"]}})
        if path=="/api/tasks":
            c=db(); rows=c.execute("SELECT id,title,description,reward FROM tasks WHERE active=1 ORDER BY id DESC").fetchall()
            c.close(); return json_out(self,{"tasks":[dict(x) for x in rows]})
        if path=="/api/wallet":
            u=require_user(self)
            if not u:return
            c=db(); rows=c.execute("SELECT kind,amount,note,created_at FROM transactions WHERE user_id=? ORDER BY id DESC LIMIT 50",(u["id"],)).fetchall()
            c.close(); return json_out(self,{"balance":u["balance"],"transactions":[dict(x) for x in rows]})
        if path=="/api/admin/summary":
            u=require_user(self)
            if not u:return
            if u["role"]!="admin": return json_out(self,{"error":"Admin only"},403)
            c=db()
            out={
              "users":c.execute("SELECT COUNT(*) FROM users WHERE role='user'").fetchone()[0],
              "pending_submissions":c.execute("SELECT COUNT(*) FROM submissions WHERE status='pending'").fetchone()[0],
              "pending_withdrawals":c.execute("SELECT COUNT(*) FROM withdrawals WHERE status='pending'").fetchone()[0],
              "withdrawals": [dict(x) for x in c.execute("""SELECT w.*,u.name,u.email FROM withdrawals w JOIN users u ON u.id=w.user_id
                    ORDER BY w.id DESC LIMIT 50""").fetchall()],
              "submissions": [dict(x) for x in c.execute("""SELECT s.*,u.name,t.title,t.reward FROM submissions s
                    JOIN users u ON u.id=s.user_id JOIN tasks t ON t.id=s.task_id
                    ORDER BY s.id DESC LIMIT 50""").fetchall()]
            }
            c.close(); return json_out(self,out)
        if path.startswith("/static/"):
            file=STATIC / path[len("/static/"):]
            if file.is_file():
                data=file.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type","text/css" if file.suffix==".css" else "application/javascript")
                self.send_header("Content-Length",str(len(data))); self.end_headers(); self.wfile.write(data); return
        if path=="/" or path=="/index.html":
            data=INDEX_HTML.encode("utf-8")
            self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8")
            self.send_header("Content-Length",str(len(data))); self.end_headers(); self.wfile.write(data); return
        json_out(self,{"error":"Not found"},404)

    def do_POST(self):
        path=urllib.parse.urlparse(self.path).path
        try: data=body(self)
        except Exception: return json_out(self,{"error":"Invalid JSON"},400)

        if path=="/api/register":
            name=str(data.get("name","")).strip(); email=str(data.get("email","")).strip().lower()
            password=str(data.get("password","")); ref=str(data.get("referral_code","")).strip().upper()
            if len(name)<2 or "@" not in email or len(password)<8:
                return json_out(self,{"error":"Use a valid name, email and password of at least 8 characters."},400)
            c=db()
            if c.execute("SELECT 1 FROM users WHERE email=?",(email,)).fetchone():
                c.close(); return json_out(self,{"error":"Email already registered."},409)
            refrow=c.execute("SELECT id FROM users WHERE referral_code=?",(ref,)).fetchone() if ref else None
            code="U"+secrets.token_hex(4).upper()
            c.execute("""INSERT INTO users(name,email,password_hash,referral_code,referred_by,created_at)
                         VALUES(?,?,?,?,?,?)""",(name,email,hash_password(password),code,refrow["id"] if refrow else None,now()))
            uid=c.execute("SELECT last_insert_rowid()").fetchone()[0]
            c.execute("INSERT INTO audit_logs(actor_id,action,details,created_at) VALUES(?,?,?,?)",(uid,"REGISTER","Account created",now()))
            c.commit(); c.close()
            return json_out(self,{"ok":True,"message":"Account created. Please log in."},201)

        if path=="/api/login":
            email=str(data.get("email","")).strip().lower(); password=str(data.get("password",""))
            c=db(); u=c.execute("SELECT * FROM users WHERE email=?",(email,)).fetchone()
            if not u or not verify_password(password,u["password_hash"]):
                c.close(); return json_out(self,{"error":"Invalid email or password."},401)
            token=secrets.token_urlsafe(32); c.execute("INSERT INTO sessions VALUES(?,?,?)",(token,u["id"],now()+7*86400)); c.commit(); c.close()
            self.send_response(200); self.send_header("Content-Type","application/json")
            self.send_header("Set-Cookie",f"session={token}; HttpOnly; SameSite=Lax; Path=/; Max-Age=604800")
            raw=json.dumps({"ok":True}).encode(); self.send_header("Content-Length",str(len(raw))); self.end_headers(); self.wfile.write(raw); return

        if path=="/api/logout":
            jar=cookies.SimpleCookie(self.headers.get("Cookie","")); token=jar.get("session")
            c=db()
            if token: c.execute("DELETE FROM sessions WHERE token=?",(token.value,))
            c.commit(); c.close()
            self.send_response(200); self.send_header("Content-Type","application/json")
            self.send_header("Set-Cookie","session=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0")
            raw=b'{"ok":true}'; self.send_header("Content-Length",str(len(raw))); self.end_headers(); self.wfile.write(raw); return

        u=require_user(self)
        if not u:return

        if path=="/api/tasks/submit":
            try: tid=int(data["task_id"]); proof=str(data["proof"]).strip()
            except: return json_out(self,{"error":"Task and proof are required."},400)
            if len(proof)<5 or len(proof)>2000: return json_out(self,{"error":"Proof must be 5-2000 characters."},400)
            c=db()
            task=c.execute("SELECT * FROM tasks WHERE id=? AND active=1",(tid,)).fetchone()
            dup=c.execute("SELECT 1 FROM submissions WHERE user_id=? AND task_id=? AND status IN ('pending','approved')",(u["id"],tid)).fetchone()
            if not task: c.close(); return json_out(self,{"error":"Task not found."},404)
            if dup: c.close(); return json_out(self,{"error":"You already submitted this task."},409)
            c.execute("INSERT INTO submissions(user_id,task_id,proof,created_at) VALUES(?,?,?,?)",(u["id"],tid,proof,now()))
            c.commit(); c.close(); return json_out(self,{"ok":True,"message":"Submitted for admin review."},201)

        if path=="/api/withdraw":
            try: amount=int(data["amount"])
            except: return json_out(self,{"error":"Enter a valid amount."},400)
            method=str(data.get("method","OPay")).strip(); account_name=str(data.get("account_name","")).strip()
            account_number=re.sub(r"\D","",str(data.get("account_number","")))
            if amount<MIN_WITHDRAW:return json_out(self,{"error":f"Minimum withdrawal is ₦{MIN_WITHDRAW:,}."},400)
            if len(account_number)<8:return json_out(self,{"error":"Enter a valid account/wallet number."},400)
            c=db(); fresh=c.execute("SELECT balance FROM users WHERE id=?",(u["id"],)).fetchone()
            if amount>fresh["balance"]: c.close(); return json_out(self,{"error":"Insufficient available balance."},400)
            c.execute("UPDATE users SET balance=balance-? WHERE id=?",(amount,u["id"]))
            c.execute("""INSERT INTO withdrawals(user_id,amount,method,account_name,account_number,created_at)
                         VALUES(?,?,?,?,?,?)""",(u["id"],amount,method,account_name,account_number,now()))
            c.execute("""INSERT INTO transactions(user_id,kind,amount,note,created_at) VALUES(?,?,?,?,?)""",
                      (u["id"],"withdrawal_hold",-amount,f"Withdrawal request #{c.execute('SELECT last_insert_rowid()').fetchone()[0]}",now()))
            c.commit(); c.close(); return json_out(self,{"ok":True,"message":"Withdrawal request submitted for review."},201)

        if path=="/api/admin/review-submission":
            if u["role"]!="admin": return json_out(self,{"error":"Admin only"},403)
            sid=int(data.get("submission_id",0)); decision=data.get("decision")
            if decision not in ("approve","reject"): return json_out(self,{"error":"Invalid decision."},400)
            c=db(); s=c.execute("""SELECT s.*,t.reward FROM submissions s JOIN tasks t ON t.id=s.task_id WHERE s.id=?""",(sid,)).fetchone()
            if not s or s["status"]!="pending": c.close(); return json_out(self,{"error":"Submission unavailable."},409)
            c.execute("UPDATE submissions SET status=?,reviewed_at=? WHERE id=?",("approved" if decision=="approve" else "rejected",now(),sid))
            if decision=="approve":
                c.execute("UPDATE users SET balance=balance+? WHERE id=?",(s["reward"],s["user_id"]))
                c.execute("INSERT INTO transactions(user_id,kind,amount,note,created_at) VALUES(?,?,?,?,?)",(s["user_id"],"task_reward",s["reward"],f"Approved task #{s['task_id']}",now()))
            c.commit(); c.close(); audit(u["id"],"REVIEW_SUBMISSION",f"{sid}:{decision}")
            return json_out(self,{"ok":True})

        if path=="/api/admin/review-withdrawal":
            if u["role"]!="admin": return json_out(self,{"error":"Admin only"},403)
            wid=int(data.get("withdrawal_id",0)); decision=data.get("decision")
            if decision not in ("approve","reject"): return json_out(self,{"error":"Invalid decision."},400)
            c=db(); w=c.execute("SELECT * FROM withdrawals WHERE id=?",(wid,)).fetchone()
            if not w or w["status"]!="pending": c.close(); return json_out(self,{"error":"Withdrawal unavailable."},409)
            c.execute("UPDATE withdrawals SET status=?,reviewed_at=? WHERE id=?",("approved" if decision=="approve" else "rejected",now(),wid))
            if decision=="reject":
                c.execute("UPDATE users SET balance=balance+? WHERE id=?",(w["amount"],w["user_id"]))
                c.execute("INSERT INTO transactions(user_id,kind,amount,note,created_at) VALUES(?,?,?,?,?)",(w["user_id"],"withdrawal_refund",w["amount"],f"Rejected withdrawal #{wid}",now()))
            c.commit(); c.close(); audit(u["id"],"REVIEW_WITHDRAWAL",f"{wid}:{decision}")
            return json_out(self,{"ok":True})

        json_out(self,{"error":"Unknown endpoint"},404)

if __name__=="__main__":
    init_db()
    print(f"Nigeria206 running at http://{HOST}:{PORT}")
    print("Demo admin: admin@Nigeria206.test / Admin123!")
    http.server.ThreadingHTTPServer((HOST,PORT),App).serve_forever()
