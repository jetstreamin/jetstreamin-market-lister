#!/usr/bin/env python3
import argparse, base64, datetime as dt, json, mimetypes, os, pathlib, shutil, sqlite3, subprocess, sys, threading, urllib.request, uuid
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

ROOT = pathlib.Path(__file__).resolve().parent
DATA = pathlib.Path(os.environ.get("JETSTREAMIN_DATA", ROOT / "data"))
DB = DATA / "catalog.db"
PHOTOS = DATA / "photos"
EXPORTS = DATA / "exports"
STATIC = ROOT / "web"
for p in (DATA, PHOTOS, EXPORTS): p.mkdir(parents=True, exist_ok=True)

SCHEMA = """
CREATE TABLE IF NOT EXISTS items(id TEXT PRIMARY KEY, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, title TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '', condition_text TEXT NOT NULL DEFAULT '', category TEXT NOT NULL DEFAULT '', price REAL NOT NULL DEFAULT 3, quantity INTEGER NOT NULL DEFAULT 1, shipping TEXT NOT NULL DEFAULT 'Calculated shipping', notes TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'draft');
CREATE TABLE IF NOT EXISTS photos(id TEXT PRIMARY KEY, item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE, path TEXT NOT NULL, position INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS auctions(id TEXT PRIMARY KEY, item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE, platform TEXT NOT NULL DEFAULT 'facebook', start_price REAL NOT NULL DEFAULT 3, increment REAL NOT NULL DEFAULT 1, ends_at TEXT, status TEXT NOT NULL DEFAULT 'open');
CREATE TABLE IF NOT EXISTS bids(id INTEGER PRIMARY KEY AUTOINCREMENT, auction_id TEXT NOT NULL REFERENCES auctions(id) ON DELETE CASCADE, bidder TEXT NOT NULL, amount REAL NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_items_updated_at ON items(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_bids_auction_amount ON bids(auction_id, amount DESC, created_at ASC);
"""

def db():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; c.execute("PRAGMA foreign_keys=ON"); c.executescript(SCHEMA); return c
def now(): return dt.datetime.now(dt.timezone.utc).isoformat()
def rowdict(r): return dict(r) if r else None
def item_full(item_id):
    with db() as c:
        i=rowdict(c.execute("SELECT * FROM items WHERE id=?",(item_id,)).fetchone())
        if not i:return None
        i["photos"]=[dict(x) for x in c.execute("SELECT id,path,position FROM photos WHERE item_id=? ORDER BY position",(item_id,))]
        a=c.execute("SELECT * FROM auctions WHERE item_id=? ORDER BY rowid DESC LIMIT 1",(item_id,)).fetchone()
        i["auction"]=rowdict(a)
        if a:i["auction"]["bids"]=[dict(x) for x in c.execute("SELECT * FROM bids WHERE auction_id=? ORDER BY amount DESC,created_at ASC",(a["id"],))]
        return i
def channel_payload(i, channel):
    photos=[f"/photos/{pathlib.Path(p['path']).name}" for p in i.get("photos",[])]
    base={"source":"Jetstreamin Market Lister","sku":i["id"],"title":i["title"],"description":i["description"],"condition":i["condition_text"],"category":i["category"],"price":i["price"],"quantity":i["quantity"],"shipping":i["shipping"],"photos":photos}
    if channel=="ebay":
        return {"format":"EBAY_DRAFT_V1","marketplaceId":"EBAY_US","sku":i["id"],"title":i["title"][:80],"description":i["description"],"conditionDescription":i["condition_text"],"categoryHint":i["category"],"pricingSummary":{"price":{"currency":"USD","value":f"{i['price']:.2f}"}},"availableQuantity":i["quantity"],"shippingProfile":i["shipping"],"localPhotos":photos,"publish":False}
    if channel=="whatnot":
        return {"format":"WHATNOT_DRAFT_V1","title":i["title"],"description":i["description"],"condition":i["condition_text"],"category":i["category"],"quantity":i["quantity"],"start_price":i["price"],"shipping_profile":i["shipping"],"local_photos":photos}
    a=i.get("auction") or {}; end=a.get("ends_at") or "Set closing date/time"
    post=f"{i['title']}\n\n{i['description']}\n\nCondition: {i['condition_text']}\nStarting bid: ${a.get('start_price',i['price']):.2f}\nMinimum increment: ${a.get('increment',1):.2f}\nEnds: {end}\nShipping: {i['shipping']}\n\nBid by commenting with your amount. Highest valid bid at closing wins."
    return {"format":"FACEBOOK_AUCTION_V1","post":post,"auction":a,"item":base}
