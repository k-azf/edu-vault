/* EduVault Desktop - local Firebase REST compatibility layer.
 * Purpose: allow the desktop app to start fully offline without loading the Firebase JS SDK.
 * It implements only the Firebase Auth/Firestore/Storage surface used by EduVault.
 */
(function(){
  'use strict';
  const getCfg = () => window.__EDUVAULT_FIREBASE_CONFIG__ || {};
  const KEY = 'ev_firebase_rest_session_v1';
  const API = 'https://identitytoolkit.googleapis.com/v1';
  const FS = () => `https://firestore.googleapis.com/v1/projects/${encodeURIComponent(getCfg().projectId||'')}/databases/(default)/documents`;
  const ST = () => `https://firebasestorage.googleapis.com/v0/b/${encodeURIComponent(getCfg().storageBucket||'')}/o`;
  let session = null;
  try { session = JSON.parse(localStorage.getItem(KEY)||'null'); } catch(e) {}
  const saveSession=()=>{ try{localStorage.setItem(KEY,JSON.stringify(session));}catch(e){} };
  const now=()=>Date.now();
  const expired=()=>!session || !session.idToken || !session.expiresAt || now() > session.expiresAt-60000;
  const json=async r=>{let t=await r.text();let d={};try{d=t?JSON.parse(t):{}}catch(e){d={raw:t}};if(!r.ok){let m=d?.error?.message||r.statusText||'Firebase REST request failed';throw new Error(m)}return d};
  async function refresh(){
    if(!session?.refreshToken) return false;
    const r=await fetch(`https://securetoken.googleapis.com/v1/token?key=${encodeURIComponent(getCfg().apiKey)}`,{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams({grant_type:'refresh_token',refresh_token:session.refreshToken})});
    const d=await json(r);
    session.idToken=d.id_token; session.refreshToken=d.refresh_token||session.refreshToken; session.localId=d.user_id||session.localId; session.expiresAt=now()+Number(d.expires_in||3600)*1000; saveSession(); return true;
  }
  async function token(){
    if(!session?.idToken) return null;
    if(expired()){ try{if(await refresh()) return session.idToken}catch(e){session=null;saveSession();return null} }
    return session.idToken;
  }
  function wrap(data){
    if(data===undefined) return {nullValue:null};
    if(data===null) return {nullValue:null};
    if(typeof data==='string') return {stringValue:data};
    if(typeof data==='boolean') return {booleanValue:data};
    if(typeof data==='number') return Number.isInteger(data)?{integerValue:String(data)}:{doubleValue:data};
    if(data instanceof Date) return {timestampValue:data.toISOString()};
    if(data && data.__serverTimestamp) return {timestampValue:new Date().toISOString()};
    if(Array.isArray(data)) return {arrayValue:{values:data.map(wrap)}};
    if(typeof data==='object') { const fields={}; Object.keys(data).forEach(k=>{fields[k]=wrap(data[k])}); return {mapValue:{fields}}; }
    return {stringValue:String(data)};
  }
  function unwrap(v){
    if(!v) return null;
    if('nullValue' in v) return null;
    if('stringValue' in v) return v.stringValue;
    if('booleanValue' in v) return v.booleanValue;
    if('integerValue' in v) return Number(v.integerValue);
    if('doubleValue' in v) return v.doubleValue;
    if('timestampValue' in v) return v.timestampValue;
    if('bytesValue' in v) return v.bytesValue;
    if('referenceValue' in v) return v.referenceValue;
    if('arrayValue' in v) return (v.arrayValue.values||[]).map(unwrap);
    if('mapValue' in v) return Object.fromEntries(Object.entries(v.mapValue.fields||{}).map(([k,x])=>[k,unwrap(x)]));
    return null;
  }
  function toDoc(obj){return {fields:Object.fromEntries(Object.entries(obj||{}).map(([k,v])=>[k,wrap(v)]))};}
  function fromDoc(doc){return Object.fromEntries(Object.entries(doc?.fields||{}).map(([k,v])=>[k,unwrap(v)]));}
  async function fsGet(path){ const t=await token(); if(!t)throw new Error('Firebase authentication is not ready'); const r=await fetch(`${FS()}/${path}`,{headers:{Authorization:`Bearer ${t}`}}); return json(r); }
  async function fsSet(path,data,merge){
    const t=await token();if(!t)throw new Error('Firebase authentication is not ready');
    let payload=data||{};
    if(merge){
      try{ const old=await fsGet(path); payload=Object.assign({},fromDoc(old),payload); }catch(e){ if(!String(e.message||'').includes('NOT_FOUND')) throw e; }
    }
    const r=await fetch(`${FS()}/${path}`,{method:'PATCH',headers:{Authorization:`Bearer ${t}`,'Content-Type':'application/json'},body:JSON.stringify(toDoc(payload))});
    return json(r);
  }
  async function fsCreate(path,data){const t=await token();if(!t)throw new Error('Firebase authentication is not ready');const r=await fetch(`${FS()}/${path}`,{method:'POST',headers:{Authorization:`Bearer ${t}`,'Content-Type':'application/json'},body:JSON.stringify(toDoc(data))});return json(r)}
  async function fsDelete(path){const t=await token();if(!t)throw new Error('Firebase authentication is not ready');const r=await fetch(`${FS()}/${path}`,{method:'DELETE',headers:{Authorization:`Bearer ${t}`}});return r.status===404?{}:json(r)}
  async function fsList(col){const t=await token();if(!t)throw new Error('Firebase authentication is not ready');const r=await fetch(`${FS()}/${col}?pageSize=1000`,{headers:{Authorization:`Bearer ${t}`}});return json(r)}
  class Query{
    constructor(col,filters=[],limitN=null){this.col=col;this.filters=filters;this.limitN=limitN}
    where(f,op,v){return new Query(this.col,this.filters.concat([[f,op,v]]),this.limitN)}
    limit(n){return new Query(this.col,this.filters,n)}
    async get(){
      const d=await fsList(this.col); let docs=(d.documents||[]).map(x=>({id:x.name.split('/').pop(),data:()=>fromDoc(x),ref:docRef(this.col,x.name.split('/').pop())}));
      docs=docs.filter(doc=>this.filters.every(([f,op,v])=>{const a=doc.data()[f];if(op==='==')return String(a??'')===String(v??'');if(op==='!=')return String(a??'')!==String(v??'');return true}));
      if(this.limitN!=null)docs=docs.slice(0,this.limitN);
      return {docs,empty:docs.length===0,size:docs.length,forEach(fn){docs.forEach(fn)}};
    }
  }
  function docRef(col,id){return {id,path:`${col}/${id}`,set:(data,opt={})=>fsSet(`${col}/${encodeURIComponent(id)}`,data,!!opt.merge),delete:()=>fsDelete(`${col}/${encodeURIComponent(id)}`)}}
  function collection(col){return Object.assign(new Query(col),{doc:id=>docRef(col,id)})}
  const batch=()=>{const ops=[];return {delete(ref){ops.push(['delete',ref])},set(ref,data,opt){ops.push(['set',ref,data,opt])},commit:async()=>{for(const [op,ref,data,opt] of ops){if(op==='delete')await ref.delete();else await ref.set(data,opt)}}}};
  const authObj={currentUser:null,async signInAnonymously(){
    if(!navigator.onLine)throw new Error('offline');
    if(session?.idToken && !expired()){this.currentUser={uid:session.localId};return {user:this.currentUser};}
    const r=await fetch(`${API}/accounts:signUp?key=${encodeURIComponent(getCfg().apiKey)}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({returnSecureToken:true})});
    const d=await json(r);session={idToken:d.idToken,refreshToken:d.refreshToken,localId:d.localId,expiresAt:now()+Number(d.expiresIn||3600)*1000};saveSession();this.currentUser={uid:d.localId};return {user:this.currentUser};
  }};
  const storageObj={ref:()=>storageRef('')};
  function storageRef(base){return {child(p){return storageRef(base?`${base}/${p}`:p)},async put(file){
      const t=await token();if(!t)throw new Error('Firebase authentication is not ready');
      const path=base;const upload=`${ST()}?uploadType=media&name=${encodeURIComponent(path)}`;
      const r=await fetch(upload,{method:'POST',headers:{Authorization:`Bearer ${t}`,'Content-Type':file.type||'application/octet-stream'},body:file});
      const d=await json(r); const dlToken=crypto?.randomUUID?crypto.randomUUID():String(Math.random()).slice(2); 
      try{await fetch(`${ST()}/${encodeURIComponent(path)}?updateMask=metadata.firebaseStorageDownloadTokens`,{method:'PATCH',headers:{Authorization:`Bearer ${t}`,'Content-Type':'application/json'},body:JSON.stringify({metadata:{firebaseStorageDownloadTokens:dlToken}})})}catch(e){}
      this._url=`${ST()}/${encodeURIComponent(path)}?alt=media&token=${encodeURIComponent(dlToken)}`; this._data=d; return {ref:this};
    },async getDownloadURL(){if(this._url)return this._url;throw new Error('Download URL not available')},_path:base};}
  window.firebase={initializeApp(){return{}},auth:()=>authObj,firestore:()=>({collection,batch,enablePersistence:async()=>{}}),storage:()=>storageObj};
  firebase.firestore.FieldValue={serverTimestamp:()=>({__serverTimestamp:true})};
  window.__EduVaultFirebaseRest={refresh,session:()=>session};
})();
