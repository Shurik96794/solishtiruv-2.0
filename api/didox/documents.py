"""Read-only Didox invoice endpoint. Configure DIDOX_ACCESS_KEY and DIDOX_FIRMS_JSON in Vercel."""
import os, json, re, time, hmac, urllib.request, urllib.error
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, quote

BASE="https://api2.didox.uz"
class ApiError(Exception): pass

def request(path, token=None, password=None):
    headers={"Accept":"application/json","Accept-Language":"uz","User-Agent":"Mozilla/5.0"}
    if token: headers["user-key"]=token
    data=None
    if password is not None:
        data=json.dumps({"password":password}).encode()
        headers["Content-Type"]="application/json"
    for attempt in range(3):
        try:
            req=urllib.request.Request(BASE+path,data=data,headers=headers,method="POST" if data else "GET")
            with urllib.request.urlopen(req,timeout=25) as res:
                return json.loads(res.read(12_000_000).decode())
        except urllib.error.HTTPError as e:
            if e.code in (401,403,423): raise ApiError("Didox kirishni rad etdi ("+str(e.code)+")")
            if e.code in (400,422): raise ApiError("Didox login/parolni rad etdi")
            if e.code not in (429,500,502,503,504) or attempt==2: raise ApiError("Didox HTTP "+str(e.code))
        except (urllib.error.URLError,TimeoutError) as e:
            if attempt==2: raise ApiError("Didox tarmoq xatosi")
        time.sleep(1.5*(attempt+1))
    raise ApiError("Didox so‘rovi bajarilmadi")

def text(v): return str(v or "").strip()
def number(v):
    try:return float(v or 0)
    except (ValueError,TypeError):return 0.0

def parse_doc(item, body):
    obj=body.get("data",body)
    if isinstance(obj,dict) and "json" in obj:
        obj=obj["json"]
    if isinstance(obj,str):
        try:obj=json.loads(obj)
        except ValueError:return None
    if not isinstance(obj,dict):return None
    typ=text(item.get("doctype"))
    fd=obj.get("facturadoc") or obj.get("hybridinvoicedoc") or {}
    productlist=obj.get("productlist") or {}
    products=productlist.get("products") or []
    if typ=="023" and not products:
        for group in (obj.get("roadway") or {}).get("productgroups") or []:
            products.extend((group.get("productinfo") or {}).get("products") or [])
    lines=[]
    for p in products:
        nm=text(p.get("name"));q=number(p.get("amount") if typ=="023" else p.get("count"));sm=number(p.get("deliverysumwithvat"))
        unit=text(p.get("packagename"));mxik=text(p.get("catalogcode"));low=(unit+" "+nm).lower()
        if not nm or q<=0 or sm==0:continue
        if "услуг" in low or "xizmat" in low or "хизмат" in low or mxik.startswith("10"):continue
        if any(x in low for x in ("киловатт","квт","kvt","гкал","gkal")):continue
        if ("куб" in unit.lower() or "m3" in unit.lower()) and any(x in nm.lower() for x in ("suv","газ","gaz","вод","канал","электр")):continue
        marks=p.get("marks") or []
        lines.append({"nm":nm,"q":q,"sum_q":sm,"u":round(sm/q,4),"mxik":mxik,"mxik_nom":text(p.get("catalogname")),"bar":text(p.get("barcode")),"unit":unit,"kiz":marks})
    if not lines:return None
    seller=obj.get("seller") or {};buyer=obj.get("buyer") or {}
    no=text(fd.get("facturano") or fd.get("no"));day=text(fd.get("facturadate") or fd.get("date"))[:10]
    if not no or not day:return None
    contract=obj.get("contractdoc") or {}
    return {"didox_id":text(item.get("doc_id")),"f_no":no,"f_sana":day,"supplier":text(seller.get("name") or item.get("partnerCompany")),"s_inn":text(obj.get("sellertin") or seller.get("tinorpinfl") or item.get("partnerTin")),"buyer":text(buyer.get("name")),"b_inn":text(obj.get("buyertin") or buyer.get("tinorpinfl") or item.get("usersTaxId")),"b_branch":text(buyer.get("branchname")),"sh_no":text(contract.get("contractno") or contract.get("no")),"sh_sana":text(contract.get("contractdate") or contract.get("date"))[:10],"jami":round(sum(x["sum_q"] for x in lines),2),"doc_status":item.get("doc_status"),"lines":lines}

