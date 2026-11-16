import json
from datetime import datetime, timezone
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from config import OUTPUT, DATA
import os

def main():
    cid=os.getenv("YT_CLIENT_ID",""); secret=os.getenv("YT_CLIENT_SECRET",""); refresh=os.getenv("YT_REFRESH_TOKEN","")
    if not all([cid,secret,refresh]): raise RuntimeError("Faltan secretos OAuth YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN")
    videos=sorted(OUTPUT.glob("*.mp4"),key=lambda p:p.stat().st_mtime)
    if not videos: print("No hay MP4."); return
    creds=Credentials(None,refresh_token=refresh,token_uri="https://oauth2.googleapis.com/token",client_id=cid,client_secret=secret,scopes=["https://www.googleapis.com/auth/youtube.upload"])
    creds.refresh(Request())
    yt=build("youtube","v3",credentials=creds)
    p=videos[-1]
    body={"snippet":{"title":"GTA VI Community Update #Shorts","description":"Original GTA VI community update. Unconfirmed information is identified as such. #GTA6 #GTAVI #Shorts","tags":["GTA6","GTAVI","Shorts"],"categoryId":"20"},"status":{"privacyStatus":"private","selfDeclaredMadeForKids":False}}
    req=yt.videos().insert(part="snippet,status",body=body,media_body=MediaFileUpload(str(p),chunksize=-1,resumable=True))
    response=None
    while response is None:
        status,response=req.next_chunk()
        if status: print(f"Upload {int(status.progress()*100)}%")
    log=DATA/"uploaded.json"
    try: entries=json.loads(log.read_text(encoding="utf-8"))
    except Exception: entries=[]
    entries.append({"id":response["id"],"file":p.name,"at":datetime.now(timezone.utc).isoformat()})
    log.write_text(json.dumps(entries[-500:],indent=2),encoding="utf-8")
    print("Subido como PRIVADO para revisión:",response["id"])
if __name__=="__main__": main()
