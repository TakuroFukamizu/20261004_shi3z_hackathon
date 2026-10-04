// ============================================================
// Scene3(ラスボス): 一人称で走って帰宅する。迫ってくる生徒指導の先生たちと校長先生を
// スティックの左右でかわし、家に着いたらお母さんに「ただいま」と言う。
//   intro  … チャイムと説明
//   run    … 先生たちが次々に迫る。ぶつかると HP が減る。終盤は校長先生がこちらを追って突進してくる
//   caught … HP が尽きた。少し回復してこのシーンをやり直す
//   home   … 玄関。お母さんに「ただいま」(音声認識。使えない時はキーボードの 1)
//   clear  … 「おかえり！」
// 操作: スティック1 左右 = よける / トリガー = 気合いバリア(MP を使って少しの間ぶつからない)
// 奥行き d: 遠く(14)から近づき、1 を通り過ぎる瞬間に横位置が近ければぶつかる。
// ============================================================
(()=>{
 const RUN_SEC=24,SPEED=5,BOSS_SPEED=6.5,BOSS_CHARGES=3,FAR=14;
 const HIT_W=0.3,BOSS_W=0.45,DMG=20,BOSS_DMG=40,SHIELD_MP=20,SHIELD_SEC=1.5,HOME_SEC=10;
 const JERSEY=['#c22','#1a7a3c','#1c3f8f','#7a2a9a','#c26a12'];
 let st,t,px,objs,spawnT,dist,hitT,shieldT,prevFire,charges,bossWait,tries,heard,said,msg,msgT;

 function spawn(boss){objs.push(boss?{boss:true,x:0,d:FAR,vx:0}:
  {x:Math.random()*2.2-1.1,d:FAR,vx:t>10&&Math.random()<0.4?(Math.random()<0.5?-0.3:0.3):0,c:JERSEY[Math.floor(Math.random()*JERSEY.length)]})}
 function say(s){msg=s;msgT=performance.now()/1000}

 // 先生(正面・両手を広げて捕まえに来る)。cx,by=足元、s=1単位の大きさ
 function person(x,cx,by,s,o){
  x.fillStyle='#0003';x.beginPath();x.ellipse(cx,by,13*s,2.5*s,0,0,7);x.fill();
  x.fillStyle=o.boss?'#2b2b33':'#1c2c5a';x.fillRect(cx-6*s,by-18*s,5*s,18*s);x.fillRect(cx+1*s,by-18*s,5*s,18*s);
  x.fillStyle=o.boss?'#3a3a46':o.c;x.beginPath();x.roundRect(cx-9*s,by-40*s,18*s,24*s,3*s);x.fill();
  x.save();x.lineCap='round';x.strokeStyle=o.boss?'#3a3a46':o.c;x.lineWidth=5*s;const w=Math.sin(performance.now()/90+cx)*2*s;   // 腕を振る
  x.beginPath();x.moveTo(cx-8*s,by-37*s);x.lineTo(cx-19*s,by-44*s+w);x.moveTo(cx+8*s,by-37*s);x.lineTo(cx+19*s,by-44*s-w);x.stroke();x.restore();
  x.fillStyle='#f1c9a0';x.beginPath();x.arc(cx-19*s,by-44*s+w,2.6*s,0,7);x.arc(cx+19*s,by-44*s-w,2.6*s,0,7);x.fill();
  if(o.boss){x.fillStyle='#fff';x.beginPath();x.moveTo(cx-3*s,by-40*s);x.lineTo(cx+3*s,by-40*s);x.lineTo(cx,by-33*s);x.fill();x.fillStyle='#a11';x.fillRect(cx-0.8*s,by-39*s,1.6*s,9*s)}
  else{x.fillStyle='#fff';x.fillRect(cx-0.6*s,by-40*s,1.2*s,24*s)}
  x.fillStyle='#f1c9a0';x.beginPath();x.arc(cx,by-47*s,7.5*s,0,7);x.fill();
  x.fillStyle=o.boss?'#ccc':'#222';x.beginPath();
  if(o.boss){x.arc(cx-7*s,by-47*s,2.2*s,0,7);x.arc(cx+7*s,by-47*s,2.2*s,0,7)}else x.arc(cx,by-49.5*s,7.6*s,Math.PI*1.05,Math.PI*1.95);x.fill();
  x.strokeStyle='#222';x.lineWidth=0.9*s;x.beginPath();
  x.moveTo(cx-5.5*s,by-51*s);x.lineTo(cx-1.5*s,by-48.7*s);x.moveTo(cx+5.5*s,by-51*s);x.lineTo(cx+1.5*s,by-48.7*s);x.stroke();
  x.fillStyle='#222';x.beginPath();x.arc(cx-3.2*s,by-47*s,0.9*s,0,7);x.arc(cx+3.2*s,by-47*s,0.9*s,0,7);x.fill();
  if(o.boss){x.fillStyle='#ccc';x.fillRect(cx-3.5*s,by-45*s,7*s,1.4*s)}   // ひげ
  x.fillStyle='#711';x.beginPath();x.ellipse(cx,by-42.6*s,2.6*s,1.8*s,0,0,7);x.fill()}

 function mom(x,cx,by,s,happy){
  x.fillStyle='#5a4a7a';x.beginPath();x.roundRect(cx-10*s,by-40*s,20*s,40*s,4*s);x.fill();
  x.fillStyle='#ffe6ee';x.beginPath();x.roundRect(cx-7*s,by-34*s,14*s,30*s,3*s);x.fill();   // エプロン
  x.fillStyle='#f1c9a0';x.beginPath();x.arc(cx,by-47*s,7.5*s,0,7);x.fill();
  x.fillStyle='#4a2d1a';x.beginPath();x.arc(cx,by-49*s,8*s,Math.PI,0);x.fill();x.beginPath();x.arc(cx,by-57*s,3.2*s,0,7);x.fill();   // おだんご
  x.fillStyle='#222';x.beginPath();x.arc(cx-3*s,by-47*s,0.9*s,0,7);x.arc(cx+3*s,by-47*s,0.9*s,0,7);x.fill();
  x.strokeStyle='#a33';x.lineWidth=0.9*s;x.beginPath();if(happy)x.arc(cx,by-44.5*s,3*s,0.15,Math.PI-0.15);else{x.moveTo(cx-2*s,by-43*s);x.lineTo(cx+2*s,by-43*s)}x.stroke()}

 Game.scenes.boss={
  enter(){st='intro';t=0;px=0;objs=[];spawnT=1;dist=0;hitT=-9;shieldT=0;prevFire=false;charges=0;bossWait=1.5;tries=0;heard='';said=false;msg='';msgT=-9},
  update(dt,inp){t+=dt;const T=performance.now()/1000,s=Game.status,m={pitch:0,roll:0,yaw:0};
   if(st==='intro'){if(!Game.chiming()&&t>6){st='run';t=0}return m}
   if(st==='run'){dist+=SPEED*dt;px=Math.max(-1.1,Math.min(1.1,px+inp.x*1.9*dt));
    if(inp.fire&&!prevFire&&shieldT<=0&&s.mp>=SHIELD_MP){s.mp-=SHIELD_MP;shieldT=SHIELD_SEC;Game.sfx.ok()}
    prevFire=inp.fire;shieldT-=dt;
    // 出現: 前半は先生だけ、後半は校長先生が突進をくり返す
    const boss=t>=RUN_SEC;spawnT-=dt;
    if(spawnT<=0){spawn(false);spawnT=boss?1.7:1.2-0.55*Math.min(1,t/RUN_SEC)}
    if(boss&&!objs.some(o=>o.boss)&&charges<BOSS_CHARGES){bossWait-=dt;if(bossWait<=0){spawn(true);bossWait=1.2;if(charges===0)say('校長先生だ！！')}}
    for(const o of objs){const was=o.d;o.d-=(o.boss?BOSS_SPEED:SPEED)*dt;
     if(o.boss){if(o.d>2.5)o.x+=Math.max(-1.5*dt,Math.min(1.5*dt,px-o.x))}   // 近づくまではこちらを追う
     else{o.x+=o.vx*dt;if(Math.abs(o.x)>1.2)o.vx=-o.vx}
     if(was>1&&o.d<=1){if(o.boss)charges++;
      if(Math.abs(o.x-px)<(o.boss?BOSS_W:HIT_W)){
       if(shieldT>0)say('気合いではね返した！');
       else{s.hp=Math.max(0,s.hp-(o.boss?BOSS_DMG:DMG));hitT=T;Game.sfx.ng();say(o.boss?'校長先生につかまった！':'こらーっ！')}}}}
    objs=objs.filter(o=>o.d>0.4);
    Game.sfx.rumble(objs.some(o=>o.boss)?0.5:0);
    if(s.hp<=0){st='caught';t=0;Game.sfx.rumble(0)}
    else if(charges>=BOSS_CHARGES&&!objs.some(o=>o.boss)&&t>RUN_SEC+2){st='home';t=0;objs=[];Game.sfx.rumble(0);Speech.start()}
    const jolt=Math.max(0,1-(T-hitT)*2.5);
    m.roll=inp.x*0.6+jolt*Math.sin(T*45)*0.5;m.yaw=inp.x*0.35;m.pitch=Math.sin(T*11)*0.07-jolt*0.9;   // 走る上下動・よける傾き・ぶつかった衝撃
    if(objs.some(o=>o.boss)){m.pitch+=Math.sin(T*27)*0.12;m.smooth=0.3}
    return m}
   if(st==='caught'){if(t>3.5){const hp=Math.round(s.hpMax*0.3);Game.scenes.boss.enter();s.hp=hp;st='run';t=0}return {pitch:-0.4,roll:0,yaw:0}}
   if(st==='home'){heard=Speech.text();
    if(/ただいま|只今|タダイマ|ただ今/.test(heard)||inp.keys.Digit1){said=true;Speech.stop();Game.sfx.ok();st='clear';t=0}
    else if(t>=HOME_SEC){tries++;t=0;say(tries>=3?'声が小さくて聞こえないわよ？':'…あら、何か言った？');Speech.stop().then(()=>{if(st==='home')Speech.start()})}
    return m}
   if(st==='clear'){m.pitch=t<1.2?Math.sin(t*8)*0.25:0;return m}
   return m},
  draw(x,W,H){const u=H/100,T=performance.now()/1000,s=Game.status,hz=40*u;
   const jolt=Math.max(0,1-(T-hitT)*2.5);
   if(st==='home'||st==='clear'){   // 玄関とお母さん
    const g=x.createLinearGradient(0,0,0,H);g.addColorStop(0,'#2a2140');g.addColorStop(1,'#e58a4a');x.fillStyle=g;x.fillRect(0,0,W,H);
    x.fillStyle='#e9dcc4';x.fillRect(W*0.12,18*u,W*0.76,70*u);x.fillStyle='#7a3b2a';x.beginPath();x.moveTo(W*0.06,20*u);x.lineTo(W/2,2*u);x.lineTo(W*0.94,20*u);x.fill();
    x.fillStyle='#ffd98a';x.fillRect(W*0.18,34*u,W*0.14,18*u);x.fillRect(W*0.68,34*u,W*0.14,18*u);
    x.fillStyle='#4a3020';x.fillRect(W/2-13*u,30*u,26*u,58*u);x.fillStyle='#ffe9b8';x.fillRect(W/2-11*u,32*u,22*u,56*u);   // 開いた玄関
    x.fillStyle='#555';x.fillRect(0,88*u,W,12*u);
    const k=Math.min(1,t/1.2);mom(x,W/2,88*u,u*(0.75+0.2*(st==='clear'?1:k)),st==='clear');
    x.fillStyle='#fff';x.font=`900 ${2.6*u}px sans-serif`;x.textAlign='center';x.fillText('H3',W/2+17*u,40*u);x.textAlign='left';   // 表札
    if(st==='home'){Game.text(x,'お母さんに『ただいま』と言おう',W/2,13*u,6.5*u,'#ffe14a');
     Game.gauge(x,W*0.3,94*u,W*0.4,2*u,1-t/HOME_SEC,'#fff');
     Game.text(x,heard?`「${heard.slice(-20)}」`:(Speech.supported()&&!Speech.error()?'マイクに向かって言おう':'音声認識が使えません(キーボードの 1)'),W/2,24*u,3.2*u,'#fff')}
    else{Game.text(x,'「おかえり！」',W/2,14*u,9*u,'#ffe14a');Game.text(x,'― 帰宅成功 ―',W/2,26*u,5*u,'#fff');
     Game.text(x,`HP ${Math.round(s.hp)} / ${s.hpMax}　　MP ${Math.round(s.mp)} / ${s.mpMax}`,W/2,97*u,3.6*u,'#fff')}
    if(T-msgT<2.5&&st==='home')Game.text(x,msg,W/2,60*u,4.5*u,'#fff');
    return}
   // 帰り道(夕方): 空・遠くの町・道
   x.save();x.translate(W/2,H/2);x.rotate(jolt*Math.sin(T*40)*0.02);x.translate(-W/2+jolt*Math.sin(T*50)*2*u,-H/2);
   const g=x.createLinearGradient(0,0,0,hz);g.addColorStop(0,'#33478f');g.addColorStop(1,'#ffb36a');x.fillStyle=g;x.fillRect(-W*0.1,-H*0.1,W*1.2,hz+H*0.1);
   x.fillStyle='#ffe9a8';x.beginPath();x.arc(W*0.72-px*W*0.03,hz-4*u,6*u,0,7);x.fill();
   x.fillStyle='#3b3550';for(let i=0;i<14;i++){const hx=((i*W*0.09-px*W*0.05)%(W*1.2)+W*1.2)%(W*1.2)-W*0.1,hh=(5+(i*7%5)*2.2)*u;x.fillRect(hx,hz-hh,W*0.07,hh)}
   x.fillStyle='#5d6b4a';x.fillRect(-W*0.1,hz,W*1.2,H);
   const P=(ox,d)=>[W/2+(ox-px)*W*0.42/d,hz+(H*0.97-hz)/d];
   const [l1,y1]=P(-1.5,1),[r1]=P(1.5,1),[l2,y2]=P(-1.5,40),[r2]=P(1.5,40);
   x.fillStyle='#6f6f78';x.beginPath();x.moveTo(l1,y1);x.lineTo(r1,y1);x.lineTo(r2,y2);x.lineTo(l2,y2);x.fill();
   for(let i=0;i<12;i++){const d=((i-dist/2.5)%12+12)%12*1.1+1;   // 流れる線と電柱で速さを出す
    const [a,yy]=P(-1.5,d),[b]=P(1.5,d),[c]=P(0,d);x.fillStyle='#0000001c';x.fillRect(a,yy,b-a,Math.max(1,1.2*u/d));
    x.fillStyle='#f4f4f4';x.fillRect(c-0.6*u/d,yy,1.2*u/d,5*u/d);
    for(const side of [-1.9,1.9]){const [qx,qy]=P(side,d);x.fillStyle='#4a4038';x.fillRect(qx-0.8*u/d,qy-55*u/d,1.6*u/d,55*u/d)}}
   // 先生たち(遠い順に描く)
   for(const o of objs.slice().sort((a,b)=>b.d-a.d)){const [sx,sy]=P(o.x,Math.max(0.45,o.d));x.globalAlpha=Math.min(1,(FAR-o.d)/2);
    person(x,sx,sy,u*(o.boss?1.55:1.05)/Math.max(0.45,o.d),o);x.globalAlpha=1}
   x.restore();
   if(shieldT>0){x.strokeStyle=`rgba(120,200,255,${0.5+Math.sin(T*20)*0.2})`;x.lineWidth=3*u;x.strokeRect(1.5*u,1.5*u,W-3*u,H-3*u)}
   if(jolt>0){x.fillStyle=`rgba(255,40,40,${jolt*0.4})`;x.fillRect(0,0,W,H)}
   // HP / MP / 家までの残り
   Game.text(x,'HP',W*0.04,7*u,4*u,'#f77','left');Game.gauge(x,W*0.09,3.5*u,W*0.25,4*u,s.hp/s.hpMax,'#e44',`${Math.round(s.hp)} / ${s.hpMax}`);
   Game.text(x,'MP',W*0.04,13*u,4*u,'#7bf','left');Game.gauge(x,W*0.09,9.5*u,W*0.25,4*u,s.mp/s.mpMax,'#48e',`${Math.round(s.mp)} / ${s.mpMax}`);
   if(st==='run'){const prog=Math.min(1,(Math.min(t,RUN_SEC)/RUN_SEC)*0.7+charges/BOSS_CHARGES*0.3);
    Game.text(x,'学校',W*0.6,7*u,2.8*u,'#fff','right');Game.gauge(x,W*0.61,4*u,W*0.28,3*u,prog,'#fc6');Game.text(x,'家',W*0.9,7*u,2.8*u,'#fff','left');
    if(T-msgT<1.6)Game.text(x,msg,W/2,30*u,7*u,'#ff5a4a')}
   else if(st==='intro'){Game.text(x,'放課後。先生たちをかわして家に帰れ！',W/2,26*u,6*u,'#ffe14a');
    Game.text(x,'スティック左右: よける　　トリガー: 気合いバリア(MP 20)',W/2,34*u,3.2*u,'#fff')}
   else if(st==='caught'){x.fillStyle='#000a';x.fillRect(0,0,W,H);Game.text(x,'つかまった… 生徒指導室へ',W/2,45*u,7*u,'#ff5a4a');Game.text(x,'もう一度！',W/2,56*u,4.5*u,'#fff')}}
 };
})();
