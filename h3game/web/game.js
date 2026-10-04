// ============================================================
// Game: シーンの切り替えと、シーンをまたいで持ち回るステータス。
// index.html(土台)から毎フレーム呼ばれる。
//   Game.scenes.名前 = {enter(), update(dt, inp), draw(x, W, H)}   ← 各 scene_*.js が登録する
//     update は席の動き {pitch, roll, yaw}(-1..1) を返す
//   Game.go('名前')   … シーンを切り替える
//   Game.status       … {hp, mp, ...} シーン間で共有
// inp: {x, y, twist, throttle, x2, y2, twist2, throttle2, rudder, brakeL, brakeR,
//       fire, fire2, buttons1[], buttons2[]}   (軸は -1..1、片側の軸は 0..1。y は手前に引くとプラス)
// ============================================================
const Game=(()=>{
 const FIRST='gate';
 const status={};const scenes={};let cur=null,name='';
 function go(n){name=n;cur=scenes[n];if(cur.enter)cur.enter()}
 function start(){for(const k in status)delete status[k];Object.assign(status,{hp:0,mp:0});go(FIRST)}
 function update(dt,inp){return cur.update(dt,inp)}
 function draw(x,W,H){cur.draw(x,W,H)}
 // 縁取り付きの文字(どの背景でも読める)
 function text(x,s,px,py,size,color,align){x.font=`900 ${size}px -apple-system,"Hiragino Sans",sans-serif`;x.textAlign=align||'center';
  x.lineJoin='round';x.lineWidth=Math.max(4,size/6);x.strokeStyle='#000';x.strokeText(s,px,py);x.fillStyle=color||'#fff';x.fillText(s,px,py);x.textAlign='left'}
 function gauge(x,px,py,w,h,v,color,label){x.fillStyle='#000a';x.fillRect(px-3,py-3,w+6,h+6);x.fillStyle='#333';x.fillRect(px,py,w,h);
  x.fillStyle=color;x.fillRect(px,py,w*Math.max(0,Math.min(1,v)),h);if(label)text(x,label,px+w/2,py+h*0.75,h*0.7,'#fff')}
 return {start,update,draw,go,status,scenes,text,gauge,scene:()=>name}
})();
