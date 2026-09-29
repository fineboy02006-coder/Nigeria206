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
HOST, PORT = "127.0.0.1", 8000
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
            data=(STATIC/"index.html").read_bytes()
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
