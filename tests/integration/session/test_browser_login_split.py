"""A split code is entered share by share, submitted and emptied on every path."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from slopmeister.session import browser_login as browser
from slopmeister.session import browser_state as state

HELPER = Path(__file__).resolve().parents[3] / "src/skills/browser-login/scripts/input.cjs"
CODE = "001234"

# Like a split code widget, a box spreads a longer entry over the boxes after it.
PAGE = """
const {operate}=require(process.argv[1]);
const fault=process.argv[2];
const request=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
let clock=0;Date.now=()=>clock+=1000;
let clicks=0,events=0,atClick='';
class Input{
 matches(s){return s===':disabled'&&!!(this.disabled||this.fieldset)}
 constructor(i,size){this.id='#d'+i;this.i=i;this.size=size;this.type='text';this.nodeName='INPUT';
  this.isConnected=true;this.stored='';}
 get value(){return this.stored} set value(v){this.stored=v}
 checkVisibility(){return true}
 getBoundingClientRect(){return {x:this.i*20,y:0,width:10,height:10}}
 contains(e){return this===e}
 dispatchEvent(event){
  events++;
  if(event.type!=='input'||this.stored.length<=this.size)return;
  let rest=this.stored;
  for(const box of boxes.slice(this.i)){
   box.stored=rest.slice(0,box.size);rest=rest.slice(box.size);
  }
 }
}
const sizes=JSON.parse(process.argv[3]);
const boxes=sizes.map((size,i)=>new Input(i,size));
const button={matches(s){return s===':disabled'&&!!(this.disabled||this.fieldset)},
 disabled:fault==='disabled',isConnected:true,checkVisibility:()=>true,
 getBoundingClientRect:()=>({x:500,y:0,width:10,height:10}),contains:e=>e===button,
 click(){clicks++;atClick=boxes.map(b=>b.stored).join('')}};
global.HTMLInputElement=Input;
global.location={origin:'https://example.com',pathname:'/mfa'};
const byId=Object.fromEntries(boxes.map(b=>[b.id,[b]]));
// A mistyped list can name the first box twice under two selectors.
if(fault==='twice')byId['#d1']=[boxes[0]];
// A disabled fieldset disables the controls inside it while their own attribute stays unset.
if(fault==='fieldset-box')boxes[1].fieldset=true;
if(fault==='fieldset-submit')button.fieldset=true;
global.document={querySelectorAll:s=>s==='*'?[...boxes,button]:s==='#go'?[button]:byId[s]||[],
 elementFromPoint:x=>x>=500?button:boxes[Math.floor(x/20)]};
