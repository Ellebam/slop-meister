"""Credential input into a form in one named embedded frame keeps both destinations strict."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from slopmeister.session import browser_state as state

HELPER = Path(__file__).resolve().parents[3] / "src/skills/browser-login/scripts/input.cjs"

# A top page on example.com embeds sign-in frames from id.example. Each evaluation runs with the
# globals of the document it belongs to, as a real execution context does.
FRAME = """
const {operate}=require(process.argv[1]);
const fault=process.argv[2];
const SECRET='dummy-private-value';
let clicks=0,writes=0,clock=0;
// Each deadline read advances the clock, so a later step's wait ends after a few polls.
Date.now=()=>clock+=5000;
class Input{
 matches(s){return s===':disabled'&&!!this.disabled}
 constructor(id,type){this.id=id;this.type=type;this.nodeName='INPUT';this.isConnected=true;this.stored='';}
 get value(){return this.stored} set value(v){this.stored=v;if(v)writes++}
 checkVisibility(){return true}
 getBoundingClientRect(){return {x:0,y:0,width:10,height:10}}
 contains(e){return this===e}
 dispatchEvent(){}
}
global.HTMLInputElement=Input;
const pass=new Input('#pass','password'),code=new Input('#code','tel');
let topUrl='https://example.com/sign-in';
const element={checkVisibility:()=>true};
const button={matches(s){return s===':disabled'&&!!this.disabled},
 disabled:false,isConnected:true,checkVisibility:()=>true,contains:e=>e===button,
 getBoundingClientRect:()=>({x:20,y:0,width:10,height:10}),
 click(){clicks++;if(fault==='leaves')go('https://evil.example/in');
  if(fault==='second'&&clicks===1)go('https://id.example/code');
  if(fault==='away'){topUrl='https://example.com/elsewhere';go('https://id.example/code');}
  if(fault==='pushes')frames[0].pushed='/done';}};
// A navigation discards the frame's old document together with whatever its fields held.
function go(address){const old=inputs[frames[0].address];if(old)old.stored='';
 frames[0].address=address;}
const inputs={'https://id.example/in':pass,'https://id.example/code':code};
const frameDocument=frame=>({querySelectorAll:s=>{const input=inputs[frame.address];
  return s==='*'?[input,button]:s===input?.id?[input]:s==='#go'?[button]:[]},
 elementFromPoint:x=>x>=20?button:inputs[frame.address]});
const topDocument={elementFromPoint:()=>fault==='covered'?{}:element};
function frame(address){
 const self={address,url:()=>self.address,frameElement:async()=>element,
  $:async()=>({boundingBox:async()=>({x:5,y:5,width:10,height:10})}),
  evaluateHandle:async()=>{const owner=self.address;return {evaluate:async(fn,step)=>{
   if(owner!==self.address)throw Error('context destroyed');
   const {origin,pathname}=new URL(self.address);
   // A same-document navigation changes the path but keeps the document and its fields.
   global.location={origin,pathname:self.pushed||pathname};global.document=frameDocument(self);
   return fn(document,step);
  }}}};
 return self;
}
const addresses={match:['https://id.example/in'],two:['https://id.example/in','https://id.example/in'],
 path:['https://id.example/other'],origin:['https://evil.example/in'],none:[]};
const frames=(addresses[fault]||addresses.match).map(frame);
const page={url:()=>topUrl,mainFrame:()=>({childFrames:()=>frames,
 evaluate:async(fn,arg)=>{global.document=topDocument;
  if(fault==='moves')topUrl='https://example.com/elsewhere';return fn(arg);}})};
const step=(path,selector)=>({origin:'https://example.com',path:'/sign-in',submit:'#go',
 frame:{origin:'https://id.example',path},fields:[{selector,types:['password','tel'],value:SECRET}]});
const steps=['second','leaves','away'].includes(fault)
 ?[step('/in','#pass'),step('/code','#code')]:[step('/in','#pass')];
operate([page],{action:'fill',steps})
 .then(result=>result,()=>'THROWN')
 .then(result=>console.log(JSON.stringify({result,clicks,writes,
  remaining:[pass,code].some(i=>i.stored.includes(SECRET))})));
"""


def node(*arguments):
    executable = shutil.which("node")
    if executable is None:
        pytest.fail("Browser consumer tests need Node on PATH")
    env = state.environment(state.TEMP_ROOT)
    return subprocess.run(
        [executable, *arguments], capture_output=True, text=True, timeout=10, env=env
    )


def run(fault):
    done = node("-e", FRAME, str(HELPER), fault)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


@pytest.mark.parametrize("fault", ["match", "second"])
def test_the_named_frame_receives_each_step_and_is_emptied_after_it(fault):
    data = run(fault)
    assert data["result"] == {"result": "BROWSER_LOGIN_SUBMITTED"}
    assert data["clicks"] == data["writes"] == {"match": 1, "second": 2}[fault]
    assert not data["remaining"], "the clear must reach the frame's own document"


def test_a_frame_that_changes_its_own_path_on_submit_keeps_no_value():
    data = run("pushes")
    assert data["result"] == {"result": "BROWSER_LOGIN_SUBMITTED"}
    assert (data["clicks"], data["writes"], data["remaining"]) == (1, 1, False)


@pytest.mark.parametrize(
    ("fault", "reason"),
    [
        ("none", "FRAME_UNAVAILABLE"),
        ("two", "FRAME_UNAVAILABLE"),
        ("path", "FRAME_UNAVAILABLE"),
        ("origin", "FRAME_UNAVAILABLE"),
        ("covered", "FIELD_UNAVAILABLE"),
    ],
)
def test_no_value_is_written_unless_one_exact_frame_is_open_and_uncovered(fault, reason):
    data = run(fault)
    assert data["result"]["reason"] == reason
    assert data["result"]["credential_input"] is False
    assert data["clicks"] == data["writes"] == 0


def test_a_top_page_that_moves_after_input_gets_no_click_and_no_kept_value():
    data = run("moves")
    assert data["result"] == {
        "result": "BROWSER_BLOCKED",
        "phase": "input",
        "step": 0,
        "reason": "FRAME_CHANGED: do not retry submission",
    }
    assert (data["clicks"], data["writes"], data["remaining"]) == (0, 1, False)


@pytest.mark.parametrize(
    ("fault", "reason"), [("leaves", "FRAME_UNAVAILABLE"), ("away", "WRONG_DESTINATION")]
)
def test_a_later_step_gets_no_value_once_the_frame_or_its_tab_moved(fault, reason):
    data = run(fault)
    assert data["result"]["reason"] == reason
    assert data["result"]["step"] == 1 and data["result"]["credential_input"] is True
    assert (data["clicks"], data["writes"], data["remaining"]) == (1, 1, False)