def ai_analyze(image_path, settings):
    endpoint=settings.get("ollama_url","http://127.0.0.1:11434").rstrip("/")
    model=settings.get("vision_model","qwen3-vl:8b")
    prompt="Analyze this sale item from the photograph. Return strict JSON with title, description, condition_text, category, suggested_price, notes. Never invent hidden details, authentication, grade, rarity, or defects not visible. Title max 80 chars."
    payload=json.dumps({"model":model,"prompt":prompt,"images":[base64.b64encode(pathlib.Path(image_path).read_bytes()).decode()],"stream":False,"format":"json"}).encode()
    req=urllib.request.Request(endpoint+"/api/generate",payload,{"Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=120) as r: out=json.load(r)
    return json.loads(out["response"])
def settings_read():
    p=DATA/"settings.json"
    try:return json.loads(p.read_text())
    except:return {"ollama_url":"http://127.0.0.1:11434","vision_model":"qwen3-vl:8b"}
def settings_write(v): (DATA/"settings.json").write_text(json.dumps(v,indent=2))
def camera(item_id):
    if not shutil.which("termux-camera-photo"): raise RuntimeError("termux-camera-photo is unavailable. Install the Termux:API app and run: pkg install termux-api")
    dest=PHOTOS/f"{item_id}-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}.jpg"
    subprocess.run(["termux-camera-photo","-c","0",str(dest)],check=True)
    return dest

class H(BaseHTTPRequestHandler):
    def log_message(self,fmt,*args): sys.stderr.write("%s %s\n"%(self.address_string(),fmt%args))
    def sendj(self,obj,status=200):
        b=json.dumps(obj,ensure_ascii=False).encode(); self.send_response(status); self.send_header("Content-Type","application/json"); self.send_header("Content-Length",str(len(b))); self.end_headers(); self.wfile.write(b)
    def body(self):
        n=int(self.headers.get("Content-Length",0)); return json.loads(self.rfile.read(n) or b"{}")
    def file(self,p,ctype=None):
        if not p.exists() or not p.is_file():return self.send_error(404)
        b=p.read_bytes(); self.send_response(200); self.send_header("Content-Type",ctype or mimetypes.guess_type(p)[0] or "application/octet-stream"); self.send_header("Content-Length",str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        u=urlparse(self.path); parts=u.path.strip("/").split("/")
        if u.path=="/api/items":
            with db() as c:return self.sendj([dict(x) for x in c.execute("SELECT id,title,price,status,updated_at FROM items ORDER BY updated_at DESC")])
        if len(parts)==3 and parts[:2]==["api","items"]: return self.sendj(item_full(parts[2]) or {"error":"not found"},200 if item_full(parts[2]) else 404)
        if len(parts)==4 and parts[:2]==["api","export"]:
            i=item_full(parts[2]); return self.sendj(channel_payload(i,parts[3]) if i else {"error":"not found"},200 if i else 404)
        if u.path=="/api/settings":return self.sendj(settings_read())
        if parts[0]=="photos" and len(parts)==2:return self.file(PHOTOS/pathlib.Path(parts[1]).name)
        return self.file(STATIC/("index.html" if u.path=="/" else u.path.lstrip("/")))
    def do_POST(self):
        try:
            u=urlparse(self.path); parts=u.path.strip("/").split("/"); data=self.body() if self.headers.get("Content-Type","").startswith("application/json") else {}
            if u.path=="/api/items":
                ident=uuid.uuid4().hex[:12]; t=now()
                with db() as c:c.execute("INSERT INTO items(id,created_at,updated_at,title,price) VALUES(?,?,?,?,?)",(ident,t,t,data.get("title","New item"),float(data.get("price",3))))
                return self.sendj(item_full(ident),201)
            if len(parts)==4 and parts[:2]==["api","items"] and parts[3]=="camera":
                p=camera(parts[2]); pid=uuid.uuid4().hex
                with db() as c:pos=c.execute("SELECT COUNT(*) FROM photos WHERE item_id=?",(parts[2],)).fetchone()[0];c.execute("INSERT INTO photos VALUES(?,?,?,?)",(pid,parts[2],str(p),pos))
                return self.sendj(item_full(parts[2]))
            if len(parts)==4 and parts[:2]==["api","items"] and parts[3]=="analyze":
                i=item_full(parts[2]);
                if not i or not i["photos"]:raise RuntimeError("Take or upload a photo first.")
                out=ai_analyze(i["photos"][0]["path"],settings_read()); return self.sendj(out)
            if len(parts)==4 and parts[:2]==["api","items"] and parts[3]=="auction":
                aid=uuid.uuid4().hex[:12]
                with db() as c:c.execute("INSERT INTO auctions(id,item_id,start_price,increment,ends_at) VALUES(?,?,?,?,?)",(aid,parts[2],float(data.get("start_price",3)),float(data.get("increment",1)),data.get("ends_at")))
                return self.sendj(item_full(parts[2]))
            if len(parts)==4 and parts[:2]==["api","auctions"] and parts[3]=="bids":
                with db() as c:
                    a=c.execute("SELECT * FROM auctions WHERE id=?",(parts[2],)).fetchone(); top=c.execute("SELECT MAX(amount) FROM bids WHERE auction_id=?",(parts[2],)).fetchone()[0]
                    minimum=max(a["start_price"],(top or (a["start_price"]-a["increment"]))+a["increment"])
                    amount=float(data["amount"])
                    if amount<minimum:raise RuntimeError(f"Bid must be at least ${minimum:.2f}")
                    c.execute("INSERT INTO bids(auction_id,bidder,amount,created_at) VALUES(?,?,?,?)",(parts[2],data["bidder"].strip(),amount,now()))
                    item_id=a["item_id"]
                return self.sendj(item_full(item_id))
            if u.path=="/api/settings":settings_write(data);return self.sendj(data)
            self.sendj({"error":"not found"},404)
        except Exception as e:self.sendj({"error":str(e)},400)
    def do_PUT(self):
        try:
            parts=urlparse(self.path).path.strip("/").split("/"); data=self.body()
            if len(parts)==3 and parts[:2]==["api","items"]:
                fields=["title","description","condition_text","category","price","quantity","shipping","notes","status"]
                vals=[data.get(x,"" if x not in ("price","quantity") else (3 if x=="price" else 1)) for x in fields]
                with db() as c:c.execute("UPDATE items SET "+",".join(f"{x}=?" for x in fields)+",updated_at=? WHERE id=?",(*vals,now(),parts[2]))
                return self.sendj(item_full(parts[2]))
            self.sendj({"error":"not found"},404)
        except Exception as e:self.sendj({"error":str(e)},400)

def serve(host,port,open_browser=True):
    httpd=ThreadingHTTPServer((host,port),H); print(f"Jetstreamin Market Lister: http://127.0.0.1:{port}")
    if open_browser and shutil.which("termux-open-url"): threading.Timer(0.5,lambda:subprocess.run(["termux-open-url",f"http://127.0.0.1:{port}"])).start()
    try:httpd.serve_forever()
    except KeyboardInterrupt:pass

if __name__=="__main__":
    ap=argparse.ArgumentParser(description="Jetstreamin multi-market listing engine")
    sub=ap.add_subparsers(dest="cmd",required=True); s=sub.add_parser("serve");s.add_argument("--host",default="127.0.0.1");s.add_argument("--port",type=int,default=8787);s.add_argument("--no-open",action="store_true")
    n=sub.add_parser("new");n.add_argument("--title",default="New item");n.add_argument("--price",type=float,default=3);n.add_argument("--camera",action="store_true")
    e=sub.add_parser("export");e.add_argument("id");e.add_argument("channel",choices=["ebay","whatnot","facebook"])
    args=ap.parse_args()
    if args.cmd=="serve":serve(args.host,args.port,not args.no_open)
    elif args.cmd=="new":
        ident=uuid.uuid4().hex[:12];t=now()
        with db() as c:c.execute("INSERT INTO items(id,created_at,updated_at,title,price) VALUES(?,?,?,?,?)",(ident,t,t,args.title,args.price))
        if args.camera:
            p=camera(ident)
            with db() as c:c.execute("INSERT INTO photos VALUES(?,?,?,0)",(uuid.uuid4().hex,ident,str(p)))
        print(json.dumps(item_full(ident),indent=2))
    else:print(json.dumps(channel_payload(item_full(args.id),args.channel),indent=2))
