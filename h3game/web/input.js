// ============================================================
// H3Input: スティック2本 + ペダル の共通入力部品
//   役割(スティック1の左右、ペダルの舵 など)ごとに「どの機器のどの軸か」を覚え、
//   ゲームからは H3Input.get('stick1_x') のように -1..1 の値で読む。
//   割り当ては /devices の画面で行い、localStorage と bridge(/input.json) に保存する。
//   注意: ブラウザは「ボタンを押す」か「軸を大きく動かす」まで機器を出さない。
// ============================================================
const H3Input=(()=>{
 const ROLES=[
  {key:'stick1_x',label:'スティック1 左右',dev:'stick1'},
  {key:'stick1_y',label:'スティック1 前後',dev:'stick1'},
  {key:'stick1_twist',label:'スティック1 ひねり',dev:'stick1'},
  {key:'stick1_throttle',label:'スティック1 スロットル',dev:'stick1',oneside:true},
  {key:'stick2_x',label:'スティック2 左右',dev:'stick2'},
  {key:'stick2_y',label:'スティック2 前後',dev:'stick2'},
  {key:'stick2_twist',label:'スティック2 ひねり',dev:'stick2'},
  {key:'stick2_throttle',label:'スティック2 スロットル',dev:'stick2',oneside:true},
  {key:'rudder',label:'ペダル 左右(舵)',dev:'pedals'},
  {key:'brake_l',label:'ペダル 左を踏む',dev:'pedals',oneside:true},
  {key:'brake_r',label:'ペダル 右を踏む',dev:'pedals',oneside:true},
 ];
 const STANDALONE=(typeof location!=='undefined')&&location.protocol==='file:';
 let map={};            // key -> {id,index,axis,center,min,max}
 let pads=[];           // 直近に見えた機器
 let listeners=[];
 // Mac 側(bridge の /pads)で読んだ機器を優先。届かない時だけブラウザの Gamepad API を使う
 let macPads=null,macT=0,macBusy=false;
 function pollMac(){if(STANDALONE||macBusy)return;macBusy=true;
  fetch('/pads').then(r=>r.json()).then(j=>{macPads=(j&&j.pads)||[];macT=performance.now()}).catch(()=>{}).finally(()=>{macBusy=false})}
 if(!STANDALONE){setInterval(pollMac,33)}
 function pollPads(){
  if(macPads&&performance.now()-macT<1500&&macPads.length){pads=macPads.map(p=>({id:p.id+' (Mac)',index:p.index,axes:p.axes,buttons:p.buttons,mac:true}));return pads}
  let gp=[];try{gp=navigator.getGamepads?Array.from(navigator.getGamepads()):[]}catch(e){}
  pads=gp.filter(g=>g).map(g=>({id:g.id,index:g.index,axes:Array.from(g.axes),buttons:Array.from(g.buttons).map(b=>b.pressed),raw:g}));return pads}
 function source(){return (macPads&&performance.now()-macT<1500&&macPads.length)?'mac':'browser'}
 function findPad(m){if(!m)return null;let p=pads.find(q=>q.index===m.index&&q.id===m.id);   // まず同じ番号・同じ名前
  if(!p){const same=pads.filter(q=>q.id===m.id);const used=Object.values(map).filter(o=>o&&o.id===m.id&&o.index!==m.index).map(o=>o.index);
   p=same.find(q=>!used.includes(q.index))||same[0]||null}   // 番号が変わっていたら同じ名前の空いている機器
  return p}
 function norm(m,raw){if(m==null||raw==null)return 0;const c=m.center||0;
  const up=(m.max!=null&&m.max>c+0.05)?m.max-c:1-c,dn=(m.min!=null&&m.min<c-0.05)?c-m.min:1+c;
  let v=raw>=c?(raw-c)/Math.max(0.05,up):(raw-c)/Math.max(0.05,dn);
  if(m.invert)v=-v;return Math.max(-1,Math.min(1,v))}
 const DEAD=0.12;
 function get(key){const m=map[key];const p=findPad(m);if(!p)return 0;const role=ROLES.find(r=>r.key===key);
  let v=norm(m,p.axes[m.axis]);if(role&&role.oneside)v=Math.max(0,m.dir<0?-v:v);
  if(Math.abs(v)<DEAD)return 0;return Math.sign(v)*(Math.abs(v)-DEAD)/(1-DEAD)}
 function buttons(dev){const r=ROLES.find(q=>q.dev===dev&&map[q.key]);if(!r)return[];const p=findPad(map[r.key]);return p?p.buttons:[]}
 function padFor(dev){const r=ROLES.find(q=>q.dev===dev&&map[q.key]);return r?findPad(map[r.key]):null}
 // ---- 自動割り当て: 挿すだけで スティック1/2・ペダル が決まる(手で割り当てた役は上書きしない) ----
 const isStick=p=>/t\.16000|thrustmaster|joystick|stick|hotas/i.test(p.id)||(p.axes.length>=3&&p.buttons.length>=4);
 const isPedal=p=>/pedal|rudder|saitek|crosswind|logitech g/i.test(p.id)||(p.axes.length<=3&&p.buttons.length<=1);
 const AXES={stick:{x:0,y:1,twist:2,throttle:3},pedals:{brake_l:0,brake_r:1,rudder:2}};   // 一般的な並び(T.16000M / Saitek)
 const rest={};   // 機器ごとに最初に見えた時の値(ペダルやスロットルの「休み位置」)
 function autoAssign(){const sticks=pads.filter(p=>isStick(p)&&!isPedal(p)).sort((a,b)=>a.index-b.index);
  const pedals=pads.filter(isPedal).sort((a,b)=>a.index-b.index);
  for(const p of pads){const k=p.index+'|'+p.id;if(!rest[k])rest[k]=p.axes.slice()}
  const put=(key,p,axis)=>{const m=map[key];if(m&&!m.auto)return;   // 手で決めたものは残す
   if(m&&m.auto&&m.id===p.id&&m.index===p.index&&m.axis===axis)return;
   if(axis>=p.axes.length)return;const r=rest[p.index+'|'+p.id];const role=ROLES.find(q=>q.key===key);
   const c=role.oneside?(r?r[axis]:0):0;map[key]={id:p.id,index:p.index,axis,center:+c.toFixed(3),dir:c>0?-1:1,auto:true};changed=true};
  let changed=false;
  const dev=[['stick1',sticks[0]],['stick2',sticks[1]],['pedals',pedals[0]]];
  for(const [name,p] of dev){if(!p)continue;const ax=name==='pedals'?AXES.pedals:AXES.stick;
   for(const r of ROLES.filter(q=>q.dev===name)){const sub=r.key.replace(name+'_','');put(r.key,p,ax[sub]!=null?ax[sub]:ax[r.key])}}
  if(changed)fire()}
 function values(){pollPads();autoAssign();const o={};for(const r of ROLES)o[r.key]=get(r.key);return o}
 function load(){try{const s=localStorage.getItem('h3_input');if(s)map=JSON.parse(s)}catch(e){}
  if(!STANDALONE)return fetch('/input.json').then(r=>r.ok?r.json():null).then(j=>{if(j&&Object.keys(j).length)map=j;fire()}).catch(()=>{});
  fire();return Promise.resolve()}
 function save(){try{localStorage.setItem('h3_input',JSON.stringify(map))}catch(e){}
  if(!STANDALONE)fetch('/input.json',{method:'POST',body:JSON.stringify(map)}).catch(()=>{});fire()}
 function fire(){for(const f of listeners)f(map)}
 // 割り当て: seconds 秒のあいだ、いちばん大きく動いた軸を役割に結びつける
 function assign(key,seconds,onTick){return new Promise(res=>{const t0=performance.now();const base={};const seen={};
  const iv=setInterval(()=>{pollPads();const el=(performance.now()-t0)/1000;
   for(const p of pads){const k=p.index+'|'+p.id;
    if(!base[k]){base[k]=p.axes.slice();seen[k]={min:p.axes.slice(),max:p.axes.slice()}}
    for(let a=0;a<p.axes.length;a++){seen[k].min[a]=Math.min(seen[k].min[a],p.axes[a]);seen[k].max[a]=Math.max(seen[k].max[a],p.axes[a])}}
   let best=null,bs=0.45;   // これより小さい動きは無視(静止のふらつき)
   for(const p of pads){const k=p.index+'|'+p.id;for(let a=0;a<p.axes.length;a++){const sc=seen[k].max[a]-seen[k].min[a];if(sc>bs){bs=sc;best={p,a,k}}}}
   if(onTick)onTick(el,best?{id:best.p.id,index:best.p.index,axis:best.a}:null);
   const done=el>=seconds||(best&&el>=1.5&&Math.abs(best.p.axes[best.a]-base[best.k][best.a])<0.08&&bs>0.6);   // 大きく動いて戻ったら早めに確定
   if(done){clearInterval(iv);
    if(best){const c=base[best.k][best.a];const cur=best.p.axes[best.a];const s=seen[best.k];
     map[key]={id:best.p.id,index:best.p.index,axis:best.a,center:+c.toFixed(3),min:+s.min[best.a].toFixed(3),max:+s.max[best.a].toFixed(3),
      dir:(s.max[best.a]-c)>=(c-s.min[best.a])?1:-1};save();res(map[key])}
    else res(null)}},50)})}
 // ボタンの割り当て: seconds 秒のあいだに押されたボタンを役割に結びつける
 function assignButton(key,seconds){return new Promise(res=>{const t0=performance.now();
  const iv=setInterval(()=>{pollPads();const el=(performance.now()-t0)/1000;
   for(const p of pads){const b=p.buttons.findIndex(x=>x);if(b>=0){clearInterval(iv);map[key]={id:p.id,index:p.index,button:b,type:'button'};save();res(map[key]);return}}
   if(el>=seconds){clearInterval(iv);res(null)}},50)})}
 function pressed(key){const m=map[key];if(!m||m.type!=='button')return null;const p=findPad(m);return !!(p&&p.buttons[m.button])}   // 未割り当てなら null
 function invert(key){const m=map[key];if(!m)return;m.invert=!m.invert;delete m.auto;save()}
 function center(key){const m=map[key];const p=findPad(m);if(!m||!p)return;m.center=+p.axes[m.axis].toFixed(3);delete m.auto;save()}
 function centerAll(){pollPads();let n=0;for(const r of ROLES){const m=map[r.key];const p=findPad(m);if(!m||!p||m.type==='button')continue;
   const raw=p.axes[m.axis];if(raw==null)continue;
   if(r.oneside){m.center=+raw.toFixed(3);m.dir=raw>0?-1:1}else{m.center=+raw.toFixed(3)}n++}
  if(n)save();return n}
 function clear(key){if(key)delete map[key];else map={};save()}
 function devName(dev){const p=padFor(dev);return p?p.id:''}
 return {ROLES,get,values,buttons,padFor,devName,pollPads,autoAssign,source,pads:()=>pads,load,save,assign,assignButton,pressed,invert,center,centerAll,clear,map:()=>map,onChange:f=>listeners.push(f),STANDALONE}
})();
