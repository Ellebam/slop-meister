"""Credential input stays bound to the page and never reaches native keyboard focus."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from slopmeister.session import browser_state as state

HELPER = Path(__file__).resolve().parents[3] / "src/skills/browser-login/scripts/input.cjs"


SECRET = "dummy-private-value"


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
global.document={querySelectorAll:s=>s==='*'?[field,button]:s==='#field'?(fault==='duplicate'?[field,field]:[field]):s==='#submit'?(fault==='duplicate-submit'?[button,button]:[button]):[],elementFromPoint:x=>x>=20?button:fault==='covered'?null:fault==='own-label'?{closest:()=>({control:field})}:fault==='other-label'?{closest:()=>({control:{}})}:field};
const requests=[];
const page={url:()=>fault==='elsewhere'?'https://other.example/login':'https://example.com/login',
 evaluateHandle:async()=>({evaluate:async(fn,step)=>{
  requests.push({step});
  if(fn.toString().includes(secret))throw Error('value in source');
  return fn(document,step);
 }})};
(async()=>{
 let result,failed=false;
 try{result=await operate([page],{action:'fill',steps:[{origin:'https://example.com',path:'/login',fields:[{selector:'#field',types:[field.type],value:secret}],submit:'#submit'}]})}catch{failed=true}
 const output={result,failed,clicks,events,authenticated,
  remaining:field.stored.includes(secret),
  secretCalls:requests.filter(r=>JSON.stringify(r.step).includes(secret)).length};
 if(JSON.stringify(output).includes(secret))throw Error('credential output detected');
 console.log(JSON.stringify(output));
})();
"""


def node(*arguments, payload=None):
    executable = shutil.which("node")
    if executable is None:
        pytest.fail("Browser consumer tests need Node on PATH")
    env = state.environment(state.TEMP_ROOT)
    return subprocess.run(
        [executable, *arguments], input=payload, capture_output=True, text=True, timeout=10, env=env
    )


@pytest.mark.parametrize(
    "fault", ["none", "origin", "hidden", "covered", "other-label", "duplicate", "changed"]
)
def test_page_bound_input_refuses_bad_state_without_native_focus(fault):
    result = node("-e", FIXTURE, str(HELPER), fault)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["clicks"] == (1 if fault == "none" else 0)
    assert data["failed"] == (fault == "changed")
    if fault in {"origin", "hidden", "covered", "other-label", "duplicate"}:
        assert data["secretCalls"] == 0 and data["events"] == 0
    if fault == "none":
        assert data["result"] == {"result": "BROWSER_LOGIN_SUBMITTED"}
    assert not data["remaining"], "a filled credential must not stay in the page"


def test_a_floating_label_of_the_exact_field_does_not_count_as_a_cover():
    result = node("-e", FIXTURE, str(HELPER), "own-label")
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["result"] == {"result": "BROWSER_LOGIN_SUBMITTED"} and data["clicks"] == 1


@pytest.mark.parametrize("raw", ["not-json", '{"library":"/nonexistent/dummy-private-value"}'])
def test_protocol_failure_never_prints_input_or_raw_exception(raw):
    result = node(str(HELPER), payload=raw)
    assert result.returncode == 1
    assert SECRET not in result.stdout + result.stderr
    assert json.loads(result.stdout)["result"] == "BROWSER_BLOCKED"


def test_code_challenge_authenticates_and_clears_without_capture():
    result = node("-e", FIXTURE, str(HELPER), "otp")
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["result"] == {"result": "BROWSER_LOGIN_SUBMITTED"}
    assert data["authenticated"] and data["clicks"] == 1 and data["events"] > 0
    assert not data["remaining"] and not data["failed"]
    assert data["secretCalls"] == 3, "only fill, submit and clear carry private arguments"


@pytest.mark.parametrize("fault", ["gated", "disabled"])
def test_submit_must_be_enabled_after_input_not_before_it(fault):
    result = node("-e", FIXTURE, str(HELPER), fault)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["clicks"] == (1 if fault == "gated" else 0)
    assert data["failed"] == (fault == "disabled")
    if fault == "gated":
        assert data["result"] == {"result": "BROWSER_LOGIN_SUBMITTED"}
    assert not data["remaining"], "a refused submit must still clear the filled credential"


def test_preflight_refusal_identifies_that_no_credential_input_occurred():
    result = node("-e", FIXTURE, str(HELPER), "duplicate-submit")
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data.get("result", {}).get("phase") == "preflight"
    assert data["result"]["step"] == 0
    assert data["result"]["reason"] == "SUBMIT_UNAVAILABLE"
    assert data["result"]["credential_input"] is False
    assert data["result"]["submission_attempted"] is False
    assert data["secretCalls"] == data["clicks"] == data["events"] == 0


