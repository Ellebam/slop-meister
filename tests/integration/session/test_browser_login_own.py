"""The page helper reads, fills and closes only this session's tab and the popups it opened."""

import json

import pytest

from tests.integration.session.test_browser_login import HELPER, node

# Five pages of one profile: a peer's tab, the own tab T1, its popup, the popup's popup, and a
# popup of the peer. A page whose target does not answer belongs to nobody.
PAGES = """
const {route}=require(process.argv[1]);
const request=JSON.parse(process.argv[2]);
const closed=[];
const page=(id,opener,url)=>({
 context:()=>({newCDPSession:async()=>({detach:async()=>{},send:async()=>{
  if(!id)throw Error('gone');return {targetInfo:{targetId:id,openerId:opener}}}})}),
 url:()=>url,frames:()=>[],close:async()=>{closed.push(id)}});
const pages=[page('T0',undefined,'https://peer.example/a'),page('T1',undefined,'https://own.example/p'),
 page('T2','T1','https://own.example/popup'),page('T3','T2','https://own.example/deeper'),
 page('T4','T0','https://peer.example/popup'),page(null,'T1','https://own.example/gone')];
route(request.main===false?pages.filter((_,i)=>i!==1):pages,request).then(
 result=>console.log(JSON.stringify({result,closed})),
 error=>console.log(JSON.stringify({error:error.message,closed})));
"""


def run(request):
    done = node("-e", PAGES, str(HELPER), json.dumps(request))
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_the_own_tab_is_named_by_its_chrome_target():
    assert run({"action": "own", "index": 1})["result"] == {"target": "T1"}


def test_a_check_reads_only_the_own_tab_and_the_popups_it_opened():
    found = run({"action": "filled", "own": "T1", "current": 2, "selectors": []})["result"]
    assert found == {
        "result": "EMPTY",
        "pages": 3,
        "address": "https://own.example/p",
        "main": 1,
        "owned": [1, 2, 3],
    }


@pytest.mark.parametrize("current", [0, 4, 5])
def test_a_current_tab_of_another_session_is_named(current):
    found = run({"action": "filled", "own": "T1", "current": current, "selectors": []})
    assert found["result"] == {"result": "FOREIGN"}


@pytest.mark.parametrize(
    ("action", "result"), [("filled", "PAGE_LOST"), ("fill", "BROWSER_BLOCKED")]
)
def test_a_lost_own_tab_reads_and_fills_nothing(action, result):
    request = {"action": action, "own": "T1", "main": False, "current": None, "selectors": []}
    found = run({**request, "steps": [{"origin": "https://own.example", "path": "/p"}]})
    assert found["result"]["result"] == result
    if action == "fill":
        assert found["result"]["credential_input"] is False


def test_close_ends_the_own_popups_before_the_own_tab_and_nothing_else():
    assert run({"action": "close", "own": "T1"})["closed"] == ["T2", "T3", "T1"]


@pytest.mark.parametrize("index", [0, 1, 4])
def test_closing_one_tab_reaches_only_an_own_popup(index):
    assert run({"action": "close", "own": "T1", "index": index}) == {
        "error": "PAGE_OPERATION_FAILED",
        "closed": [],
    }
    assert run({"action": "close", "own": "T1", "index": 3})["closed"] == ["T3"]
