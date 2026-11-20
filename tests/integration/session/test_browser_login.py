"""Credential input stays bound to the page and never reaches native keyboard focus."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from slopmeister.session import browser_login as browser
from slopmeister.session import browser_runtime as runtime
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
 matches(s){return s===':disabled'&&!!this.disabled}
 constructor(id,type){this.id=id;this.type=type;this.nodeName='INPUT';this.isConnected=true;this.stored='';}
 get value(){return this.stored} set value(v){this.stored=v}
 checkVisibility(){return fault!=='hidden'}
 getBoundingClientRect(){return {x:0,y:0,width:10,height:10}}
 contains(e){return this===e}
 focus(){throw Error('native focus must not run')}
 dispatchEvent(){events++;if(fault==='changed')this.stored+='changed';if(['gated','passthrough'].includes(fault))button.disabled=false;
  // Apple enables its button from a page timer, which Chrome delays in a tab it does not draw.
  if(fault==='later')setTimeout(()=>{button.disabled=false},1200);}
}
const field=new Input('field',fault==='otp'?'tel':'password');
const button={matches(s){return s===':disabled'&&!!this.disabled},
 disabled:['gated','disabled','passthrough','later'].includes(fault),isConnected:true,
 checkVisibility:()=>true,
 getBoundingClientRect:()=>({x:20,y:0,width:10,height:10}),contains:e=>e===button,
 click(){clicks++;authenticated=field.value===secret}};
global.HTMLInputElement=Input;
global.location={origin:fault==='origin'?'https://wrong.example':'https://example.com',pathname:'/login'};
// A disabled button often ignores the pointer, so the point lands on what lies behind it.
global.document={querySelectorAll:s=>s==='*'?[field,button]:s==='#field'?(fault==='duplicate'?[field,field]:[field]):s==='#submit'?(fault==='duplicate-submit'?[button,button]:[button]):[],
 elementFromPoint:x=>x>=20?(fault==='covered-submit'||fault==='passthrough'&&button.disabled?{}:button):fault==='covered'?null:fault==='own-label'?{closest:()=>({control:field})}:fault==='other-label'?{closest:()=>({control:{}})}:field};
const requests=[];
const page={url:()=>fault==='elsewhere'?'https://other.example/login':'https://example.com/login',
 evaluateHandle:async()=>({evaluate:async(fn,step)=>{
  requests.push({step});
  if(fn.toString().includes(secret))throw Error('value in source');
  // A driver error can quote what it was sent, so its text must never reach the result.
  if(fault==='raises'&&step.mode==='fill')throw Error('evaluate failed with '+secret);
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
    assert not data["failed"]
    if fault in {"origin", "hidden", "covered", "other-label", "duplicate"}:
        assert data["secretCalls"] == 0 and data["events"] == 0
    if fault == "none":
        assert data["result"] == {"result": "BROWSER_LOGIN_SUBMITTED"}
    if fault == "changed":
        assert data["result"] == inner_failure("FIELD_CHANGED")
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


def inner_failure(code, step=0):
    return {
        "result": "BROWSER_BLOCKED",
        "phase": "input",
        "step": step,
        "reason": f"{code}: do not retry submission",
    }


@pytest.mark.parametrize("fault", ["gated", "passthrough", "later", "disabled"])
def test_submit_must_be_enabled_after_input_not_before_it(fault):
    result = node("-e", FIXTURE, str(HELPER), fault)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["clicks"] == (0 if fault == "disabled" else 1)
    assert not data["failed"]
    if fault == "disabled":
        assert data["result"] == inner_failure("SUBMIT_UNAVAILABLE")
    else:
        assert data["result"] == {"result": "BROWSER_LOGIN_SUBMITTED"}
    assert not data["remaining"], "a refused submit must still clear the filled credential"


def test_a_driver_error_after_input_is_named_without_its_text():
    result = node("-e", FIXTURE, str(HELPER), "raises")
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["result"] == inner_failure("PAGE_OPERATION_FAILED")
    assert data["clicks"] == 0 and not data["remaining"]


@pytest.mark.parametrize("fault", ["duplicate-submit", "covered-submit"])
def test_preflight_refusal_identifies_that_no_credential_input_occurred(fault):
    result = node("-e", FIXTURE, str(HELPER), fault)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data.get("result", {}).get("phase") == "preflight"
    assert data["result"]["step"] == 0
    assert data["result"]["reason"] == "SUBMIT_UNAVAILABLE"
    assert data["result"]["credential_input"] is False
    assert data["result"]["submission_attempted"] is False
    assert data["secretCalls"] == data["clicks"] == data["events"] == 0


STEPS = """
const {operate}=require(process.argv[1]);
const mode=process.argv[2];
const request=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
// The clock runs fast, so a step that never becomes ready stops at once.
let clock=0;Date.now=()=>clock+=5000;
const flow=[['https://idp.example','/name','#user'],['https://idp.example','/password','#pass'],
 [mode==='elsewhere'?'https://other.example':'https://idp.example','/code','#code'],
 ['https://idp.example','/done','#done']];
