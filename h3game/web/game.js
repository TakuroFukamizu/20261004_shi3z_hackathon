// ============================================================
// Game: ゲーム本体。index.html(土台)から毎フレーム呼ばれる。
//   start()            … スタートが押された時に1回
//   update(dt, inp)    … 入力を受けて進め、席の動き {pitch, roll, yaw}(-1..1) を返す
//   draw(x, W, H)      … canvas に描く
// inp: {x, y, twist, throttle, x2, y2, twist2, throttle2, rudder, brakeL, brakeR,
//       fire, fire2, buttons1[], buttons2[]}   (軸は -1..1、片側の軸は 0..1)
// いまは仮の中身: スティック1で席が傾き、ペダル(またはひねり)で横に振れる。
// ============================================================
const Game=(()=>{
 let t=0,m={pitch:0,roll:0,yaw:0};
 function start(){t=0}
 function update(dt,inp){t+=dt;
  m.pitch=inp.y;m.roll=inp.x;m.yaw=inp.rudder||inp.twist;
  return m}
 function draw(x,W,H){
  x.fillStyle='#0b1020';x.fillRect(0,0,W,H);
  // 傾きに合わせて動く地平線
  x.save();x.translate(W/2,H/2);x.rotate(-m.roll*0.5);x.translate(m.yaw*W*0.2,-m.pitch*H*0.3);
  x.fillStyle='#16304a';x.fillRect(-W*2,-H*2,W*4,H*2);
  x.fillStyle='#1d3b2a';x.fillRect(-W*2,0,W*4,H*2);
  x.strokeStyle='#7fd';x.lineWidth=2;x.beginPath();x.moveTo(-W*2,0);x.lineTo(W*2,0);x.stroke();
  x.restore();
  x.strokeStyle='#fc6';x.lineWidth=3;x.beginPath();x.moveTo(W/2-60,H/2);x.lineTo(W/2-20,H/2);x.moveTo(W/2+20,H/2);x.lineTo(W/2+60,H/2);x.stroke();
  x.fillStyle='#eee';x.font='28px -apple-system,"Hiragino Sans",sans-serif';x.textAlign='center';
  x.fillText('ここにゲームを書く(web/game.js)',W/2,60);x.textAlign='left'}
 return {start,update,draw}
})();
