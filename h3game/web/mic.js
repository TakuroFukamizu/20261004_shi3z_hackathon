// ============================================================
// Mic: マイクの音量を測り、声を録音する(16kHz モノラルの WAV)。
//   Mic.init()          … マイクを開く。"USB PnP" の機器があればそれを選ぶ
//   Mic.level()         … 今の音量 0..1(確認画面のメーター用)
//   Mic.start() / await Mic.stop() … 録音。stop は {wav(base64), loud(0..100), db, seconds, voiced(声が出ていた秒数)}
// 音量を測るので、ブラウザの自動音量調整・雑音除去は切っている。
// ============================================================
const Mic=(()=>{
 const RATE=16000;
 const DB_MIN=-42,DB_MAX=-8;   // この範囲を 音量 0..100 に当てる(マイクに合わせて調整)
 let ctx=null,stream=null,label='',err='',lv=0,rec=null,rms=[];
 const open=id=>navigator.mediaDevices.getUserMedia({audio:{deviceId:id?{exact:id}:undefined,channelCount:1,echoCancellation:false,noiseSuppression:false,autoGainControl:false}});
 async function init(){if(stream)return true;
  try{stream=await open();
   const usb=(await navigator.mediaDevices.enumerateDevices()).find(d=>d.kind==='audioinput'&&/USB PnP/i.test(d.label));
   if(usb&&!/USB PnP/i.test(stream.getAudioTracks()[0].label)){stream.getTracks().forEach(t=>t.stop());stream=await open(usb.deviceId)}
   label=stream.getAudioTracks()[0].label;
   ctx=new AudioContext({sampleRate:RATE});
   const src=ctx.createMediaStreamSource(stream),proc=ctx.createScriptProcessor(2048,1,1),mute=ctx.createGain();mute.gain.value=0;
   proc.onaudioprocess=e=>{const d=e.inputBuffer.getChannelData(0);let s=0;for(let i=0;i<d.length;i++)s+=d[i]*d[i];
    const r=Math.sqrt(s/d.length);lv=Math.max(r,lv*0.85);
    if(rec){rec.push(new Float32Array(d));rms.push(r)}};
   src.connect(proc);proc.connect(mute);mute.connect(ctx.destination);err='';return true}
  catch(e){err=String(e&&e.message||e);stream=null;return false}}
 function resume(){if(ctx&&ctx.state==='suspended')ctx.resume()}
 const toDb=r=>20*Math.log10(Math.max(1e-5,r));
 const score=db=>Math.round(Math.max(0,Math.min(100,(db-DB_MIN)/(DB_MAX-DB_MIN)*100)));
 function level(){return Math.max(0,Math.min(1,(toDb(lv)-DB_MIN-10)/(DB_MAX-DB_MIN-10)))}
 function start(){resume();rec=[];rms=[]}
 function stop(){const chunks=rec||[],r=rms.slice().sort((a,b)=>b-a);rec=null;
  // 音量: 大きかった上位 2割 の平均(一瞬の雑音や無音に引っ張られない)
  const top=r.slice(0,Math.max(1,Math.ceil(r.length*0.2)));const loudRms=top.length?top.reduce((a,b)=>a+b,0)/top.length:0;
  const n=chunks.reduce((a,c)=>a+c.length,0),pcm=new DataView(new ArrayBuffer(44+n*2));
  const str=(o,t)=>{for(let i=0;i<t.length;i++)pcm.setUint8(o+i,t.charCodeAt(i))};
  str(0,'RIFF');pcm.setUint32(4,36+n*2,true);str(8,'WAVEfmt ');pcm.setUint32(16,16,true);pcm.setUint16(20,1,true);pcm.setUint16(22,1,true);
  pcm.setUint32(24,RATE,true);pcm.setUint32(28,RATE*2,true);pcm.setUint16(32,2,true);pcm.setUint16(34,16,true);str(36,'data');pcm.setUint32(40,n*2,true);
  let o=44;for(const c of chunks)for(let i=0;i<c.length;i++,o+=2)pcm.setInt16(o,Math.max(-1,Math.min(1,c[i]))*32767,true);
  const u=new Uint8Array(pcm.buffer);let bin='';for(let i=0;i<u.length;i+=8192)bin+=String.fromCharCode.apply(null,u.subarray(i,i+8192));
  const db=toDb(loudRms),voiced=rms.filter(v=>toDb(v)>DB_MIN+8).length*2048/RATE;   // 声が出ていた秒数
  return {wav:btoa(bin),loud:score(db),db:+db.toFixed(1),seconds:n/RATE,voiced:+voiced.toFixed(1)}}
 return {init,resume,level,start,stop,ok:()=>!!stream,label:()=>label,error:()=>err}
})();
