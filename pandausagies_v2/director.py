from __future__ import annotations
import random
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any
from .events import evolve_events
from .expression import ExpressionValidator, LocalExpressionProvider
from .media import ExistingMediaProvider
from .memory import Memory
from .songs import choose_song

DAILY_MOTIFS = ("pot", "table", "bread", "glasses", "train", "room", "lunch")
CELEBRATION_MOTIFS = ("guitar", "crown", "flowers")
MOTIFS = DAILY_MOTIFS + CELEBRATION_MOTIFS
CATEGORIES = ("ordinary", "offbeat", "promo")
BANNED = ("死にたい", "消えたい", "絶望", "今すぐ買", "絶対聴いて", "フォローして")
LINES = {
 "pot": (("鍋にスープを残した\n朝もこれを食べる","ordinary"),("小さい鍋でお湯を沸かした\n大きい鍋は出さなかった","ordinary"),("鍋のふたを洗った\n鍋はあとで洗う","offbeat"),("鍋にうどんを入れた\n少し多かった","ordinary"),("鍋の残りを弁当に入れた\n汁は入れなかった","offbeat"),("鍋で卵を二つゆでた\n一つは今食べた","ordinary")),
 "table": (("食卓を拭いた\nパンくずが三つあった","ordinary"),("食卓に皿を一枚置いた\n椅子は二脚ある","ordinary"),("食卓でお弁当を包んだ\n輪ゴムを二本使った","offbeat"),("食卓の端でごはんを食べた\n真ん中は空いている","ordinary"),("食卓の鍋を少しずらした\nパンを置いた","ordinary"),("食卓にメガネを置いた\n掛けたまま探していた","offbeat")),
 "bread": (("パンを買った\n帰るまで少し減った","offbeat"),("食パンを一枚焼いた\n少し焦げた","ordinary"),("パンを半分に切った\n大きい方を弁当に入れた","ordinary"),("丸いパンを買った\n電車では手に持った","ordinary"),("パンを二つ買った\n先に同じ方を二つ食べた","offbeat"),("パンの袋を閉じた\n洗濯ばさみを使った","offbeat")),
 "glasses": (("メガネを拭いた\n右だけ二回拭いた","ordinary"),("メガネを掛けたまま探した\n食卓の下も見た","offbeat"),("メガネをケースに入れた\nケースはかばんに入れた","ordinary"),("メガネのねじを締めた\n小さいドライバーを使った","ordinary"),("電車でメガネが曇った\n降りるまでそのまま","ordinary"),("予備のメガネを持った\nいつものも掛けている","offbeat")),
 "train": (("電車を一本見送った\n次の電車に乗った","offbeat"),("各駅停車に乗った\n三つ先で降りた","ordinary"),("電車のドアの近くに立った\n二駅で席が空いた","ordinary"),("反対方向の電車に乗った\n次の駅で戻った","offbeat"),("電車でパンを持っていた\n袋は開けなかった","ordinary"),("終点の一つ前で降りた\n駅前を少し歩いた","ordinary")),
 "room": (("古い部屋の窓を開けた\n十分で閉めた","ordinary"),("机の端を片づけた\n真ん中はそのまま","offbeat"),("椅子を窓の近くへ動かした\n夜に元へ戻した","ordinary"),("電球をひとつ替えた\n脚立は使わなかった","ordinary"),("棚の上だけ拭いた\n下の段は明日","offbeat"),("床の本を積んだ\n四冊でやめた","ordinary")),
 "lunch": (("卵焼きが少し斜め\nそのまま閉めた","ordinary"),("お弁当のすき間\nパンで埋めた","offbeat"),("お弁当を食卓で包んだ\n結び目は横になった","ordinary"),("ごはんを少し多く入れた\nふたは閉まった","ordinary"),("赤いおかずがなかった\n梅干しを二つ入れた","offbeat"),("箸を入れ忘れた\n売店でスプーンをもらった","ordinary")),
 "guitar": (("ギターを弾いた\nコードを三つ確認した","ordinary"),("ギターの弦を一本替えた\n残りはそのまま","ordinary"),("マイクを机に出した\n一曲だけ録った","ordinary"),("歌詞を一行直した\n前の行は消さなかった","ordinary"),("ギターを壁から外した\nチューニングだけした","offbeat"),("マイクをつないだ\n歌う前にパンを食べた","offbeat")),
 "crown": (("王冠を箱から出した\nほこりを拭いた","ordinary"),("王冠をかぶって鏡を見た\nメガネも掛けた","ordinary"),("王冠を食卓に置いた\n鍋より奥へ移した","offbeat"),("王冠の飾りを一つ直した\n接着剤を使った","ordinary"),("王冠を紙で包んだ\nパン屋の袋に入れた","offbeat"),("王冠を撮影に持っていった\n箱で運んだ","ordinary")),
 "flowers": (("花を窓のそばへ\n今日はそこ","ordinary"),("花の水を替えた\n茎も少し切った","ordinary"),("短い花を前に置いた\n長い花は後ろ","ordinary"),("花瓶がなかった\n大きいコップを使った","offbeat"),("黄色い花を一本買った\nパンとは別に持った","ordinary"),("花を三本に分けた\n花瓶は二つ使った","offbeat")),
}
EXTRA_LINES = {
 "pot": (("鍋を洗って棚に戻した\nふたも同じ場所に置いた","ordinary"),("鍋でじゃがいもを煮た\n四つ入れた","ordinary")),
 "table": (("食卓に布を敷いた\n角を一度直した","ordinary"),("食卓で郵便を読んだ\n封筒は重ねて置いた","ordinary")),
 "bread": (("固いパンをスープに入れた\nスプーンで食べた","ordinary"),("パン屋で食パンを買った\nかばんの上に入れた","ordinary")),
 "glasses": (("メガネを食卓に置いた\n鍋から少し離した","ordinary"),("メガネを外して顔を洗った\nタオルの横に置いた","ordinary")),
 "train": (("電車を乗り換えた\n同じホームを端まで歩いた","ordinary"),("空いた電車で立っていた\nかばんは手に持った","ordinary")),
 "room": (("古い部屋で洗濯物を干した\nシャツは二枚","ordinary"),("カーテンを閉めた\n机の電気をつけた","ordinary")),
 "lunch": (("小さいお弁当にした\nパンも別に持った","ordinary"),("お昼を遅く食べた\n卵焼きから食べた","ordinary")),
 "guitar": (("録音を一度聴いた\n音量を少し下げた","ordinary"),("ギターをケースに入れた\n玄関に置いた","ordinary")),
 "crown": (("王冠を一度かぶった\n箱へ戻した","ordinary"),("王冠を撮る前にメガネを拭いた\n布は机に置いた","ordinary")),
 "flowers": (("花びらを一枚拾った\n食卓の端に置いた","ordinary"),("花を撮る前に鍋を移した\n鍋は台に置いた","ordinary")),
}
LINES = {motif: LINES[motif] + EXTRA_LINES[motif] for motif in MOTIFS}

