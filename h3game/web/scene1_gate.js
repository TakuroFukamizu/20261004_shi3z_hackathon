// ============================================================
// Scene1: 校門。生徒指導の先生の前で、両方のレバーを引いて気合いを入れ、
// マイクに「おはよう」と叫ぶ。声の大きさが HP、気合い(感情)が MP になる。
//   pull   … 「レバーを引いて気合いを入れろ！」両レバーを手前いっぱいに引き続ける
//   listen … 「力いっぱい、『おはよう』と言おう」録音
//   judge  … AI(bridge の /ai)が 言葉・感情・声の強さ を判定。
//            AI は文字しか読めない LLM なので、言葉はブラウザの音声認識で文字にし、音量の実測と一緒に渡す
//   result … 結果を見せて Scene2 へ。言えていなければやり直し
// ============================================================
(()=>{
 const PULL=0.85,CHARGE_SEC=1.5,LISTEN_SEC=3.5,MAX_TRIES=3;
 const HP_BASE=50,HP_PER=1.5,MP_BASE=20,MP_PER=1;   // HP=50..200(音量) MP=20..120(気合い)
 const prompt=(heard,r)=>`学校の校門で、生徒が生徒指導の先生に向かって挨拶しました。
聞こえた言葉(音声認識の結果): 「${heard}」
声の大きさ(実測): ${r.loud}/100 (${r.db} dB)
声が出ていた時間: ${r.voiced} 秒
(音声が添付されていれば、それも聞いて判断してください)
次の JSON だけを返してください。
{"said_ohayou": 「おはよう」または「おはようございます」と言っていれば true、違う言葉や無言なら false,
 "emotion": "言葉と声の大きさから感じる感情を一言で(例: 元気, 怒り, 眠い, 照れ, 無気力)",
 "kiai": 気合い・感情の強さ 0〜100 の整数(小声や短い声は低く、大声で伸ばした声や「！」の勢いがあれば高く),
 "volume": 声の大きさ・張りの印象 0〜100 の整数,
 "comment": "生徒指導の先生が生徒に言い放つ一言(20文字以内、命令口調の熱血教師。例: 声が小さい！腹から出せ！ / よし！その意気だ！)"}`;
 let st,t,charge,pull,tries,rec,res,shake,hasMic;

 // Web Speech(ブラウザの音声認識)。AI が使えない時の言葉の聞き取り用
 let sr=null,srText='';
 function srStart(){srText='';const R=window.SpeechRecognition||window.webkitSpeechRecognition;if(!R)return;
  try{sr=new R();sr.lang='ja-JP';sr.interimResults=true;sr.onresult=e=>{srText=Array.from(e.results).map(r=>r[0].transcript).join('')};sr.onerror=()=>{};sr.start()}catch(e){sr=null}}
 // 止めてから最後の結果が届くまで少し待つ
 function srStop(){return new Promise(res=>{if(!sr)return res();const done=()=>{sr=null;res()};sr.onend=done;setTimeout(done,1500);try{sr.stop()}catch(e){done()}})}

 async function judge(){
  let a=null;await srStop();
  try{const r=await fetch('/ai',{method:'POST',body:JSON.stringify({prompt:prompt(srText,rec),json:true,audio:rec.wav})});
   const txt=(await r.json()).text||'';const m=txt.match(/\{[\s\S]*\}/);if(m)a=JSON.parse(m[0])}catch(e){}
  const num=v=>Math.max(0,Math.min(100,Math.round(+v||0)));
  // 小さい LLM は数字が甘いので、言えたかどうかは認識した文字で決め、気合いは実測(音量と声の長さ)と半々に混ぜる
  const heard=/おはよ|お早/.test(srText)||(!srText&&rec.loud>=25),body=rec.loud*0.7+Math.min(1,rec.voiced/2)*30;
  if(a)res={ai:true,transcript:srText||String(a.transcript||''),said:heard,emotion:String(a.emotion||'?'),kiai:num((num(a.kiai)+body)/2),
   loud:Math.round((rec.loud+num(a.volume))/2),db:rec.db,comment:String(a.comment||'')};
  else{const said=heard;   // AI なし: 気合いは実測だけで決める
   res={ai:false,transcript:srText,said,emotion:rec.loud>=60?'元気':rec.loud>=30?'ふつう':'眠い',kiai:num(body),loud:rec.loud,db:rec.db,
    comment:said?(rec.loud>=60?'よし、いい声だ！':'もっと腹から出せ！'):'聞こえんぞ！'}}
  if(!res.said&&tries>=MAX_TRIES){res.said=true;res.forced=true;res.comment='…もういい、通れ。'}
  if(res.said){const s=Game.status;s.hpMax=HP_BASE+100*HP_PER;s.mpMax=MP_BASE+100*MP_PER;
   s.hp=Math.round(HP_BASE+res.loud*HP_PER);s.mp=Math.round(MP_BASE+res.kiai*MP_PER);s.voice=res}
  st='result';t=0}

 function noMic(){rec={wav:'',loud:0,db:-99,seconds:0};res={ai:false,transcript:'',said:true,forced:true,emotion:'?',kiai:0,loud:0,db:-99,comment:'マイクが使えん！通れ。'};
  const s=Game.status;s.hpMax=HP_BASE+100*HP_PER;s.mpMax=MP_BASE+100*MP_PER;s.hp=HP_BASE;s.mp=MP_BASE;s.voice=res;st='result';t=0}

 Game.scenes.gate={
  enter(){st='pull';t=0;charge=0;pull=0;tries=0;rec=null;res=null;shake=0;hasMic=Mic.ok();
   if(!hasMic)Mic.init().then(ok=>hasMic=ok);Mic.resume()},
  update(dt,inp){t+=dt;const m={pitch:0,roll:0,yaw:0};const T=performance.now()/1000;
   const two=!!H3Input.padFor('stick2');pull=two?Math.min(inp.y,inp.y2):inp.y;   // スティックが1本だけならそれで判定
   if(st==='pull'){charge=Math.max(0,Math.min(1,charge+(pull>=PULL?dt/CHARGE_SEC:-dt*1.5)));
    m.pitch=charge*0.5+Math.sin(T*45)*0.08*charge;m.roll=Math.sin(T*37)*0.06*charge;   // 引くほど席がのけぞって震える
    if(charge>=1){tries++;if(!hasMic){noMic()}else{st='listen';t=0;Mic.start();srStart()}}}
   else if(st==='listen'){shake=Mic.level();m.pitch=0.5-shake*0.4;m.roll=Math.sin(T*50)*0.25*shake;m.yaw=Math.sin(T*31)*0.2*shake;   // 声で席が震える
    if(t>=LISTEN_SEC){rec=Mic.stop();st='judge';t=0;judge()}}
   else if(st==='judge'){m.pitch=0.2+Math.sin(T*3)*0.05}
   else if(st==='result'){
    if(res.said){if(t>0.3&&t<1)m.pitch=-0.5;if(t>5||(t>1.5&&inp.fire))Game.go('status')}
    else{m.roll=Math.sin(T*25)*0.3*Math.max(0,1-t);if(t>3){st='pull';t=0;charge=0}}}
   return m},
  draw(x,W,H){const u=H/100,T=performance.now()/1000;
   // 空・校舎・校門
   const g=x.createLinearGradient(0,0,0,H);g.addColorStop(0,'#7ec8f5');g.addColorStop(0.7,'#dff3ff');x.fillStyle=g;x.fillRect(0,0,W,H);
   x.fillStyle='#e9e2d0';x.fillRect(W*0.18,22*u,W*0.64,45*u);x.fillStyle='#c9bfa6';x.fillRect(W*0.18,20*u,W*0.64,3*u);
   x.fillStyle='#e9e2d0';x.fillRect(W*0.45,8*u,W*0.1,16*u);
   x.fillStyle='#fff';x.strokeStyle='#333';x.lineWidth=0.5*u;x.beginPath();x.arc(W/2,15*u,4*u,0,7);x.fill();x.stroke();
   x.beginPath();x.moveTo(W/2,15*u);x.lineTo(W/2,12*u);x.moveTo(W/2,15*u);x.lineTo(W/2+2*u,16*u);x.stroke();   // 時計は 8:20
   x.fillStyle='#5b7f9a';for(let r=0;r<3;r++)for(let c=0;c<9;c++){if(r>0&&c===4)continue;x.fillRect(W*0.2+c*W*0.068,27*u+r*12*u,W*0.045,7*u)}
   x.fillStyle='#8a8f96';x.fillRect(0,67*u,W,33*u);x.fillStyle='#9aa0a8';x.beginPath();x.moveTo(W*0.4,67*u);x.lineTo(W*0.6,67*u);x.lineTo(W*0.85,H);x.lineTo(W*0.15,H);x.fill();
   for(const sx of [0.1,0.82]){x.fillStyle='#b5aa98';x.fillRect(W*sx,38*u,W*0.08,42*u);x.fillStyle='#8f8676';x.fillRect(W*sx-1*u,36*u,W*0.08+2*u,3*u)}
   x.fillStyle='#f4efe2';x.fillRect(W*0.12,46*u,W*0.04,22*u);x.fillStyle='#222';x.font=`900 ${3.2*u}px "Hiragino Mincho ProN",serif`;x.textAlign='center';
   ['熱','血','高','校'].forEach((ch,i)=>x.fillText(ch,W*0.14,51*u+i*4.6*u));x.textAlign='left';
   // 先生: ジャージ・竹刀・ホイッスル。場面で表情が変わる
   const angry=st==='result'&&!res.said,happy=st==='result'&&res.said&&!res.forced;
   const bob=Math.sin(T*(angry?18:2))*(angry?0.6:0.4)*u,cx=W*0.62,by=86*u+bob,s=u*1.15;
   x.fillStyle='#0003';x.beginPath();x.ellipse(cx,87*u,11*s,2*s,0,0,7);x.fill();
   x.strokeStyle='#c9a45a';x.lineWidth=1.2*s;x.beginPath();x.moveTo(cx+11*s,by-16*s);x.lineTo(cx+17*s,by-46*s);x.stroke();   // 竹刀
   x.fillStyle='#1c3f8f';x.fillRect(cx-6*s,by-18*s,5*s,18*s);x.fillRect(cx+1*s,by-18*s,5*s,18*s);   // 足
   x.fillStyle='#c22';x.beginPath();x.roundRect(cx-9*s,by-40*s,18*s,24*s,3*s);x.fill();   // ジャージ
   x.fillStyle='#fff';x.fillRect(cx-9*s,by-34*s,18*s,1.2*s);x.fillRect(cx-0.6*s,by-40*s,1.2*s,24*s);
   x.fillStyle='#c22';x.fillRect(cx-13*s,by-39*s,5*s,16*s);x.fillRect(cx+8*s,by-39*s,5*s,16*s);   // 腕
   x.fillStyle='#f1c9a0';x.beginPath();x.arc(cx,by-47*s,7.5*s,0,7);x.fill();
   x.fillStyle='#222';x.beginPath();x.arc(cx,by-49.5*s,7.6*s,Math.PI*1.05,Math.PI*1.95);x.fill();   // 角刈り
   x.strokeStyle='#222';x.lineWidth=0.9*s;x.beginPath();const br=happy?-1:1.6;   // 眉
   x.moveTo(cx-5.5*s,by-49.5*s-br*s);x.lineTo(cx-1.5*s,by-49.5*s+br*s*0.5);x.moveTo(cx+5.5*s,by-49.5*s-br*s);x.lineTo(cx+1.5*s,by-49.5*s+br*s*0.5);x.stroke();
   x.fillStyle='#222';x.beginPath();x.arc(cx-3.2*s,by-47*s,0.9*s,0,7);x.arc(cx+3.2*s,by-47*s,0.9*s,0,7);x.fill();
   x.beginPath();if(happy)x.arc(cx,by-44*s,3*s,0.1,Math.PI-0.1);else if(angry||st==='pull')x.ellipse(cx,by-43*s,2.6*s,(1.2+Math.abs(Math.sin(T*9)))*s,0,0,7);else{x.moveTo(cx-2.5*s,by-43*s);x.lineTo(cx+2.5*s,by-43*s)}
   x.fillStyle='#711';x.fill();x.stroke();
   x.fillStyle='#fc3';x.beginPath();x.arc(cx,by-37*s,1.3*s,0,7);x.fill();   // ホイッスル
   // 場面ごとの文字とゲージ
   const gw=W*0.5,gx=W/2-gw/2;
   if(st==='pull'){Game.text(x,'レバーを引いて気合いを入れろ！',W/2,14*u,7*u,'#ffe14a');
    Game.text(x,'左右のレバーを手前いっぱいに引き続ける',W/2,21*u,3.2*u,'#fff');
    Game.gauge(x,gx,90*u,gw,5*u,charge,pull>=PULL?'#fa3':'#888','気合い');
    if(tries>0)Game.text(x,`${tries+1} 回目`,W*0.9,8*u,3*u,'#fff')}
   else if(st==='listen'){const k=1+shake*0.15;Game.text(x,'力いっぱい、『おはよう』と言おう',W/2,14*u,7*u*k,'#ff6a4a');
    Game.gauge(x,gx,84*u,gw,5*u,shake,'#4d8','声');Game.gauge(x,gx,92*u,gw,3*u,1-t/LISTEN_SEC,'#fff');
    x.fillStyle='#e33';x.beginPath();x.arc(gx-5*u,86.5*u,(1.6+shake*1.5)*u,0,7);x.fill()}
   else if(st==='judge'){Game.text(x,'先生が判定中'+'.'.repeat(1+Math.floor(t*2)%3),W/2,14*u,7*u,'#fff')}
   else if(st==='result'){
    Game.text(x,res.comment||'',W/2,14*u,7*u,res.said?'#ffe14a':'#ff5a4a');
    if(res.transcript)Game.text(x,`「${res.transcript}」`,W/2,22*u,4*u,'#fff');
    if(res.said){const s=Game.status;x.fillStyle='#000a';x.fillRect(W*0.06,58*u,W*0.36,30*u);
     Game.text(x,`声の大きさ ${res.loud} → HP ${s.hp}`,W*0.08,66*u,3.6*u,'#f88','left');
     Game.text(x,`気合い ${res.kiai}(${res.emotion})→ MP ${s.mp}`,W*0.08,74*u,3.6*u,'#8cf','left');
     Game.text(x,res.ai?'AI 判定':'AI なし(音量で判定)',W*0.08,82*u,2.6*u,res.ai?'#9fc':'#fc6','left')}
    else Game.text(x,'もう一回！',W/2,30*u,6*u,'#fff')}}
 };
})();
