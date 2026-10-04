// Scene3(ラスボス・仮): いまはステータスを見せるだけ。
Game.scenes.boss={
 enter(){this.t=0},
 update(dt,inp){this.t+=dt;return {pitch:0,roll:0,yaw:0}},
 draw(x,W,H){const s=Game.status,u=H/100,k=Math.min(1,this.t/0.8);
  x.fillStyle='#10131c';x.fillRect(0,0,W,H);
  Game.text(x,'Scene 3(仮)― ラスボス',W/2,16*u,6*u,'#9fc');
  const w=W*0.5,px=W/2-w/2;
  Game.text(x,'HP',px-2*u,40*u,7*u,'#f77','right');Game.gauge(x,px,33*u,w,8*u,s.hp/s.hpMax*k,'#e44',String(Math.round(s.hp*k))+' / '+s.hpMax);
  Game.text(x,'MP',px-2*u,56*u,7*u,'#7bf','right');Game.gauge(x,px,49*u,w,8*u,s.mp/s.mpMax*k,'#48e',String(Math.round(s.mp*k))+' / '+s.mpMax);
  if(s.okashimochi)Game.text(x,`おかしもち: ${s.okashimochi.ok} / 5 正解`,W/2,74*u,4*u,'#eee');
  Game.text(x,'Esc: 設定に戻る',W/2,95*u,2.6*u,'#888')}
};
