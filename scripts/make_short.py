import json, re, asyncio, subprocess
from datetime import datetime, timezone
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import edge_tts
from config import DATA, OUTPUT

def load():
    try: return json.loads((DATA/"candidates.json").read_text(encoding="utf-8")).get("items",[])
    except Exception: return []

def font(size):
    for p in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf","/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"]:
        if Path(p).exists(): return ImageFont.truetype(p,size)
    return ImageFont.load_default()

def wrap(draw,text,f,maxw):
    out=[]; line=""
    for word in text.split():
        test=(line+" "+word).strip()
        if draw.textbbox((0,0),test,font=f)[2] <= maxw: line=test
        else:
            if line: out.append(line)
            line=word
    if line: out.append(line)
    return out

async def voice(text,path):
    await edge_tts.Communicate(text,"en-US-GuyNeural",rate="+5%").save(str(path))

def main():
    items=load()
    if not items: print("No hay novedades; no se crea vídeo."); return
    item=items[0]
    title=item.get("title","GTA VI update")
    summary=re.sub(r"\s+"," ",item.get("summary","")).strip()
    script=f"Here is a GTA six community update. {title}. {summary[:350]}. Treat unconfirmed claims as rumours until Rockstar confirms them. Follow for more GTA six updates."
    stamp=datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    img=OUTPUT/f"gta_vi_{stamp}.jpg"; audio=OUTPUT/f"gta_vi_{stamp}.mp3"; video=OUTPUT/f"gta_vi_{stamp}.mp4"
    canvas=Image.new("RGB",(1080,1920),(10,18,45)); d=ImageDraw.Draw(canvas)
    d.ellipse((500,160,1250,900),outline=(238,70,160),width=18)
    d.ellipse((-300,1050,650,2000),outline=(20,220,220),width=16)
    d.rectangle((65,90,1015,1830),outline=(255,210,80),width=5)
    f=font(76); y=570
    for line in wrap(d,title.upper(),f,850)[:6]:
        bb=d.textbbox((0,0),line,font=f,stroke_width=3); x=(1080-(bb[2]-bb[0]))//2
        d.text((x,y),line,font=f,fill="white",stroke_width=3,stroke_fill="black"); y+=105
    d.text((95,1660),"GTA VI COMMUNITY UPDATE",font=font(38),fill=(255,220,90))
    canvas.save(img)
    (OUTPUT/f"gta_vi_{stamp}.txt").write_text(f"SOURCE: {item.get('url','')}\nTITLE: {title}\n\nSCRIPT:\n{script}",encoding="utf-8")
    asyncio.run(voice(script,audio))
    subprocess.run(["ffmpeg","-y","-loop","1","-i",str(img),"-i",str(audio),"-vf","scale=1080:1920,format=yuv420p","-c:v","libx264","-tune","stillimage","-c:a","aac","-b:a","192k","-shortest","-movflags","+faststart",str(video)],check=True)
    print("Short de prueba creado:",video)
if __name__=="__main__": main()
