// ============================================================
// Game: シーンの切り替えと、シーンをまたいで持ち回るステータス。
// index.html(土台)から毎フレーム呼ばれる。
//   Game.scenes.名前 = {enter(), update(dt, inp), draw(x, W, H)}   ← 各 scene_*.js が登録する
//     update は席の動き {pitch, roll, yaw}(-1..1) を返す
//   Game.go('名前')   … シーンを切り替える
//   Game.status       … {hp, hpMax, mp, mpMax, ...} シーン間で共有
//   Game.chiming()    … シーン開始のチャイムが鳴っている間 true(この間はマイクを使わない)
//   Game.sfx          … 効果音: rumble(0..1) 地鳴り / ok() / ng()
//   試すとき: http://localhost:8891/?scene=quake のようにすると、そのシーンから始まる
// チャイム: 効果音ラボ(https://soundeffect-lab.info/)「学校のチャイム」の冒頭
// inp: {x, y, twist, throttle, x2, y2, twist2, throttle2, rudder, brakeL, brakeR,
//       fire, fire2, buttons1[], buttons2[]}   (軸は -1..1、片側の軸は 0..1。y は手前に引くとプラス)
// ============================================================
const Game=(()=>{
 const FIRST=new URLSearchParams(location.search).get('scene')||'gate',CHIME_SEC=5;
 const status={};const scenes={};let cur=null,name='',chimeAt=-99;
 const chime=new Audio('chime.mp3');chime.volume=0.7;
 // 効果音(その場で合成)
 const sfx=(()=>{let ac=null,rg=null;
  function ctx(){if(!ac){ac=new AudioContext();const n=ac.sampleRate*2,b=ac.createBuffer(1,n,ac.sampleRate),d=b.getChannelData(0);let v=0;
    for(let i=0;i<n;i++){v=(v+(Math.random()*2-1)*0.04)/1.004;d[i]=v*4}
    const src=ac.createBufferSource();src.buffer=b;src.loop=true;const lp=ac.createBiquadFilter();lp.type='lowpass';lp.frequency.value=110;
    rg=ac.createGain();rg.gain.value=0;src.connect(lp);lp.connect(rg);rg.connect(ac.destination);src.start()}
   if(ac.state==='suspended')ac.resume();return ac}
  function rumble(v){ctx();rg.gain.setTargetAtTime(Math.max(0,Math.min(1,v))*1.5,ac.currentTime,0.1)}
  function beep(freqs,type,len){const a=ctx();freqs.forEach((f,i)=>{const o=a.createOscillator(),g=a.createGain();o.type=type;o.frequency.value=f;
   const t=a.currentTime+i*len;g.gain.setValueAtTime(0.25,t);g.gain.exponentialRampToValueAtTime(0.001,t+len*1.8);o.connect(g);g.connect(a.destination);o.start(t);o.stop(t+len*2)})}
  return {rumble,ok:()=>beep([880,1175],'sine',0.12),ng:()=>beep([196,147],'sawtooth',0.22),stop:()=>{if(rg)rg.gain.value=0}}})();
 function go(n){name=n;cur=scenes[n];chimeAt=performance.now()/1000;try{chime.currentTime=0;chime.play().catch(()=>{})}catch(e){}
  if(cur.enter)cur.enter()}
 function chiming(){return performance.now()/1000-chimeAt<CHIME_SEC}
 function stop(){chime.pause();sfx.stop();Speech.stop()}
 function start(){for(const k in status)delete status[k];Object.assign(status,{hp:150,hpMax:200,mp:80,mpMax:120});go(FIRST)}
 function update(dt,inp){return cur.update(dt,inp)}
 function draw(x,W,H){cur.draw(x,W,H)}
 // 縁取り付きの文字(どの背景でも読める)
 function text(x,s,px,py,size,color,align){x.font=`900 ${size}px -apple-system,"Hiragino Sans",sans-serif`;x.textAlign=align||'center';
  x.lineJoin='round';x.lineWidth=Math.max(4,size/6);x.strokeStyle='#000';x.strokeText(s,px,py);x.fillStyle=color||'#fff';x.fillText(s,px,py);x.textAlign='left'}
 function gauge(x,px,py,w,h,v,color,label){x.fillStyle='#000a';x.fillRect(px-3,py-3,w+6,h+6);x.fillStyle='#333';x.fillRect(px,py,w,h);
  x.fillStyle=color;x.fillRect(px,py,w*Math.max(0,Math.min(1,v)),h);if(label)text(x,label,px+w/2,py+h*0.75,h*0.7,'#fff')}
 return {start,stop,update,draw,go,chiming,sfx,status,scenes,text,gauge,scene:()=>name}
})();
