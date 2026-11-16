import json, re
from datetime import datetime, timezone
import feedparser, requests
from config import DATA, RSS_URLS, YOUTUBE_API_KEY

SEEN = DATA/"seen.json"
CANDIDATES = DATA/"candidates.json"
TERMS = ["GTA 6","GTA VI","Grand Theft Auto VI","Vice City","Lucia","Jason","Rockstar Games"]

def read(path, default):
    try: return json.loads(path.read_text(encoding="utf-8"))
    except Exception: return default

def main():
    seen = read(SEEN,{})
    items = []
    for url in RSS_URLS:
        try:
            for e in feedparser.parse(url).entries[:40]:
                title = re.sub(r"\s+"," ",e.get("title","")).strip()
                summary = re.sub(r"\s+"," ",e.get("summary","")).strip()
                if any(t.lower() in (title+" "+summary).lower() for t in TERMS):
                    items.append({"title":title,"summary":summary[:800],"url":e.get("link",""),"published":e.get("published",""),"source":url})
        except Exception as exc: print("RSS:",url,exc)
    # Solo una búsqueda por ejecución: controlar el consumo de cuota.
    if YOUTUBE_API_KEY:
        try:
            params={"part":"snippet","q":"GTA 6","type":"video","order":"date","maxResults":10,"key":YOUTUBE_API_KEY}
            r=requests.get("https://www.googleapis.com/youtube/v3/search",params=params,timeout=20); r.raise_for_status()
            for x in r.json().get("items",[]):
                items.append({"title":x["snippet"].get("title",""),"summary":x["snippet"].get("description","")[:800],"url":"https://youtube.com/watch?v="+x["id"]["videoId"],"published":x["snippet"].get("publishedAt",""),"source":x["snippet"].get("channelTitle","YouTube")})
        except Exception as exc: print("YouTube API:",exc)
    unique={}
    for x in items:
        u=x.get("url")
        if u and u not in seen: unique[u]=x
    ranked=sorted(unique.values(),key=lambda x:x.get("published",""),reverse=True)
    (CANDIDATES).write_text(json.dumps({"checked_at":datetime.now(timezone.utc).isoformat(),"items":ranked[:15]},ensure_ascii=False,indent=2),encoding="utf-8")
    for x in ranked: seen[x["url"]]=datetime.now(timezone.utc).isoformat()
    if len(seen)>2500: seen=dict(list(seen.items())[-2000:])
    SEEN.write_text(json.dumps(seen,indent=2),encoding="utf-8")
    print("Temas nuevos:",len(ranked))
if __name__=="__main__": main()
