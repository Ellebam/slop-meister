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
const fault=process.argv[2];const secret='dummy-private-value';let clicks=0,events=0;
class Input {
 constructor(id,type){this.id=id;this.type=type;this.nodeName='INPUT';this.isConnected=true;this.stored='';}
 get value(){return this.stored} set value(v){this.stored=v}
 checkVisibility(){return fault!=='hidden'}
 getBoundingClientRect(){return {x:0,y:0,width:10,height:10}}
 contains(e){return this===e}
 focus(){throw Error('native focus must not run')}
 dispatchEvent(){events++;if(fault==='changed')this.stored+='changed';if(fault==='gated')button.disabled=false;}
}
const field=new Input('field','password');
const button={disabled:['gated','disabled'].includes(fault),isConnected:true,
 checkVisibility:()=>true,
 getBoundingClientRect:()=>({x:20,y:0,width:10,height:10}),contains:e=>e===button,
 click(){clicks++}};
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
 try{result=await operate(client,{action:'fill',step:{origin:'https://example.com',path:'/login',fields:[{selector:'#field',types:['password'],value:secret}],submit:'#submit'}})}catch{failed=true}
 console.log(JSON.stringify({result,failed,clicks,events,secretCalls:requests.filter(r=>JSON.stringify(r.params).includes(secret)).length,methods:requests.map(r=>r.method)}));
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


def node(*arguments, payload=None):
    executable = shutil.which("node")
    env = runtime.environment(runtime.TEMP_ROOT)
    if executable is None:
        try:
            _, bundled = runtime.binaries()
        except ValueError:
            pytest.fail("Browser consumer tests need Node on PATH or the installed Orca runtime")
        executable = str(bundled)
        env["ELECTRON_RUN_AS_NODE"] = "1"
    return subprocess.run(
        [executable, *arguments], input=payload, capture_output=True, text=True, timeout=10, env=env
    )


@pytest.mark.parametrize("fault", ["none", "origin", "hidden", "covered", "duplicate", "changed"])
def test_page_bound_input_refuses_bad_state_without_native_focus(fault):
    result = node("-e", FIXTURE, str(HELPER), fault)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["clicks"] == (1 if fault == "none" else 0)
    assert data["failed"] == (fault == "changed")
    assert not any(method.startswith(("Input.", "DOM.")) for method in data["methods"])
    if fault in {"origin", "hidden", "covered", "duplicate"}:
        assert data["secretCalls"] == 0 and data["events"] == 0
    if fault == "none":
        assert data["result"] == {"result": "BROWSER_LOGIN_SUBMITTED"}
        assert data["events"] == 2


@pytest.mark.parametrize("raw", ["not-json", '{"endpoint":"file:///dummy-private-value"}'])
def test_protocol_failure_never_prints_input_or_raw_exception(raw):
    result = node(str(HELPER), payload=raw)
    assert result.returncode == 1
    assert SECRET not in result.stdout + result.stderr
    assert json.loads(result.stdout)["result"] == "BROWSER_BLOCKED"


@pytest.mark.parametrize("fault", ["gated", "disabled"])
def test_submit_must_be_enabled_after_input_not_before_it(fault):
    result = node("-e", FIXTURE, str(HELPER), fault)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["events"] == 2
    assert data["clicks"] == (1 if fault == "gated" else 0)
    assert data["failed"] == (fault == "disabled")
    if fault == "gated":
        assert data["result"] == {"result": "BROWSER_LOGIN_SUBMITTED"}


@pytest.mark.parametrize("value", ["", "op://example/item/otp", "otpauth://seed", "ABCDEF"])
def test_unresolved_or_seed_otp_is_refused(monkeypatch, value):
    monkeypatch.setenv("BROWSER_LOGIN_OTP", value)
    with pytest.raises(ValueError, match="BROWSER_(CREDENTIAL|OTP)"):
        browser.fields([["#field", "BROWSER_LOGIN_OTP"]])


def test_generated_otp_keeps_leading_zeroes(monkeypatch):
    monkeypatch.setenv("BROWSER_LOGIN_OTP", "001234")
    assert browser.fields([["#otp", "BROWSER_LOGIN_OTP"]]) == [["#otp", "001234"]]


