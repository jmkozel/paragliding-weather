// Separate Cloudflare Worker for PWA push subscriptions.
// Bind KV namespace PUSH_SUBSCRIPTIONS and secret PUSH_API_TOKEN.
// Public registration is same-origin constrained; private listing is bearer-protected.
const ALLOWED_ORIGIN="https://jmkozel.github.io";
const headers={"Access-Control-Allow-Origin":ALLOWED_ORIGIN,"Access-Control-Allow-Methods":"GET,POST,DELETE,OPTIONS","Access-Control-Allow-Headers":"Content-Type,Authorization","Cache-Control":"no-store"};
const reply=(body,status=200)=>new Response(JSON.stringify(body),{status,headers:{...headers,"Content-Type":"application/json"}});
async function digest(value){const bytes=await crypto.subtle.digest("SHA-256",new TextEncoder().encode(value));return [...new Uint8Array(bytes)].map(b=>b.toString(16).padStart(2,"0")).join("");}
export default {
  async fetch(request,env){
    const url=new URL(request.url);
    if(request.method==="OPTIONS")return new Response(null,{status:204,headers});
    if(!env.PUSH_SUBSCRIPTIONS)return reply({error:"Missing KV binding"},503);
    if(url.pathname==="/health"&&request.method==="GET")return reply({ready:true});
    if(url.pathname==="/subscriptions"&&request.method==="GET"){
      if(!env.PUSH_API_TOKEN||request.headers.get("Authorization")!=="Bearer "+env.PUSH_API_TOKEN)return reply({error:"Unauthorized"},401);
      const entries=[];let cursor;
      do{
        const page=await env.PUSH_SUBSCRIPTIONS.list({prefix:"sub:",cursor});
        for(const key of page.keys){
          const value=await env.PUSH_SUBSCRIPTIONS.get(key.name,"json");
          if(value)entries.push({id:key.name.slice(4),subscription:value});
        }
        cursor=page.list_complete?null:page.cursor;
      }while(cursor);
      return reply({subscriptions:entries});
    }
    if(url.pathname==="/subscriptions"&&["POST","DELETE"].includes(request.method)){
      if(request.headers.get("Origin")!==ALLOWED_ORIGIN)return reply({error:"Origin not allowed"},403);
      let data;try{data=await request.json();}catch{return reply({error:"Invalid JSON"},400);}
      const sub=data?.subscription;
      if(typeof sub?.endpoint!=="string"||!sub.endpoint.startsWith("https://")||sub.endpoint.length>2048||typeof sub.keys?.p256dh!=="string"||typeof sub.keys?.auth!=="string")return reply({error:"Invalid subscription"},400);
      const key="sub:"+await digest(sub.endpoint);
      if(request.method==="POST")await env.PUSH_SUBSCRIPTIONS.put(key,JSON.stringify(sub));
      else await env.PUSH_SUBSCRIPTIONS.delete(key);
      return reply({ok:true});
    }
    return reply({error:"Not found"},404);
  }
};
