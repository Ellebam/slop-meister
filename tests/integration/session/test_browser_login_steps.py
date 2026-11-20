"""A username a later page still needs stays until the fill ends, then every field is empty."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from slopmeister.session import browser_state as state

HELPER = Path(__file__).resolve().parents[3] / "src/skills/browser-login/scripts/input.cjs"
SECRET = "dummy-private-value"

# Like Apple's sign-in, the page keeps the username field on its password page and turns its
# button on only while both fields hold a value.
STEPS = """
const {operate}=require(process.argv[1]);
const fault=process.argv[2];
const NAME='dummy-user@example.com',SECRET='dummy-private-value';
let clicks=0,clock=0,phase='name',submitted=false;
// Each deadline read advances the clock, so a wait ends after a few polls.
Date.now=()=>clock+=1000;
class Input{
 matches(s){return s===':disabled'&&!!this.disabled}
 constructor(id,type,x){this.id=id;this.type=type;this.x=x;this.nodeName='INPUT';this.isConnected=true;this.stored='';}
 get value(){return this.stored} set value(v){this.stored=v}
 checkVisibility(){return this.type!=='password'||fault!=='hidden'}
 getBoundingClientRect(){return {x:this.x,y:0,width:10,height:10}}
 contains(e){return this===e}
 dispatchEvent(){}
}
global.HTMLInputElement=Input;
const name=new Input('#name','email',0),pass=new Input('#pass','password',40);
const button={matches(s){return s===':disabled'&&!!this.disabled},
 isConnected:true,checkVisibility:()=>true,contains:e=>e===button,
 getBoundingClientRect:()=>({x:20,y:0,width:10,height:10}),
 get disabled(){return !name.value||phase==='pass'&&(fault==='refuses'||!pass.value)},
 click(){clicks++;if(phase==='name')phase='pass';
  else submitted=name.value===NAME&&pass.value===SECRET}};
global.location={origin:'https://example.com',pathname:'/login'};
const nodes={'*':[name,pass,button],'#name':[name],'#pass':[pass],'#go':[button]};
global.document={querySelectorAll:s=>nodes[s]||[],
 elementFromPoint:x=>x>=40?pass:x>=20?button:name};
const page={url:()=>'https://example.com/login',
 evaluateHandle:async()=>({evaluate:async(fn,step)=>fn(document,step)})};
const step=(selector,type,value)=>({origin:'https://example.com',path:'/login',submit:'#go',
 fields:[{selector,types:type==='name'?['text','email']:['password'],value}]});
operate([page],{action:'fill',steps:[step('#name','name',NAME),step('#pass','pass',SECRET)]})
 .then(result=>result,()=>'THROWN')
 .then(result=>{const out=JSON.stringify({result,clicks,submitted,
  remaining:[name.stored,pass.stored].filter(Boolean).length});
  if(out.includes(SECRET)||out.includes(NAME))throw Error('value in output');console.log(out);});