const page={url:()=>'https://example.com/mfa',evaluateHandle:async()=>({evaluate:async(fn,step)=>fn(document,step)})};
operate([page],request).then(result=>{
 const out=JSON.stringify({result,clicks,events,submitted:atClick===request.code,
  left:boxes.filter(b=>b.stored).length});
 if(out.includes(request.code))throw Error('code in output');
 console.log(out);
});
"""


def node():
    executable = shutil.which("node")
    if executable is None:
        pytest.fail("Browser consumer tests need Node on PATH")
    return executable


def steps(monkeypatch, selectors, code=CODE):
    monkeypatch.setenv("BROWSER_LOGIN_OTP", code)
    raw = {
        "url": "https://example.com/mfa",
        "fields": [[selectors, "BROWSER_LOGIN_OTP"]],
        "submit": "#go",
    }
    return [browser.step(json.dumps(raw))]


def run(monkeypatch, sizes, selectors, fault="none"):
    payload = {"action": "fill", "steps": steps(monkeypatch, selectors), "code": CODE}
    done = subprocess.run(
        [node(), "-e", PAGE, str(HELPER), fault, json.dumps(sizes)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
        env=state.environment(state.TEMP_ROOT),
    )
    assert done.returncode == 0, done.stderr
    assert CODE not in done.stdout + done.stderr
    return json.loads(done.stdout)


@pytest.mark.parametrize(
    "sizes", [[1] * 6, [3, 3], [2, 2, 2]], ids=["six-digits", "two-threes", "three-twos"]
)
def test_a_split_code_is_entered_per_box_submitted_and_emptied(monkeypatch, sizes):
    selectors = [f"#d{i}" for i in range(len(sizes))]
    data = run(monkeypatch, sizes, selectors)
    assert data["result"] == {"result": "BROWSER_LOGIN_SUBMITTED"}
    assert data["clicks"] == 1 and data["submitted"], "every box must hold its share at the click"
    assert data["left"] == 0, "every box must be empty afterwards"


def test_one_selector_on_a_split_page_is_refused_without_a_submit(monkeypatch):
    data = run(monkeypatch, [1] * 6, "#d0")
    assert data["result"]["reason"] == "FIELD_CHANGED: do not retry submission"
    assert data["clicks"] == 0 and not data["submitted"]


def test_a_refused_submit_still_empties_every_box(monkeypatch):
    data = run(monkeypatch, [1] * 6, [f"#d{i}" for i in range(6)], "disabled")
    assert data["result"]["reason"] == "SUBMIT_UNAVAILABLE: do not retry submission"
    assert data["result"]["phase"] == "input" and data["clicks"] == 0
    assert data["left"] == 0, "a refused submit must still empty every box"


@pytest.mark.parametrize(
    ("fault", "phase", "reason"),
    [
        ("fieldset-box", "preflight", "FIELD_UNAVAILABLE"),
        ("fieldset-submit", "input", "SUBMIT_UNAVAILABLE: do not retry submission"),
    ],
)
def test_a_control_in_a_disabled_fieldset_gets_no_value_and_no_click(
    monkeypatch, fault, phase, reason
):
    data = run(monkeypatch, [3, 3], ["#d0", "#d1"], fault)
    assert data["result"]["phase"] == phase and data["result"]["reason"] == reason
    assert data["clicks"] == data["left"] == 0, "nothing is submitted and every box is empty"


def test_two_selectors_for_one_box_are_refused_before_any_input(monkeypatch):
    selectors = ["#d0", "#d1"]
    data = run(monkeypatch, [3, 3], selectors, "twice")
    assert data["result"]["phase"] == "preflight"
    assert data["result"]["reason"] == "FIELD_UNAVAILABLE"
    assert data["events"] == data["clicks"] == data["left"] == 0


# A stand-in for the browser library whose submit check never answers, so the hard deadline ends
# the helper while the code boxes are filled.
HANGS = """
const fs=require('node:fs');
class Input{
 matches(s){return s===':disabled'&&!!this.disabled}
 constructor(i){this.i=i;this.type='text';this.nodeName='INPUT';this.isConnected=true;this.stored='';}
 get value(){return this.stored} set value(v){if(v)this.filled=true;this.stored=v}
 checkVisibility(){return true}
 getBoundingClientRect(){return {x:this.i*20,y:0,width:10,height:10}}
 contains(e){return this===e}
 dispatchEvent(){}
}
global.HTMLInputElement=Input;
const boxes=[new Input(0),new Input(1)];
const button={matches(s){return s===':disabled'&&!!this.disabled},
 disabled:false,isConnected:true,checkVisibility:()=>true,contains:e=>e===button,
 getBoundingClientRect:()=>({x:500,y:0,width:10,height:10}),click(){}};
global.location={origin:'https://example.com',pathname:'/mfa'};
const nodes={'*':[...boxes,button],'#d0':[boxes[0]],'#d1':[boxes[1]],'#go':[button]};
global.document={querySelectorAll:s=>nodes[s]||[],elementFromPoint:x=>x>=500?button:boxes[Math.floor(x/20)]};
const cdp={send:async()=>({targetInfo:{targetId:'T1'}}),detach:async()=>{}};
const page={context:()=>({newCDPSession:async()=>cdp}),url:()=>'https://example.com/mfa',
 evaluateHandle:async()=>({evaluate:async(fn,step)=>
  step.mode==='submit'?new Promise(()=>{}):fn(document,step)})};
process.on('exit',()=>fs.writeFileSync(__dirname+'/out.json',JSON.stringify({
 filled:boxes.every(b=>b.filled),left:boxes.filter(b=>b.stored).length})));
module.exports={chromium:{connect:async()=>({contexts:()=>[{pages:()=>[page]}]})}};
"""

# The real deadline is 55 seconds, so the test shortens only that one timer.
SHORT = """
const later=global.setTimeout;
global.setTimeout=(fn,ms,...rest)=>later(fn,ms===55000?3000:ms,...rest);
"""


def test_the_hard_deadline_after_input_empties_every_box(tmp_path, monkeypatch):
    (tmp_path / "library.js").write_text(HANGS)
    (tmp_path / "short.js").write_text(SHORT)
    request = {
        "action": "fill",
        "own": "T1",
        "socket": "unused",
        "library": str(tmp_path / "library.js"),
        "steps": steps(monkeypatch, ["#d0", "#d1"]),
    }
    done = subprocess.run(
        [node(), "--require", str(tmp_path / "short.js"), str(HELPER)],
        input=json.dumps(request),
        capture_output=True,
        text=True,
        timeout=30,
        env=state.environment(state.TEMP_ROOT),
    )
    assert done.returncode == 1 and "BROWSER_TIMEOUT" in done.stdout, done.stdout + done.stderr
    assert CODE not in done.stdout + done.stderr
    after = json.loads((tmp_path / "out.json").read_text())
    assert after["filled"], "the deadline must fire after the code reached the boxes"
    assert after["left"] == 0, "the deadline must still empty every box"
