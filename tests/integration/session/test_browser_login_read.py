"""Read-only helper modes report page state and never write or click outside their one control."""

import json

import pytest

from tests.integration.session.test_browser_login import HELPER, node


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
 matches(s){return s===':disabled'&&!!this.disabled}
 constructor(){this.nodeName='INPUT';this.type='password';this.isConnected=true;}
 get value(){return ''} set value(v){events.push('write')}
 checkVisibility(){return true}
 getBoundingClientRect(){return {x:0,y:0,width:10,height:10}}
 contains(e){return this===e}
 dispatchEvent(){events.push('event')}
}
const field=new Input();
const button={matches(s){return s===':disabled'&&!!this.disabled},
 disabled:false,isConnected:true,checkVisibility:()=>true,
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