"""


def run(fault):
    executable = shutil.which("node")
    if executable is None:
        pytest.fail("Browser consumer tests need Node on PATH")
    env = state.environment(state.TEMP_ROOT)
    done = subprocess.run(
        [executable, "-e", STEPS, str(HELPER), fault],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_a_username_the_password_page_still_needs_stays_until_the_last_click():
    data = run("none")
    assert data["result"] == {"result": "BROWSER_LOGIN_SUBMITTED"}
    assert data["clicks"] == 2 and data["submitted"]
    assert data["remaining"] == 0, "every filled field must be empty after success"


@pytest.mark.parametrize(
    ("fault", "result"),
    [
        (
            "refuses",
            {
                "result": "BROWSER_BLOCKED",
                "phase": "input",
                "step": 1,
                "reason": "SUBMIT_UNAVAILABLE: do not retry submission",
            },
        ),
        (
            "hidden",
            {
                "result": "BROWSER_BLOCKED",
                "phase": "preflight",
                "step": 1,
                "reason": "FIELD_UNAVAILABLE",
                "credential_input": True,
                "submission_attempted": True,
            },
        ),
    ],
)
def test_a_later_step_that_fails_still_empties_the_kept_username(fault, result):
    data = run(fault)
    assert data["result"] == result
    assert data["clicks"] == 1 and not data["submitted"]
    assert data["remaining"] == 0, "every filled field must be empty after failure"


# A stand-in for the browser library: the password page never answers, so the hard deadline ends
# the helper while the username it kept is still filled.
HANGS = """
const fs=require('node:fs');
let phase='name';
class Input{
 matches(s){return s===':disabled'&&!!this.disabled}
 constructor(id,type,x){this.id=id;this.type=type;this.x=x;this.nodeName='INPUT';this.isConnected=true;this.stored='';}
 get value(){return this.stored} set value(v){this.stored=v}
 checkVisibility(){return true}
 getBoundingClientRect(){return {x:this.x,y:0,width:10,height:10}}
 contains(e){return this===e}
 dispatchEvent(){}
}
global.HTMLInputElement=Input;
const name=new Input('#name','email',0),pass=new Input('#pass','password',40);
const button={matches(s){return s===':disabled'&&!!this.disabled},
 disabled:false,isConnected:true,checkVisibility:()=>true,contains:e=>e===button,
 getBoundingClientRect:()=>({x:20,y:0,width:10,height:10}),click(){phase='pass'}};
global.location={origin:'https://example.com',pathname:'/login'};
const nodes={'*':[name,pass,button],'#name':[name],'#pass':[pass],'#go':[button]};
global.document={querySelectorAll:s=>nodes[s]||[],elementFromPoint:x=>x>=40?pass:x>=20?button:name};
const cdp={send:async()=>({targetInfo:{targetId:'T1'}}),detach:async()=>{}};
const page={context:()=>({newCDPSession:async()=>cdp}),url:()=>'https://example.com/login',evaluateHandle:async()=>({evaluate:async(fn,step)=>
 phase==='pass'&&step.mode!=='clear'?new Promise(()=>{}):fn(document,step)})};
process.on('exit',()=>fs.writeFileSync(__dirname+'/out.json',JSON.stringify({phase,nameLeft:!!name.stored})));
module.exports={chromium:{connect:async()=>({contexts:()=>[{pages:()=>[page]}]})}};
"""

# The real deadline is 55 seconds, so the test shortens only that one timer.
SHORT = """
const later=global.setTimeout;
global.setTimeout=(fn,ms,...rest)=>later(fn,ms===55000?3000:ms,...rest);
"""


def test_the_hard_deadline_still_empties_a_kept_username(tmp_path):
    executable = shutil.which("node")
    if executable is None:
        pytest.fail("Browser consumer tests need Node on PATH")
    (tmp_path / "library.js").write_text(HANGS)
    (tmp_path / "short.js").write_text(SHORT)
    step = {"origin": "https://example.com", "path": "/login", "submit": "#go"}
    request = {
        "action": "fill",
        "own": "T1",
        "socket": "unused",
        "library": str(tmp_path / "library.js"),
        "steps": [
            {**step, "fields": [{"selector": "#name", "types": ["text", "email"], "value": "u"}]},
            {**step, "fields": [{"selector": "#pass", "types": ["password"], "value": SECRET}]},
        ],
    }
    done = subprocess.run(
        [executable, "--require", str(tmp_path / "short.js"), str(HELPER)],
        input=json.dumps(request),
        capture_output=True,
        text=True,
        timeout=30,
        env=state.environment(state.TEMP_ROOT),
    )
    assert done.returncode == 1 and "BROWSER_TIMEOUT" in done.stdout, done.stdout + done.stderr
    assert SECRET not in done.stdout + done.stderr
    after = json.loads((tmp_path / "out.json").read_text())
    assert after["phase"] == "pass", "the username step must have been submitted"
    assert not after["nameLeft"], "the deadline must still empty the kept username"
