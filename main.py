#!/usr/bin/env python3
"""Nigeria206 v6 production-oriented task/rewards scaffold.

Still not a payment processor. Real payouts must be confirmed by a legitimate
provider or by a documented manual transfer before a withdrawal is marked paid.
"""
import hashlib, hmac, http.server, json, os, re, secrets, sqlite3, time, urllib.parse
from http import cookies
from pathlib import Path

BASE = Path(__file__).resolve().parent
volume = os.environ.get("RAILWAY_VOLUME_MOUNT_PATH")
DATA_DIR = Path(volume) if volume else (BASE / "data")
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB = DATA_DIR / "nigeria206.db"
STATIC = BASE / "static"
HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", "8000"))
MIN_WITHDRAW = 1000
SESSION_DAYS = 7
RATE = {}
RATE_WINDOW = 60
RATE_LIMIT = 60


def db():
    c = sqlite3.connect(DB, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    c.execute("PRAGMA journal_mode = WAL")
    c.execute("PRAGMA busy_timeout = 10000")
    return c


def now(): return int(time.time())


def hash_password(password):
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=salt.encode(), n=32768, r=8, p=1).hex()
    return salt + ":" + digest


def verify_password(password, stored):
    try:
        salt, digest = stored.split(":", 1)
        check = hashlib.scrypt(password.encode(), salt=salt.encode(), n=32768, r=8, p=1).hex()
        return hmac.compare_digest(check, digest)
    except Exception:
        return False


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
      daily_limit INTEGER NOT NULL DEFAULT 0,
      created_at INTEGER NOT NULL,
      updated_at INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS submissions(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL,
      task_id INTEGER NOT NULL,
      proof TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'pending',
      created_at INTEGER NOT NULL,
      reviewed_at INTEGER,
      reviewer_id INTEGER,
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
      provider_ref TEXT NOT NULL DEFAULT '',
      admin_note TEXT NOT NULL DEFAULT '',
      created_at INTEGER NOT NULL,
      reviewed_at INTEGER,
      FOREIGN KEY(user_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS sessions(
      token TEXT PRIMARY KEY,
      user_id INTEGER NOT NULL,
      csrf_token TEXT NOT NULL,
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
    # Safe migrations for databases created by earlier versions.
    cols = {r[1] for r in c.execute("PRAGMA table_info(tasks)").fetchall()}
    if "daily_limit" not in cols: c.execute("ALTER TABLE tasks ADD COLUMN daily_limit INTEGER NOT NULL DEFAULT 0")
    if "updated_at" not in cols: c.execute("ALTER TABLE tasks ADD COLUMN updated_at INTEGER NOT NULL DEFAULT 0")
    wcols = {r[1] for r in c.execute("PRAGMA table_info(withdrawals)").fetchall()}
    if "provider_ref" not in wcols: c.execute("ALTER TABLE withdrawals ADD COLUMN provider_ref TEXT NOT NULL DEFAULT ''")
    if "admin_note" not in wcols: c.execute("ALTER TABLE withdrawals ADD COLUMN admin_note TEXT NOT NULL DEFAULT ''")
    scols = {r[1] for r in c.execute("PRAGMA table_info(sessions)").fetchall()}
    if "csrf_token" not in scols: c.execute("ALTER TABLE sessions ADD COLUMN csrf_token TEXT NOT NULL DEFAULT ''")
    
    admin_count = c.execute("SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0]
    admin_email = os.environ.get("ADMIN_EMAIL", "").strip().lower()
    admin_password = os.environ.get("ADMIN_PASSWORD", "")
    if admin_count == 0 and admin_email and len(admin_password) >= 12 and "@" in admin_email:
        c.execute("INSERT INTO users(name,email,password_hash,referral_code,role,created_at) VALUES(?,?,?,?,?,?)",
                  ("Nigeria206 Admin", admin_email, hash_password(admin_password), "ADMIN206", "admin", now()))
    if c.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0:
        t = now()
        c.executemany("INSERT INTO tasks(title,description,reward,active,daily_limit,created_at,updated_at) VALUES(?,?,?,?,?,?,?)", [
            ("Daily app research", "Complete a short research task and submit truthful proof.", 300, 1, 0, t, t),
            ("Social engagement task", "Follow a legitimate campaign instruction and submit the requested proof.", 250, 1, 0, t, t),
            ("Content feedback", "Read the supplied content and send useful feedback.", 500, 1, 0, t, t),
        ])
    c.commit(); c.close()


def json_out(h, data, status=200, extra=None):
    raw = json.dumps(data).encode()
    h.send_response(status)
    h.send_header("Content-Type", "application/json; charset=utf-8")
    h.send_header("Content-Length", str(len(raw)))
    for k,v in (extra or {}).items(): h.send_header(k, v)
    h.end_headers(); h.wfile.write(raw)


def body(h):
    n = int(h.headers.get("Content-Length", "0"))
    if n > 100_000: raise ValueError("Body too large")
    return json.loads(h.rfile.read(n) or b"{}")


def audit(actor, action, details):
    c = db(); c.execute("INSERT INTO audit_logs(actor_id,action,details,created_at) VALUES(?,?,?,?)", (actor,action,details,now())); c.commit(); c.close()


def current_session(h):
    jar = cookies.SimpleCookie(h.headers.get("Cookie", "")); token = jar.get("session")
    if not token: return None
    c = db(); row = c.execute("SELECT s.*,u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=? AND s.expires_at>?", (token.value,now())).fetchone(); c.close()
    return row


def current_user(h):
    s = current_session(h)
    return s


def require_user(h):
    u = current_user(h)
    if not u: json_out(h,{"error":"Login required"},401); return None
    return u


def csrf_ok(h):
    s = current_session(h)
    if not s: return False
    return h.headers.get("X-CSRF-Token", "") == s["csrf_token"]


def client_ip(h): return h.client_address[0] if h.client_address else "unknown"


def rate_ok(h):
    key = client_ip(h); t = now(); hits = RATE.get(key, [])
    hits = [x for x in hits if x > t - RATE_WINDOW]
    if len(hits) >= RATE_LIMIT: RATE[key] = hits; return False
    hits.append(t); RATE[key] = hits; return True


def common_headers(h):
    h.send_header("X-Content-Type-Options", "nosniff")
    h.send_header("X-Frame-Options", "DENY")
    h.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
    h.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'")


class App(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args): pass

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/health": return json_out(self,{"status":"ok","service":"Nigeria206","db":"ready"})
        if path == "/api/me":
            u = current_user(self)
            if not u: return json_out(self,{"user":None})
            return json_out(self,{"user":{"id":u["id"],"name":u["name"],"email":u["email"],"role":u["role"],"balance":u["balance"],"referral_code":u["referral_code"]},"csrf":u["csrf_token"]})
        if path == "/api/tasks":
            c=db(); rows=c.execute("SELECT id,title,description,reward,daily_limit FROM tasks WHERE active=1 ORDER BY id DESC").fetchall(); c.close()
            return json_out(self,{"tasks":[dict(x) for x in rows]})
        if path == "/api/wallet":
            u=require_user(self)
            if not u:return
            c=db(); tx=c.execute("SELECT kind,amount,note,created_at FROM transactions WHERE user_id=? ORDER BY id DESC LIMIT 100",(u["id"],)).fetchall(); ws=c.execute("SELECT id,amount,method,status,provider_ref,admin_note,created_at FROM withdrawals WHERE user_id=? ORDER BY id DESC LIMIT 30",(u["id"],)).fetchall(); c.close()
            return json_out(self,{"balance":u["balance"],"transactions":[dict(x) for x in tx],"withdrawals":[dict(x) for x in ws]})
        if path == "/api/admin/summary":
            u=require_user(self)
            if not u:return
            if u["role"]!="admin": return json_out(self,{"error":"Admin only"},403)
            c=db(); out={
              "users":c.execute("SELECT COUNT(*) FROM users WHERE role='user'").fetchone()[0],
              "pending_submissions":c.execute("SELECT COUNT(*) FROM submissions WHERE status='pending'").fetchone()[0],
              "pending_withdrawals":c.execute("SELECT COUNT(*) FROM withdrawals WHERE status='pending'").fetchone()[0],
              "processing_withdrawals":c.execute("SELECT COUNT(*) FROM withdrawals WHERE status='processing'").fetchone()[0],
              "tasks":[dict(x) for x in c.execute("SELECT * FROM tasks ORDER BY id DESC").fetchall()],
              "withdrawals":[dict(x) for x in c.execute("SELECT w.*,u.name,u.email FROM withdrawals w JOIN users u ON u.id=w.user_id ORDER BY w.id DESC LIMIT 100").fetchall()],
              "submissions":[dict(x) for x in c.execute("SELECT s.*,u.name,t.title,t.reward FROM submissions s JOIN users u ON u.id=s.user_id JOIN tasks t ON t.id=s.task_id ORDER BY s.id DESC LIMIT 100").fetchall()]
            }; c.close(); return json_out(self,out)
        if path.startswith("/static/"):
            file=STATIC / path[len("/static/"):]
            if file.is_file():
                data=file.read_bytes(); self.send_response(200); self.send_header("Content-Type", "text/css" if file.suffix==".css" else "application/javascript"); self.send_header("Content-Length",str(len(data))); common_headers(self); self.end_headers(); self.wfile.write(data); return
        if path in ("/","/index.html"):
            data=(STATIC/"index.html").read_bytes(); self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Content-Length",str(len(data))); common_headers(self); self.end_headers(); self.wfile.write(data); return
        return json_out(self,{"error":"Not found"},404)

    def do_POST(self):
        if not rate_ok(self): return json_out(self,{"error":"Too many requests. Try again shortly."},429)
        path=urllib.parse.urlparse(self.path).path
        try: data=body(self)
        except Exception: return json_out(self,{"error":"Invalid request."},400)

        if path=="/api/register":
            name=str(data.get("name","")).strip(); email=str(data.get("email","")).strip().lower(); password=str(data.get("password","")); ref=str(data.get("referral_code","")).strip().upper()
            if len(name)<2 or len(name)>100 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+",email) or len(password)<10: return json_out(self,{"error":"Use a valid name, email and password of at least 10 characters."},400)
            c=db()
            if c.execute("SELECT 1 FROM users WHERE email=?",(email,)).fetchone(): c.close(); return json_out(self,{"error":"Email already registered."},409)
            refrow=c.execute("SELECT id FROM users WHERE referral_code=?",(ref,)).fetchone() if ref else None
            code="U"+secrets.token_hex(5).upper()
            c.execute("INSERT INTO users(name,email,password_hash,referral_code,referred_by,created_at) VALUES(?,?,?,?,?,?)",(name,email,hash_password(password),code,refrow["id"] if refrow else None,now()))
            uid=c.execute("SELECT last_insert_rowid()").fetchone()[0]; c.execute("INSERT INTO audit_logs(actor_id,action,details,created_at) VALUES(?,?,?,?)",(uid,"REGISTER","Account created",now())); c.commit(); c.close()
            return json_out(self,{"ok":True,"message":"Account created. Please log in."},201)

        if path=="/api/login":
            email=str(data.get("email","")).strip().lower(); password=str(data.get("password","")); c=db(); u=c.execute("SELECT * FROM users WHERE email=?",(email,)).fetchone()
            if not u or not verify_password(password,u["password_hash"]): c.close(); return json_out(self,{"error":"Invalid email or password."},401)
            token=secrets.token_urlsafe(32); csrf=secrets.token_urlsafe(24); c.execute("INSERT INTO sessions(token,user_id,csrf_token,expires_at) VALUES(?,?,?,?)",(token,u["id"],csrf,now()+SESSION_DAYS*86400)); c.commit(); c.close()
            return json_out(self,{"ok":True},200,{"Set-Cookie":f"session={token}; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age={SESSION_DAYS*86400}"})

        if path=="/api/logout":
            jar=cookies.SimpleCookie(self.headers.get("Cookie","")); token=jar.get("session"); c=db();
            if token: c.execute("DELETE FROM sessions WHERE token=?",(token.value,))
            c.commit(); c.close(); return json_out(self,{"ok":True},200,{"Set-Cookie":"session=; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=0"})

        u=require_user(self)
        if not u:return
        if not csrf_ok(self): return json_out(self,{"error":"Security token expired. Refresh and try again."},403)

        if path=="/api/tasks/submit":
            try: tid=int(data["task_id"]); proof=str(data["proof"]).strip()
            except Exception: return json_out(self,{"error":"Task and proof are required."},400)
            if len(proof)<5 or len(proof)>2000:return json_out(self,{"error":"Proof must be 5-2000 characters."},400)
            c=db(); task=c.execute("SELECT * FROM tasks WHERE id=? AND active=1",(tid,)).fetchone(); dup=c.execute("SELECT 1 FROM submissions WHERE user_id=? AND task_id=? AND status IN ('pending','approved')",(u["id"],tid)).fetchone()
            if not task:c.close();return json_out(self,{"error":"Task not found."},404)
            if dup:c.close();return json_out(self,{"error":"You already submitted this task."},409)
            if task["daily_limit"]:
                since=now()-86400; count=c.execute("SELECT COUNT(*) FROM submissions WHERE task_id=? AND created_at>?",(tid,since)).fetchone()[0]
                if count>=task["daily_limit"]: c.close(); return json_out(self,{"error":"This task has reached its daily submission limit."},409)
            c.execute("INSERT INTO submissions(user_id,task_id,proof,created_at) VALUES(?,?,?,?)",(u["id"],tid,proof,now())); c.commit(); c.close(); return json_out(self,{"ok":True,"message":"Submitted for admin review."},201)

        if path=="/api/withdraw":
            try: amount=int(data["amount"])
            except Exception:return json_out(self,{"error":"Enter a valid amount."},400)
            method=str(data.get("method","OPay")).strip(); account_name=str(data.get("account_name","")).strip(); account_number=re.sub(r"\D","",str(data.get("account_number","")))
            if amount<MIN_WITHDRAW:return json_out(self,{"error":f"Minimum withdrawal is ₦{MIN_WITHDRAW:,}."},400)
            if len(account_name)<2 or len(account_number)<8:return json_out(self,{"error":"Enter valid account details."},400)
            c=db(); fresh=c.execute("SELECT balance FROM users WHERE id=?",(u["id"],)).fetchone()
            if amount>fresh["balance"]:c.close();return json_out(self,{"error":"Insufficient available balance."},400)
            c.execute("UPDATE users SET balance=balance-? WHERE id=?",(amount,u["id"]))
            c.execute("INSERT INTO withdrawals(user_id,amount,method,account_name,account_number,created_at) VALUES(?,?,?,?,?,?)",(u["id"],amount,method,account_name,account_number,now()))
            wid=c.execute("SELECT last_insert_rowid()").fetchone()[0]; c.execute("INSERT INTO transactions(user_id,kind,amount,note,created_at) VALUES(?,?,?,?,?)",(u["id"],"withdrawal_hold",-amount,f"Withdrawal request #{wid}",now())); c.commit(); c.close(); return json_out(self,{"ok":True,"message":"Withdrawal request submitted for review."},201)

        if u["role"]!="admin": return json_out(self,{"error":"Admin only"},403)

        if path=="/api/admin/task":
            action=str(data.get("action","")); title=str(data.get("title","")).strip(); desc=str(data.get("description","")).strip()
            try: reward=int(data.get("reward",0)); daily=int(data.get("daily_limit",0)); tid=int(data.get("task_id",0))
            except Exception:return json_out(self,{"error":"Invalid task values."},400)
            c=db()
            if action=="create":
                if len(title)<3 or not desc or reward<=0 or daily<0:c.close();return json_out(self,{"error":"Enter valid task details."},400)
                c.execute("INSERT INTO tasks(title,description,reward,active,daily_limit,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",(title,desc,reward,1,daily,now(),now()))
            elif action=="update":
                if tid<=0 or len(title)<3 or not desc or reward<=0 or daily<0:c.close();return json_out(self,{"error":"Enter valid task details."},400)
                c.execute("UPDATE tasks SET title=?,description=?,reward=?,daily_limit=?,updated_at=? WHERE id=?",(title,desc,reward,daily,now(),tid))
            elif action=="toggle":
                c.execute("UPDATE tasks SET active=CASE active WHEN 1 THEN 0 ELSE 1 END,updated_at=? WHERE id=?",(now(),tid))
            else:c.close();return json_out(self,{"error":"Unknown task action."},400)
            c.commit();c.close();audit(u["id"],"TASK_ADMIN",action);return json_out(self,{"ok":True})

        if path=="/api/admin/review-submission":
            sid=int(data.get("submission_id",0)); decision=data.get("decision")
            if decision not in ("approve","reject"):return json_out(self,{"error":"Invalid decision."},400)
            c=db(); s=c.execute("SELECT s.*,t.reward FROM submissions s JOIN tasks t ON t.id=s.task_id WHERE s.id=?",(sid,)).fetchone()
            if not s or s["status"]!="pending":c.close();return json_out(self,{"error":"Submission unavailable."},409)
            c.execute("UPDATE submissions SET status=?,reviewed_at=?,reviewer_id=? WHERE id=?",("approved" if decision=="approve" else "rejected",now(),u["id"],sid))
            if decision=="approve":
                c.execute("UPDATE users SET balance=balance+? WHERE id=?",(s["reward"],s["user_id"]));c.execute("INSERT INTO transactions(user_id,kind,amount,note,created_at) VALUES(?,?,?,?,?)",(s["user_id"],"task_reward",s["reward"],f"Approved task #{s['task_id']}",now()))
            c.commit();c.close();audit(u["id"],"REVIEW_SUBMISSION",f"{sid}:{decision}");return json_out(self,{"ok":True})

        if path=="/api/admin/review-withdrawal":
            wid=int(data.get("withdrawal_id",0)); decision=data.get("decision"); note=str(data.get("note","")).strip(); provider_ref=str(data.get("provider_ref","")).strip()
            if decision not in ("approve","reject","paid"):return json_out(self,{"error":"Invalid decision."},400)
            c=db();w=c.execute("SELECT * FROM withdrawals WHERE id=?",(wid,)).fetchone()
            if not w:c.close();return json_out(self,{"error":"Withdrawal unavailable."},409)
            if decision=="approve" and w["status"]!="pending":c.close();return json_out(self,{"error":"Only pending withdrawals can be approved."},409)
            if decision=="paid" and w["status"]!="processing":c.close();return json_out(self,{"error":"Only processing withdrawals can be marked paid."},409)
            if decision=="reject" and w["status"] not in ("pending","processing"):c.close();return json_out(self,{"error":"Withdrawal cannot be rejected now."},409)
            if decision=="approve": new="processing"
            elif decision=="paid": new="paid"
            else:new="rejected"
            c.execute("UPDATE withdrawals SET status=?,reviewed_at=?,provider_ref=?,admin_note=? WHERE id=?",(new,now(),provider_ref,note,wid))
            if decision=="reject":
                c.execute("UPDATE users SET balance=balance+? WHERE id=?",(w["amount"],w["user_id"]));c.execute("INSERT INTO transactions(user_id,kind,amount,note,created_at) VALUES(?,?,?,?,?)",(w["user_id"],"withdrawal_refund",w["amount"],f"Rejected withdrawal #{wid}",now()))
            if decision=="paid":
                c.execute("INSERT INTO transactions(user_id,kind,amount,note,created_at) VALUES(?,?,?,?,?)",(w["user_id"],"withdrawal_paid",0,f"Withdrawal #{wid} marked paid; reference: {provider_ref or 'manual'}",now()))
            c.commit();c.close();audit(u["id"],"REVIEW_WITHDRAWAL",f"{wid}:{decision}:{provider_ref}");return json_out(self,{"ok":True})

        return json_out(self,{"error":"Unknown endpoint"},404)


if __name__ == "__main__":
    init_db()
    print(f"Nigeria206 v6 listening on {HOST}:{PORT}")
    if not os.environ.get("ADMIN_EMAIL") or not os.environ.get("ADMIN_PASSWORD"):
        print("ADMIN_EMAIL/ADMIN_PASSWORD are not set. Existing admin records, if any, remain usable.")
    http.server.ThreadingHTTPServer((HOST,PORT),App).serve_forever()