def test_unrelated_environment_is_refused():
    with pytest.raises(ValueError, match="FIELD_REFUSED"):
        browser.fields([["#password", "OP_SERVICE_ACCOUNT_TOKEN"]])


def test_values_use_private_stdin_not_child_environment_or_arguments(tmp_path, monkeypatch):
    monkeypatch.setenv("BROWSER_LOGIN_PASSWORD", SECRET)
    monkeypatch.setenv("NODE_OPTIONS", SECRET)
    monkeypatch.setenv("OP_SERVICE_ACCOUNT_TOKEN", SECRET)

    def execute(argv, **options):
        assert SECRET not in json.dumps(argv) + json.dumps(options["env"])
        assert json.loads(options["input"])["value"] == SECRET
        assert options["env"]["ELECTRON_RUN_AS_NODE"] == "1"
        return subprocess.CompletedProcess(argv, 0, '{"result":"BROWSER_LOGIN_SUBMITTED"}')

    monkeypatch.setattr(state.subprocess, "run", execute)
    assert runtime.execute(tmp_path, ["bundled-node", "input.cjs"], {"value": SECRET}) == {
        "result": "BROWSER_LOGIN_SUBMITTED"
    }


def test_preflight_refusal_identifies_that_no_credential_input_occurred():
    result = node("-e", FIXTURE, str(HELPER), "duplicate-submit")
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data.get("result", {}).get("phase") == "preflight"
    assert data["result"]["reason"] == "SUBMIT_UNAVAILABLE"
    assert data["result"]["credential_input"] is False
    assert data["result"]["submission_attempted"] is False
    assert data["secretCalls"] == data["clicks"] == data["events"] == 0


def test_entry_preserves_explicit_preflight_refusal(tmp_path, monkeypatch, capsys):
    refusal = {
        "result": "BROWSER_BLOCKED",
        "phase": "preflight",
        "reason": "SUBMIT_UNAVAILABLE",
        "credential_input": False,
        "submission_attempted": False,
    }
    monkeypatch.setattr(runtime, "owned", lambda _: tmp_path)
    monkeypatch.setattr(runtime, "request", lambda *_: refusal)
    monkeypatch.setenv("BROWSER_LOGIN_USERNAME", SECRET)
    code = browser.main(
        [
            "fill",
            str(tmp_path),
            "--url",
            "https://example.com/",
            "--field",
            "#username",
            "BROWSER_LOGIN_USERNAME",
            "--submit",
            "#continue",
        ]
    )
    output = capsys.readouterr()
    assert code == 1 and json.loads(output.out) == refusal
    assert SECRET not in output.out + output.err


def test_chrome_window_has_background_bounds_before_navigation():
    script = """
const {operate}=require(process.argv[1]);
let calls=[];
const client={send:async(method,params)=>{
  calls.push({method,params});return {targetId:'owned',windowId:42}
}};
operate(client,{action:'create'}).then(()=>console.log(JSON.stringify(calls)));
"""
    result = node("-e", script, str(HELPER))
    assert result.returncode == 0, result.stderr
    calls = json.loads(result.stdout)
    assert calls[0]["method"] == "Target.createTarget"
    options = calls[0]["params"]
    assert options["newWindow"] is True and options["background"] is True
    bounds = next(
        call["params"]["bounds"] for call in calls if call["method"] == "Browser.setWindowBounds"
    )
    assert bounds["width"] > 0 and bounds["height"] > 0


@pytest.mark.parametrize("fault", ["ordinary", "large-output", "oversize-frame", "unicode-frame"])
def test_snapshot_accepts_large_ax_reply_but_bounds_frames_and_output(tmp_path, fault):
    preload = tmp_path / "socket.cjs"
    preload.write_text(SOCKET_FIXTURE)
    result = node(
        "--require",
        str(preload),
        str(HELPER),
        fault,
        payload=json.dumps(
            {"endpoint": "ws://127.0.0.1:12345/devtools/page/test", "action": "snapshot"}
        ),
    )
    assert len(result.stdout) < 1024
    data = json.loads(result.stdout)
    if fault == "ordinary":
        assert result.returncode == 0 and data == {"snapshot": "button: Login"}
    else:
        assert result.returncode == 1 and data["result"] == "BROWSER_BLOCKED"
