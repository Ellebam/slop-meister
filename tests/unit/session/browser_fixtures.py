"""Synthetic page and protocol programs for the browser consumer tests."""

FIXTURE = """
const {operate,pageStep}=require(process.argv[1]);
const fault=process.argv[2];
const secret=fault==='otp'?
 require('node:crypto').randomInt(1000000).toString().padStart(6,'0'):'dummy-private-value';
let clicks=0,events=0,authenticated=false;
class Input {
 constructor(id,type){this.id=id;this.type=type;this.nodeName='INPUT';this.isConnected=true;this.stored='';}
 get value(){return this.stored} set value(v){this.stored=v}
 checkVisibility(){return fault!=='hidden'}
 getBoundingClientRect(){return {x:0,y:0,width:10,height:10}}
 contains(e){return this===e}
 focus(){throw Error('native focus must not run')}
 dispatchEvent(){events++;if(fault==='changed')this.stored+='changed';if(fault==='gated')button.disabled=false;}
}
const field=new Input('field',fault==='otp'?'tel':'password');
const button={disabled:['gated','disabled'].includes(fault),isConnected:true,
 checkVisibility:()=>true,
 getBoundingClientRect:()=>({x:20,y:0,width:10,height:10}),contains:e=>e===button,
 click(){clicks++;authenticated=field.value===secret}};
global.HTMLInputElement=Input;
global.location={origin:fault==='origin'?'https://wrong.example':'https://example.com',pathname:'/login'};
global.document={querySelectorAll:s=>s==='*'?[field,button]:s==='#field'?(fault==='duplicate'?[field,field]:[field]):s==='#submit'?(fault==='duplicate-submit'?[button,button]:[button]):[],elementFromPoint:x=>fault==='covered'?null:x<20?field:button};
const requests=[];
const client={async send(method,params){
 requests.push({method,params});
 if(method==='Runtime.evaluate')return {result:{objectId:'page'}};
 if(method!=='Runtime.callFunctionOn')throw Error('unexpected native input');
 if(params.functionDeclaration.includes(secret))throw Error('value in source');
 return {result:{value:pageStep(params.arguments[0].value)}};
}};
(async()=>{
 let result,failed=false;
 try{result=await operate(client,{action:'fill',step:{origin:'https://example.com',path:'/login',fields:[{selector:'#field',types:[field.type],value:secret}],submit:'#submit'}})}catch{failed=true}
 const output={result,failed,clicks,events,authenticated,
  credentialRetained:field.value.includes(secret),
  secretCalls:requests.filter(r=>JSON.stringify(r.params).includes(secret)).length,
  methods:requests.map(r=>r.method)};
 if(JSON.stringify(output).includes(secret))throw Error('credential output detected');
 console.log(JSON.stringify(output));
})();
"""

SOCKET_FIXTURE = """
const fault=process.argv[2];
global.WebSocket=class {
 constructor(){this.listeners={};setImmediate(()=>this.listeners.open({}));}
 addEventListener(name,listener){this.listeners[name]=listener;}
 send(raw){
  const request=JSON.parse(raw);
  if(request.method!=='Accessibility.getFullAXTree')throw Error('wrong subject');
  const name=fault==='large-output'?'x'.repeat(300000):'Login';
  const extra=fault==='large-output'?'':fault==='oversize-frame'?'x'.repeat(17*1024*1024):
    fault==='unicode-frame'?'é'.repeat(9*1024*1024):'x'.repeat(350000);
  const result={nodes:[{ignored:false,role:{value:'button'},name:{value:name},extra}]};
  setImmediate(()=>this.listeners.message({data:JSON.stringify({id:request.id,result})}));
 }
 close(){}
};
"""