let current=0,clicks=0;
let codeInput,codeFilled=false;
const seen=[];
class Input{
 matches(s){return s===':disabled'&&!!this.disabled}
 constructor(selector){this.selector=selector;this.nodeName='INPUT';this.isConnected=true;this.stored='';
  this.type=['#pass','#code'].includes(selector)?'password':'text';}
 get value(){return this.stored}
 set value(v){
  this.stored=v;seen.push(location.origin+this.selector);
  if(this===codeInput&&v===request.steps[2].fields[0].value)codeFilled=true;
 }
 checkVisibility(){return true}
 getBoundingClientRect(){return {x:0,y:0,width:10,height:10}}
 contains(e){return this===e}
 dispatchEvent(){}
}
const button={matches(s){return s===':disabled'&&!!this.disabled},
 get disabled(){return mode==='disabled'&&current===2},
 isConnected:true,checkVisibility:()=>true,
 getBoundingClientRect:()=>({x:20,y:0,width:10,height:10}),contains:e=>e===button,
 click(){
  if(input.value!==request.steps[current].fields[0].value)throw Error('unexpected credential');
  clicks++;
  if((mode==='repeat'&&current===1)||(mode!=='redirect'&&current===2))return;
  current++;render();
 }};
let input;
function render(){
 const [origin,pathname,id]=flow[current];
 global.location={origin,pathname};input=new Input(id);
 if(id==='#code')codeInput=input;
}
render();
global.HTMLInputElement=Input;
global.document={querySelectorAll:s=>s==='*'?[input,button]:s===input.selector?[input]:s==='#go'?[button]:[],
 elementFromPoint:x=>x<20?input:button};
// A document handle stops working when its page is replaced, as a real execution context does.
let refusedWrites=0;
const page={url:()=>location.origin+location.pathname,evaluateHandle:async()=>{
 const owner=input;
 return {evaluate:async(fn,value)=>{
  if(owner!==input){refusedWrites++;throw Error('context destroyed')}
  return fn(document,value);
 }};
}};
operate([page],request).then(result=>console.log(JSON.stringify({
 result,clicks,seen,refusedWrites,codeFilled,codeEmpty:codeInput?.value==='',
})));
"""


@pytest.fixture
def ordered_fill(tmp_path, monkeypatch, capsys):
    state.save(tmp_path, {"worktree": str(tmp_path)})
    monkeypatch.setattr(runtime, "owned", lambda _: tmp_path)
    monkeypatch.setenv("BROWSER_LOGIN_USERNAME", "dummy-user")
    monkeypatch.setenv("BROWSER_LOGIN_PASSWORD", SECRET)
    steps = [
        ("/name", "#user", "BROWSER_LOGIN_USERNAME"),
        ("/password", "#pass", "BROWSER_LOGIN_PASSWORD"),
        ("/code", "#code", "BROWSER_LOGIN_OTP"),
    ]
    args = ["fill", str(tmp_path)]
    for path, selector, variable in steps:
        args.extend(
            [
                "--step",
                json.dumps(
                    {
                        "url": "https://idp.example" + path,
                        "fields": [[selector, variable]],
                        "submit": "#go",
                    }
                ),
            ]
        )

    def run(mode, code="001234"):
        observed = {}
        monkeypatch.setenv("BROWSER_LOGIN_OTP", code)

        def request(_root, payload):
            assert not observed, "one fill must send one request"
            assert payload["steps"][-1]["fields"][0]["value"] == code
            done = node("-e", STEPS, str(HELPER), mode, payload=json.dumps(payload))
            assert code not in done.stdout + done.stderr and SECRET not in done.stdout + done.stderr
            assert done.returncode == 0, done.stderr
            observed.update(json.loads(done.stdout))
            return observed["result"]

        monkeypatch.setattr(runtime, "request", request)
        status = browser.main(args)
        output = capsys.readouterr()
        assert code not in output.out + output.err and SECRET not in output.out + output.err
        result = json.loads(output.out)
        assert status == int(result["result"] == "BROWSER_BLOCKED")
        return observed | {"result": result}

    return run


@pytest.mark.parametrize("code", ["001234", "00123456"], ids=["six-digits", "eight-digits"])
def test_password_type_code_submits_in_order_and_clears(ordered_fill, code):
    data = ordered_fill("complete", code)
    assert data["result"] == {"result": "BROWSER_LOGIN_SUBMITTED"}
    assert data["clicks"] == 3
    assert data["codeFilled"] and data["codeEmpty"], "the submitted code field must be empty"
    assert [s for s in data["seen"] if s.endswith(("user", "pass", "code"))][:3] == [
        "https://idp.example#user",
        "https://idp.example#pass",
        "https://idp.example#code",
    ]


def test_password_type_code_clears_after_a_refused_submit(ordered_fill):
    data = ordered_fill("disabled")
    assert data["result"] == inner_failure("SUBMIT_UNAVAILABLE", step=2)
    assert data["clicks"] == 2
    assert data["codeFilled"] and data["codeEmpty"], "the refused code must clear after input"


@pytest.mark.parametrize("code", ["1234567", "１２３４５６"], ids=["seven-digits", "non-ascii"])
def test_password_type_code_refuses_invalid_input_before_request(ordered_fill, code):
    assert ordered_fill("complete", code) == {
        "result": {
            "result": "BROWSER_BLOCKED",
            "reason": "BROWSER_OTP_REFUSED: require a generated numeric code, never a seed",
        },
    }


@pytest.mark.parametrize("mode", ["elsewhere", "repeat"])
def test_a_later_step_stops_before_its_value_leaves_this_process(ordered_fill, mode):
    data = ordered_fill(mode)
    assert data["result"]["result"] == "BROWSER_BLOCKED"
    assert data["result"]["phase"] == "preflight" and data["result"]["credential_input"] is True
    assert data["clicks"] == 2
    assert not any(s.endswith("#code") for s in data["seen"]), "the code must stay unsent"


def test_a_redirect_receives_nothing_when_a_step_clears_its_fields(ordered_fill):
    data = ordered_fill("redirect")
    assert data["result"] == {"result": "BROWSER_LOGIN_SUBMITTED"} and data["codeFilled"]
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