STEPS = """
const {operate,pageStep}=require(process.argv[1]);
const mode=process.argv[2];
// The clock runs fast, so a step that never becomes ready stops at once.
let clock=0;Date.now=()=>clock+=5000;
const secrets={'#user':'dummy-user','#pass':'dummy-private-value','#code':'123456'};
const flow=[['https://idp.example','/name','#user'],['https://idp.example','/password','#pass'],
 mode==='elsewhere'?['https://evil.example','/code','#code']:['https://idp.example','/code','#code']];
let current=0,clicks=0;
const seen=[];
class Input{
 constructor(selector){this.selector=selector;this.nodeName='INPUT';this.isConnected=true;this.stored='';
  this.type=selector==='#pass'?'password':'text';}
 get value(){return this.stored} set value(v){this.stored=v;seen.push(selector(this))}
 checkVisibility(){return true}
 getBoundingClientRect(){return {x:0,y:0,width:10,height:10}}
 contains(e){return this===e}
 dispatchEvent(){}
}
const selector=input=>location.origin+input.selector;
const button={disabled:false,isConnected:true,checkVisibility:()=>true,
 getBoundingClientRect:()=>({x:20,y:0,width:10,height:10}),contains:e=>e===button,
 click(){clicks++;if(mode==='repeat'&&current===1)return;current=Math.min(current+1,flow.length-1);render()}};
let input;
function render(){
 const [origin,pathname,id]=flow[current];
 global.location={origin,pathname};input=new Input(id);
}
render();
global.HTMLInputElement=Input;
global.document={querySelectorAll:s=>s==='*'?[input,button]:s===input.selector?[input]:s==='#go'?[button]:[],
 elementFromPoint:x=>x<20?input:button};
// A document handle stops working when its page is replaced, as a real execution context does.
let replaced=[];
const page={url:()=>location.origin+location.pathname,evaluateHandle:async()=>{
 const owner=input;
 return {evaluate:async(fn,value)=>{
  if(owner!==input){replaced.push(JSON.stringify(value));throw Error('context destroyed')}
  return fn(document,value);
 }};
}};
const step=(origin,path,id)=>({origin,path,submit:'#go',
 fields:[{selector:id,types:['text','password'],value:secrets[id]}]});
operate([page],{action:'fill',steps:[step('https://idp.example','/name','#user'),
 step('https://idp.example','/password','#pass'),step('https://idp.example','/code','#code')]})
 .then(result=>console.log(JSON.stringify({result,clicks,seen,refusedWrites:replaced.length})));
"""


def test_one_process_walks_the_declared_pages_in_order():
    result = node("-e", STEPS, str(HELPER), "complete")
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["result"] == {"result": "BROWSER_LOGIN_SUBMITTED"}
    assert data["clicks"] == 3
    assert [s for s in data["seen"] if s.endswith(("user", "pass", "code"))][:3] == [
        "https://idp.example#user",
        "https://idp.example#pass",
        "https://idp.example#code",
    ]


@pytest.mark.parametrize(("mode", "clicks"), [("elsewhere", 2), ("repeat", 2)])
def test_a_later_step_stops_before_its_value_leaves_this_process(mode, clicks):
    result = node("-e", STEPS, str(HELPER), mode)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["result"]["result"] == "BROWSER_BLOCKED"
    assert data["result"]["phase"] == "preflight" and data["result"]["credential_input"] is True
    assert data["clicks"] == clicks
    assert not any(s.endswith("#code") for s in data["seen"]), "the code must stay unsent"


def test_a_redirect_receives_nothing_when_a_step_clears_its_fields():
    result = node("-e", STEPS, str(HELPER), "complete")
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["refusedWrites"] == 3, "each clear must stop at the old, gone document"


def test_a_step_on_no_open_page_is_refused_before_any_input():
    script = """
const {operate}=require(process.argv[1]);
const page={url:()=>'https://other.example/',evaluateHandle:async()=>{throw Error('page touched')}};
operate([page],{action:'fill',steps:[{origin:'https://example.com',path:'/',fields:[],submit:'#s'}]})
 .then(r=>console.log(JSON.stringify(r)));
"""
    result = node("-e", script, str(HELPER))
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "result": "BROWSER_BLOCKED",
        "phase": "preflight",
        "step": 0,
        "reason": "WRONG_DESTINATION",
        "credential_input": False,
        "submission_attempted": False,
    }


