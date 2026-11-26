"""Local read-only report server, standard library only."""
import access
import os, sqlite3, secrets, hashlib, hmac, json, time, getpass
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlsplit
ROOT=Path(__file__).resolve().parent
DB=ROOT/'local.sqlite3'
def db():
    c=sqlite3.connect(DB)
    c.execute('CREATE TABLE IF NOT EXISTS users (login TEXT PRIMARY KEY, salt TEXT, digest TEXT, role TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS report (id INTEGER PRIMARY KEY, data TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, login TEXT, expires INTEGER)')
    access.initialize(c)
    c.commit()
    return c
def digest(p,s):
    return hashlib.pbkdf2_hmac('sha256',p.encode(),bytes.fromhex(s),600000).hex()
def user(login,p,role):
    salt=secrets.token_hex(16)
    with db() as c: c.execute('INSERT INTO users VALUES (?,?,?,?)',(login,salt,digest(p,salt),role))
class Handler(BaseHTTPRequestHandler):
    def reply(self,status,data,kind='application/json',cookie=None):
        b=(json.dumps(data,ensure_ascii=False) if kind=='application/json' else data).encode()
        self.send_response(status);self.send_header('Content-Type',kind+'; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
        if cookie:self.send_header('Set-Cookie',cookie)
        self.end_headers();self.wfile.write(b)
    def identity(self):
        from http.cookies import SimpleCookie
        ck=SimpleCookie();ck.load(self.headers.get('Cookie',''))
        token=ck.get('sid')
        if not token:return None
        with db() as c:return c.execute('SELECT u.login,u.role FROM sessions s JOIN users u ON s.login=u.login WHERE token=? AND expires>?',(token.value,int(time.time()))).fetchone()
    def do_GET(self):
        p=urlsplit(self.path).path
        if p=='/':return self.reply(200,(ROOT/'viewer.html').read_text(encoding='utf-8'),'text/html')
        ident=self.identity()
        if not ident:return self.reply(401,{'error':'Kirish kerak'})
        if p=='/api/access':
            with db() as c:
                if ident[1]=='admin':
                    rows=c.execute("SELECT login,role FROM users ORDER BY login").fetchall()
                    grants=c.execute("SELECT login,section,mode FROM section_access").fetchall()
                    return self.reply(200,{'users':[{'login':u,'role':r} for u,r in rows],'grants':[{'login':u,'section':i,'mode':m} for u,i,m in grants]})
                grants=c.execute("SELECT section,mode FROM section_access WHERE login=?",(ident[0],)).fetchall()
                return self.reply(200,{'grants':[{'section':i,'mode':m} for i,m in grants]})
        if p=='/api/me':return self.reply(200,{'login':ident[0],'role':ident[1]})
        if p.startswith('/api/section/'):
            try:
                section=int(p.rsplit('/',1)[1])
                with db() as c: result=access.read(c,ident,section)
                return self.reply(200,result)
            except PermissionError:return self.reply(403,{'error':'Ruxsat yo‘q'})
            except ValueError:return self.reply(400,{'error':'Invalid section'})
        if p=='/api/report':
            with db() as c:r=c.execute('SELECT data FROM report WHERE id=1').fetchone()
            return self.reply(200,json.loads(r[0]) if r else [])
        return self.reply(404,{'error':'Topilmadi'})
    def do_POST(self):
        p=urlsplit(self.path).path
        if self.headers.get('Content-Type','').split(';')[0]!='application/json':return self.reply(415,{'error':'JSON required'})
        try:
            n=int(self.headers.get('Content-Length','0'))
            if not 0<n<=20_000_000:raise ValueError()
            d=json.loads(self.rfile.read(n))
        except Exception:return self.reply(400,{'error':'Invalid data'})
        if p=='/api/login':
            with db() as c:
                r=c.execute('SELECT salt,digest FROM users WHERE login=?',(str(d.get('login','')),)).fetchone()
                if not r or not hmac.compare_digest(r[1],digest(str(d.get('password','')),r[0])):return self.reply(401,{'error':'Login yoki parol xato'})
                t=secrets.token_urlsafe(32);c.execute('INSERT INTO sessions VALUES (?,?,?)',(t,d['login'],int(time.time())+28800))
            return self.reply(200,{'ok':True},cookie='sid='+t+'; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800')
        ident=self.identity()
        if p.startswith('/api/section/'):
            try:
                section=int(p.rsplit('/',1)[1])
                with db() as c: revision=access.write(c,ident,section,d['revision'],d['data'])
                return self.reply(200,{'revision':revision})
            except PermissionError:return self.reply(403,{'error':'Ruxsat yo‘q'})
            except (ValueError,KeyError,TypeError):return self.reply(409,{'error':'Invalid data or revision conflict'})
        if not ident or ident[1]!='admin':return self.reply(403,{'error':'Ruxsat yo‘q'})
        if p=='/api/access':
            try:
                with db() as c: access.grant(c,ident,str(d['login']),int(d['section']),d.get('mode'))
                return self.reply(200,{'ok':True})
            except (ValueError,KeyError,TypeError):return self.reply(400,{'error':'Invalid permission'})
        if p=='/api/users':
            try:
                login=str(d['login']).strip();pw=str(d['password'])
                if not login or len(pw)<10:raise ValueError()
                user(login,pw,'viewer')
            except Exception:return self.reply(400,{'error':'Login takrorlangan yoki parol 10 belgidan kam'})
            return self.reply(200,{'ok':True})
        if p=='/api/report':
            if not isinstance(d,list) or any(not isinstance(x,dict) for x in d):return self.reply(400,{'error':'Invalid report'})
            rows=[{k:str(x.get(k,'') or '') for k in ('name','uprName','barcode','effectiveBarcode','status')} for x in d]
            with db() as c:c.execute('INSERT OR REPLACE INTO report VALUES (1,?)',(json.dumps(rows,ensure_ascii=False),))
            return self.reply(200,{'ok':True})
        return self.reply(404,{'error':'Topilmadi'})
if __name__=='__main__':
    with db() as c: exists=c.execute("SELECT 1 FROM users WHERE role='admin'").fetchone()
    if not exists:
        p=getpass.getpass('Admin password (min 10): ')
        if len(p)<10:raise SystemExit('Password too short')
        user('admin',p,'admin')
    print('Local server: http://localhost:8765')
    ThreadingHTTPServer(('0.0.0.0',8765),Handler).serve_forever()
