// ============================================================
// Speech: ブラウザの音声認識(Chrome)で、話した言葉を文字にする。
//   Speech.start()       … 聞き始める(途中で切れても自動で聞き直す)
//   Speech.text()        … ここまでに聞こえた文字(途中経過を含む)
//   await Speech.stop()  … 止めて、最後の結果が届くのを少し待つ
// 注意: マイクは Mac の「サウンド > 入力」で選ばれているものが使われる。インターネットが必要。
// ============================================================
const Speech=(()=>{
 const R=window.SpeechRecognition||window.webkitSpeechRecognition;
 let sr=null,on=false,base='',cur='',err='',onEnd=null;
 function begin(){try{sr=new R();sr.lang='ja-JP';sr.interimResults=true;sr.continuous=true;
   sr.onresult=e=>{cur=Array.from(e.results).map(r=>r[0].transcript).join(' ')};
   sr.onerror=e=>{if(e.error!=='no-speech'&&e.error!=='aborted')err=e.error};
   sr.onend=()=>{base+=cur+' ';cur='';sr=null;if(on&&!err)begin();else if(onEnd){onEnd();onEnd=null}};
   sr.start()}catch(e){err=String(e&&e.message||e);sr=null}}
 function start(){base='';cur='';err='';on=true;if(R&&!sr)begin()}
 function stop(){on=false;return new Promise(res=>{if(!sr)return res();const t=setTimeout(()=>{onEnd=null;res()},1500);
  onEnd=()=>{clearTimeout(t);res()};try{sr.stop()}catch(e){clearTimeout(t);res()}})}
 return {start,stop,text:()=>(base+cur).trim(),supported:()=>!!R,error:()=>err}
})();
