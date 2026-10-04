// ============================================================
// Scene2: 教室で地震。席が揺れる中、「おかしもち」の5つをマイクに向かって答える。
//   calm   … チャイムが鳴る静かな教室
//   quake  … 「地震だ！」揺れが大きくなる
//   ask    … 「地震の時の『おかしもち』は？」言えた札から埋まる。全部言えたら早く終わる
//   review … 言えなかった札を1つずつ答え合わせ。1つにつき HP が減る
//   end    … 揺れがおさまって Scene3 へ
// 判定: 音声認識(Speech)の文字に、それぞれの言葉が入っているかで決める。
// 音声認識が使えない時は、キーボードの 1〜5 で札を埋められる。
// ============================================================
(()=>{
 const ASK_SEC=20,DAMAGE=30,REVIEW_SEC=1.8;
 const ITEMS=[
  {k:'お',a:'おさない',  re:/押[さしす]|おさな|推さ|おしません|お砂|幼い/},
  {k:'か',a:'かけない',  re:/駆け|かけな|欠け|掛け|賭け|書けな|架け|走ら|かけません/},
  {k:'し',a:'しゃべらない',re:/しゃべ|喋|シャベ|しゃぶら|話さな|はなさな|話しません|喋ん|黙/},   // 認識がぶれやすいので広めに取る(「話さない」も可),
  {k:'も',a:'もどらない', re:/戻[らりれ]|もど[らりれ]/},
  {k:'ち',a:'ちかよらない',re:/近寄|近よ|ちかよ|近づ|ちかづ|近付/},
 ];
 let st,t,got,gotAt,rev,hit,power,heard;

 function mark(i){if(got[i])return;got[i]=true;gotAt[i]=performance.now()/1000;Game.sfx.ok()}

 Game.scenes.quake={
  enter(){st='calm';t=0;got=ITEMS.map(()=>false);gotAt=ITEMS.map(()=>-9);rev=-1;hit=-9;power=0;heard=''},
  update(dt,inp){t+=dt;const T=performance.now()/1000,s=Game.status;let want=0;
   if(st==='calm'){if(!Game.chiming()){st='quake';t=0}}
   else if(st==='quake'){want=Math.min(1,0.4+t*0.5);if(t>=2.5){st='ask';t=0;Speech.start()}}
   else if(st==='ask'){heard=Speech.text();
    ITEMS.forEach((it,i)=>{if(it.re.test(heard)||inp.keys['Digit'+(i+1)])mark(i)});
    const left=got.filter(g=>!g).length;want=0.7+left*0.06;   // 言えるほど揺れが弱まる
    if(left===0&&T-Math.max(...gotAt)>0.8||t>=ASK_SEC){Speech.stop();st='review';t=REVIEW_SEC;rev=-1}}
   else if(st==='review'){want=0.6;
    if(t>=REVIEW_SEC){t=0;rev=got.findIndex((g,i)=>!g&&i>rev);   // 次の言えなかった札
     if(rev<0){st='end';t=0;s.okashimochi={ok:got.filter(g=>g).length}}
     else{hit=T;s.hp=Math.max(1,s.hp-DAMAGE);Game.sfx.ng()}}}
   else if(st==='end'){want=Math.max(0,0.5-t*0.2);if(t>=4)Game.go('boss')}
   power+=(want-power)*Math.min(1,dt*3);Game.sfx.rumble(st==='ask'?power*0.25:power*0.8);   // 聞き取り中は地鳴りを小さく
   // 席: 横揺れ(左右・横振り)を大きくゆっくり、縦揺れ(前後)を細かく。外した瞬間はドンと突き上げる
   const jolt=Math.max(0,1-(T-hit)*3);
   // smooth: 土台のならしを弱めて、細かい揺れをそのまま席に伝える
   return {smooth:0.45,roll:power*(Math.sin(T*12)*0.9+Math.sin(T*19.3)*0.5)+jolt*Math.sin(T*40)*0.6,
    yaw:power*(Math.sin(T*9.1+1)*0.8+Math.sin(T*15.7)*0.5),
    pitch:power*(Math.sin(T*25)*0.5+Math.sin(T*14)*0.4)-jolt*1.0}},
  draw(x,W,H){const u=H/100,T=performance.now()/1000,s=Game.status;
   const jolt=Math.max(0,1-(T-hit)*3),amp=(power*2.2+jolt*3)*u;
   x.fillStyle='#000';x.fillRect(0,0,W,H);
   x.save();x.translate(Math.sin(T*31)*amp,Math.sin(T*37)*amp*0.6);x.rotate(Math.sin(T*9)*power*0.02);
   // 教室: 壁・黒板・窓・床・机
   x.fillStyle='#e8e0cc';x.fillRect(-W*0.1,-H*0.1,W*1.2,H*0.75);
   x.fillStyle='#8a6a45';x.fillRect(-W*0.1,62*u,W*1.2,H*0.5);
   x.fillStyle='#6b4f33';for(let i=0;i<14;i++)x.fillRect(-W*0.1,62*u+i*3.4*u,W*1.2,0.3*u);
   x.fillStyle='#7a5a36';x.fillRect(W*0.2-1*u,14*u,W*0.5+2*u,36*u);x.fillStyle='#22503a';x.fillRect(W*0.2,15*u,W*0.5,34*u);   // 黒板
   x.fillStyle='#cfe0d6';x.font=`${3*u}px "Hiragino Maru Gothic ProN",sans-serif`;x.fillText('10月4日(日)　日直: H3',W*0.21,20*u);
   x.fillStyle='#bfe3f7';for(let i=0;i<2;i++){x.fillRect(W*0.76+i*W*0.11,16*u,W*0.1,30*u)}   // 窓
   x.strokeStyle='#fff';x.lineWidth=0.6*u;for(let i=0;i<2;i++){x.strokeRect(W*0.76+i*W*0.11,16*u,W*0.1,30*u)}
   x.fillStyle='#444';x.fillRect(W*0.07,12*u,W*0.07,10*u);x.fillStyle='#f33';x.fillRect(W*0.08,14*u,W*0.05,3*u);   // スピーカー
   // 揺れる蛍光灯
   for(const lx of [0.3,0.62]){const a=Math.sin(T*3+lx*5)*power*0.6;x.save();x.translate(W*lx,-2*u);x.rotate(a);
    x.strokeStyle='#777';x.lineWidth=0.4*u;x.beginPath();x.moveTo(0,0);x.lineTo(0,9*u);x.stroke();x.fillStyle='#fffbe0';x.fillRect(-9*u,9*u,18*u,1.6*u);x.restore()}
   // 机(手前ほど大きい)。揺れでずれる
   for(let r=0;r<2;r++)for(let c=0;c<4;c++){const sc=1+r*0.5,dx=W*(0.14+c*0.24)+Math.sin(T*7+c*2+r)*power*2*u-(r*W*0.03),dy=(66+r*14)*u;
    x.fillStyle='#c9a36b';x.fillRect(dx,dy,13*u*sc,2*u*sc);x.fillStyle='#777';x.fillRect(dx+1*u*sc,dy+2*u*sc,0.8*u*sc,9*u*sc);x.fillRect(dx+11*u*sc,dy+2*u*sc,0.8*u*sc,9*u*sc)}
   x.restore();
   if(jolt>0){x.fillStyle=`rgba(255,40,40,${jolt*0.35})`;x.fillRect(0,0,W,H)}
   // HP は常に表示
   Game.text(x,'HP',W*0.04,7*u,4*u,'#f77','left');Game.gauge(x,W*0.09,3.5*u,W*0.25,4*u,s.hp/s.hpMax,'#e44',`${Math.round(s.hp)} / ${s.hpMax}`);
   if(st==='calm')Game.text(x,'― 1時間目 ―',W/2,58*u,5*u,'#fff');
   else if(st==='quake')Game.text(x,'地震だ！！',W/2,34*u,(10+Math.sin(T*30)*1)*u,'#ff4a3a');
   else{
    if(st==='ask'){Game.text(x,'地震の時の『おかしもち』は？',W/2,60*u,6.5*u,'#ffe14a');
     Game.gauge(x,W*0.25,64*u,W*0.5,2*u,1-t/ASK_SEC,'#fff');
     Game.text(x,heard?`「${heard.slice(-28)}」`:(Speech.supported()&&!Speech.error()?'マイクに向かって5つ答えよう':'音声認識が使えません(キーボードの 1〜5)'),W/2,96*u,3*u,heard?'#fff':'#ccc')}
    else if(st==='end')Game.text(x,got.every(g=>g)?'全部言えた！揺れがおさまった':'揺れがおさまった…',W/2,60*u,6*u,'#fff');
    // 5枚の札
    const cw=W*0.17,gap=W*0.015,x0=W/2-(cw*5+gap*4)/2;
    ITEMS.forEach((it,i)=>{const px=x0+i*(cw+gap),py=70*u,ok=got[i],miss=!ok&&(st==='end'||st==='review'&&i<=rev),pop=Math.max(0,1-(T-gotAt[i])*4);
     x.fillStyle=ok?'#1f9d55':miss?'#b3261e':'#000a';x.fillRect(px-pop*u,py-pop*u,cw+pop*2*u,20*u+pop*2*u);
     x.strokeStyle=st==='review'&&i===rev?'#fff':'#fff6';x.lineWidth=0.5*u;x.strokeRect(px,py,cw,20*u);
     Game.text(x,it.k,px+cw/2,py+9*u,8*u,'#fff');
     Game.text(x,ok||miss?it.a:'？？？',px+cw/2,py+16.5*u,Math.min(3.4*u,cw/7),ok?'#cfc':miss?'#fdd':'#aaa')});
    if(st==='review'&&rev>=0)Game.text(x,`「${ITEMS[rev].k}」は ${ITEMS[rev].a}！　HP -${DAMAGE}`,W/2,60*u,5.5*u,'#ff5a4a')}}
 };
})();