@pytest.mark.parametrize(("value", "expected"), [("", "EMPTY"), ("kept", "FILLED")])
def test_credential_check_reports_only_whether_a_field_holds_a_value(value, expected):
    script = """
const {operate}=require(process.argv[1]);
const value=process.argv[2];
global.document={querySelectorAll:s=>s==='*'?[]:s==='#user'?[{value}]:[]};
const frame={evaluateHandle:async()=>({evaluate:async(fn,step)=>fn(document,step)})};
const page={url:()=>'https://example.com/login?once=private',frames:()=>[frame]};
operate([page],{action:'filled',selectors:['input[type=password]','#user']})
  .then(r=>console.log(JSON.stringify(r)));
"""
    result = node("-e", script, str(HELPER), value)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "result": expected,
        "pages": 1,
        "address": "https://example.com/login",
    }


@pytest.mark.parametrize(
    ("urls", "expected"),
    [
        ([], {"result": "PAGE_LOST"}),
        (["about:blank"], {"result": "PAGE_LOST"}),
        (["", "about:blank"], {"result": "PAGE_LOST"}),
        (
            ["about:blank", "https://b.example/x"],
            {"result": "EMPTY", "pages": 1, "address": "https://b.example/x"},
        ),
        (
            ["https://b.example/" + "x" * 5000],
            {"result": "EMPTY", "pages": 1, "address": ("https://b.example/" + "x" * 5000)[:1024]},
        ),
    ],
)
def test_a_blank_tab_is_a_lost_tab_and_a_live_page_is_counted(urls, expected):
    script = """
const {operate}=require(process.argv[1]);
global.document={querySelectorAll:()=>[]};
const frame={evaluateHandle:async()=>({evaluate:async(fn,step)=>fn(document,step)})};
const pages=JSON.parse(process.argv[2]).map(url=>({url:()=>url,frames:()=>[frame]}));
operate(pages,{action:'filled',selectors:['input[type=password]']})
  .then(r=>console.log(JSON.stringify(r)));
"""
    result = node("-e", script, str(HELPER), json.dumps(urls))
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == expected


@pytest.mark.parametrize(
    ("origin", "expected"),
    [
        ("https://example.com", {"result": "BROWSER_FILL_READY"}),
        ("https://other.example", {"reason": "WRONG_DESTINATION", "credential_input": False}),
    ],
)
def test_check_inspects_the_page_and_writes_nothing(origin, expected):
    script = """
const {operate}=require(process.argv[1]);
const events=[];
class Input{
 constructor(){this.nodeName='INPUT';this.type='password';this.isConnected=true;}
 get value(){return ''} set value(v){events.push('write')}
 checkVisibility(){return true}
 getBoundingClientRect(){return {x:0,y:0,width:10,height:10}}
 contains(e){return this===e}
 dispatchEvent(){events.push('event')}
}
const field=new Input();
const button={disabled:false,isConnected:true,checkVisibility:()=>true,
 getBoundingClientRect:()=>({x:20,y:0,width:10,height:10}),contains:e=>e===button,
 click(){events.push('click')}};
global.HTMLInputElement=Input;
global.location={origin:'https://example.com',pathname:'/login'};
global.document={querySelectorAll:s=>s==='*'?[field,button]:s==='#p'?[field]:s==='#s'?[button]:[],
 elementFromPoint:x=>x>=20?button:field};
const page={url:()=>process.argv[2]+'/login',
 evaluateHandle:async()=>({evaluate:async(fn,step)=>fn(document,step)})};
operate([page],{action:'check',steps:[{origin:process.argv[2],path:'/login',submit:'#s',
 fields:[{selector:'#p',types:['password'],value:''}]}]})
 .then(result=>console.log(JSON.stringify({result,events})));
"""
    result = node("-e", script, str(HELPER), origin)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["events"] == [] and expected.items() <= data["result"].items()


FRAMES = """
const {operate,pageStep}=require(process.argv[1]);
const frame=value=>({evaluateHandle:async()=>{
 if(value===null)throw Error('unreadable frame');
 return {evaluate:async(fn,step)=>{
  global.document={querySelectorAll:s=>s==='*'?[]:s==='input[type=password]'?[{value}]:[]};
  return fn(document,step);
 }};
}});
const frames=JSON.parse(process.argv[2]).map(frame);
operate([{url:()=>'https://example.com/',frames:()=>frames}],{action:'filled',selectors:['input[type=password]']})
 .then(r=>console.log(JSON.stringify(r)),()=>console.log(JSON.stringify({rejected:true})));
"""


@pytest.mark.parametrize(
    ("frames", "expected"),
    [
        (["", ""], {"result": "EMPTY", "pages": 1, "address": "https://example.com/"}),
        (["", "kept"], {"result": "FILLED", "pages": 1, "address": "https://example.com/"}),
        (["", None], {"rejected": True}),
    ],
)
def test_the_guard_reads_every_frame_and_an_unreadable_frame_is_not_empty(frames, expected):
    result = node("-e", FRAMES, str(HELPER), json.dumps(frames))
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == expected