@dataclass(frozen=True)
class Decision:
 at: str; action: str; category: str|None; motif: str|None; event_id: str|None; event_action: str
 song_id: str|None; media_id: str|None; include_url: bool; text: str; reason: str; week_id: str|None=None
 def to_dict(self)->dict[str,Any]: return asdict(self)

class AutonomousDirector:
 def __init__(self,songs:list[dict],media_provider:ExistingMediaProvider,rng:random.Random|None=None):
  self.songs,self.media_provider,self.rng=songs,media_provider,rng or random.Random(); self.expression=LocalExpressionProvider(); self.validator=ExpressionValidator()
 def _pick_motif(self,memory:Memory,event:dict|None)->str:
  recent=[p.get("motif") for p in memory.posts[-3:]]
  if event and event["motif"] in MOTIFS and self.rng.random()<.65: return event["motif"]
  group=DAILY_MOTIFS if self.rng.random()<.70 else CELEBRATION_MOTIFS
  pool=[m for m in group if m not in recent[-2:]] or list(group); counts={m:len(memory.motif_usage.get(m,[])) for m in pool}; least=min(counts.values())
  return self.rng.choice([m for m in pool if counts[m]<=least+1])
 def _text(self,motif:str,memory:Memory)->tuple[str,str]:
  used={p["text"] for p in memory.posts}
  nonpromo=[p for p in memory.posts if p.get("category")!="promo"]; offbeat=sum(p.get("category")=="offbeat" for p in nonpromo)
  preferred="offbeat" if (not nonpromo or offbeat/len(nonpromo)<.18) and self.rng.random()<.30 else "ordinary"
  preferred_pool=[x for x in LINES[motif] if x[1]==preferred]
  preferred_unused=[x for x in preferred_pool if x[0] not in used]; any_unused=[x for x in LINES[motif] if x[0] not in used]
  candidates=preferred_unused or any_unused or preferred_pool
  scored=[(self.validator.score(t),t,c) for t,c in candidates]; best=min(x[0] for x in scored); _,text,category=self.rng.choice([x for x in scored if x[0]==best]); return self.expression.polish(text),category
 def decide(self,now:datetime,memory:Memory,weekly_due:bool=False)->Decision:
  day_posts=[p for p in memory.posts if p["at"][:10]==now.date().isoformat()]
  if len(day_posts)>=memory.settings["normal_daily_limit"]: return Decision(now.isoformat(),"skip",None,None,None,"none",None,None,False,"","daily hard limit")
  memory.events,event,event_action=evolve_events(memory.events,now.date(),self.rng)
  if not weekly_due and self.rng.random()>(.50 if not day_posts else .12): return Decision(now.isoformat(),"skip",None,None,event and event["id"],event_action,None,None,False,"","quiet day chosen")
  motif=self._pick_motif(memory,event); text,category=self._text(motif,memory)
  song=choose_song(self.songs,[p["song_id"] for p in memory.posts if p.get("song_id")],self.rng) if weekly_due else None; media=self.media_provider.choose([p["media_id"] for p in memory.posts if p.get("media_id")],self.rng) if weekly_due else None
  promo_count=sum(p.get("category")=="promo" for p in memory.posts); promo_room=not memory.posts or promo_count/len(memory.posts)<.08
  include_url=bool(weekly_due and song and promo_room and self.rng.random()<.55); category="promo" if include_url else category; validation=self.validator.validate(text)
  if not validation.valid or any(w in text for w in BANNED): return Decision(now.isoformat(),"skip",None,motif,event and event["id"],event_action,None,None,False,"","voice validation rejected")
  week_id=f"week-{len(memory.weeks)+1:02d}" if weekly_due else None
  return Decision(now.isoformat(),"post",category,motif,event and event["id"],event_action,song and song["id"],media and media["id"],include_url,text,"weekly autonomous selection" if weekly_due else "daily autonomous trace",week_id)

def apply_decision(memory:Memory,decision:Decision,mutate_week:bool=True)->None:
 data=decision.to_dict(); memory.decisions.append(data)
 if decision.action!="post": return
 memory.posts.append(data); stamp=decision.at
 if decision.motif: memory.motif_usage.setdefault(decision.motif,[]).append(stamp)
 if decision.song_id: memory.song_usage.setdefault(decision.song_id,[]).append(stamp)
 if decision.media_id: memory.media_usage.setdefault(decision.media_id,[]).append(stamp)
 if decision.event_id:
  for event in memory.events:
   if event["id"]==decision.event_id: event["related_posts"].append(len(memory.posts)-1)
 if mutate_week and decision.week_id: memory.weeks.append({"id":decision.week_id,"week":len(memory.weeks)+1,"date":decision.at[:10],"text":decision.text,"song_id":decision.song_id,"media_id":decision.media_id,"status":"simulated","immutable":True})

def next_week_due(memory:Memory,now:datetime,start:datetime)->bool:
 last=datetime.fromisoformat(memory.weeks[-1]["date"]) if memory.weeks else start-timedelta(days=7)
 if last.tzinfo is None: last=last.replace(tzinfo=now.tzinfo)
 return (now.date()-last.date()).days>=7