def collect(inn, start, end, firm):
    token=text(firm.get("token"))
    if not token:
        password=text(firm.get("password"))
        if not password:raise ApiError("Firma tokeni yoki paroli sozlanmagan")
        login=request("/v1/auth/"+quote(inn)+"/password/uz",password=password)
        token=text(login.get("token") or (login.get("data") or {}).get("token") or (login.get("user") or {}).get("token"))
        if not token:raise ApiError("Didox token qaytarmadi")
    docs=[];seen=set()
    # Hard limits protect serverless runtime; incomplete reads return an explicit error.
    for suffix in ("","&status=60"):
        for page in range(1,6):
            result=request("/v2/documents?page="+str(page)+"&limit=100&owner=0"+suffix,token)
            data=result.get("data") or []
            if isinstance(data,dict):data=data.get("items") or data.get("documents") or []
            if not isinstance(data,list):raise ApiError("Didox ro‘yxat formati noma’lum")
            for item in data:
                if not isinstance(item,dict):continue
                docid=text(item.get("doc_id"));dt=text(item.get("doc_date"))[:10]
                if not docid or docid in seen or text(item.get("doctype")).zfill(3) not in ("001","002","008","023"):continue
                if start<=dt<=end:
                    seen.add(docid)
                    if len(seen)>80:raise ApiError("80 tadan ko‘p faktura: davrni qisqartiring")
                    detail=request("/v1/documents/"+quote(docid,safe="")+"?owner=0",token)
                    parsed=parse_doc(item,detail)
                    if parsed:docs.append(parsed)
            if len(data)<100:break
            if page==5:raise ApiError("Sahifalar chegarasi: davrni qisqartiring")
    return docs

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        path=urlparse(self.path).path
        if path not in ("/api/didox/login","/api/didox/documents"):
            return self.send_json(404,{"error":"Manzil topilmadi"})
        try:
            length=int(self.headers.get("Content-Length","0"))
            if length<=0 or length>4096:raise ValueError("So‘rov hajmi noto‘g‘ri")
            data=json.loads(self.rfile.read(length))
            inn=text(data.get("inn"));password=data.get("password")
            if not re.fullmatch(r"\d{9}",inn):raise ValueError("STIR 9 raqamdan iborat bo‘lishi kerak")
            if not isinstance(password,str) or not password:raise ValueError("Didox parolini kiriting")
            if path.endswith("/login"):
                token=self.login(inn,password)
                if not token:raise ApiError("Didox token qaytarmadi")
                return self.send_json(200,{"ok":True,"inn":inn})
            start=text(data.get("date_from"));end=text(data.get("date_to"))
            first=date.fromisoformat(start);last=date.fromisoformat(end)
            if last<first or (last-first).days>31:raise ValueError("Sana oralig‘i 31 kundan oshmasin")
            token=self.login(inn,password)
            return self.send_json(200,{"docs":collect(inn,start,end,{"token":token})})
        except (ValueError,KeyError,TypeError):self.send_json(400,{"error":"STIR, parol yoki sana ma’lumotlari noto‘g‘ri"})
        except ApiError as e:self.send_json(502,{"error":str(e)})
        except Exception:self.send_json(500,{"error":"Serverda ichki xatolik"})
    def login(self,inn,password):
        login=request("/v1/auth/"+quote(inn)+"/password/uz",password=password)
        return text(login.get("token") or (login.get("data") or {}).get("token") or (login.get("user") or {}).get("token"))
    def send_json(self,status,data):
        raw=json.dumps(data,ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Cache-Control","no-store")
        self.send_header("Content-Length",str(len(raw)))
        self.end_headers();self.wfile.write(raw)
