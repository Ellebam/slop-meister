"""Startup context accounts for tokens, attachment bytes and deferred MCP tools."""

import json

from slopmeister.threads import startup_context

RECORDS = [
    {"type": "user", "message": {"content": "Probe kickoff"}},
    {
        "type": "attachment",
        "attachment": {
            "type": "deferred_tools_delta",
            "addedNames": ["WebFetch", "WebSearch"],
            "addedLines": ["WebFetch\n", "WebSearch\n"],
        },
    },
    {
        "type": "attachment",
        "attachment": {
            "type": "agent_listing_delta",
            "addedTypes": ["Explore"],
            "addedLines": ["- Explore: search\n"],
        },
    },
    {
        "type": "attachment",
        "attachment": {
            "type": "skill_listing",
            "content": "- frame: step 1\n- plan: step 2\n",
            "names": ["frame", "plan"],
        },
    },
    {
        "type": "assistant",
        "message": {
            "id": "msg_1",
            "usage": {
                "input_tokens": 2,
                "cache_creation_input_tokens": 100,
                "cache_read_input_tokens": 900,
            },
        },
    },
    {"type": "assistant", "message": {"id": "msg_1", "content": [{"type": "text", "text": "ok"}]}},
    {
        "type": "assistant",
        "message": {"id": "msg_1", "content": [{"type": "tool_use", "name": "Bash"}]},
    },
    {
        "type": "attachment",
        "attachment": {
            "type": "deferred_tools_delta",
            "addedNames": ["mcp__alpha__one", "mcp__beta__two", "mcp__beta__three"],
            "addedLines": ["mcp__alpha__one\n", "mcp__beta__two\n", "mcp__beta__three\n"],
        },
    },
    {
        "type": "attachment",
        "attachment": {
            "type": "mcp_instructions_delta",
            "addedNames": ["alpha"],
            "addedBlocks": ["## alpha\nuse it\n"],
        },
    },
    {"type": "assistant", "message": {"id": "msg_2"}},
]


def output(tmp_path, capsys) -> list[str]:
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text("".join(json.dumps(record) + "\n" for record in RECORDS))
    startup_context.report(str(transcript))
    return capsys.readouterr().out.splitlines()


def test_first_turn_sums_all_usage_fields(tmp_path, capsys):
    assert output(tmp_path, capsys)[0] == (
        "first turn 1002 prompt tokens (input_tokens 2, "
        "cache_creation_input_tokens 100, cache_read_input_tokens 900)"
    )


def test_assistant_records_with_one_message_id_are_one_turn(tmp_path, capsys):
    lines = output(tmp_path, capsys)
    assert any(line.startswith("after turn 1 deferred_tools_delta ") for line in lines)
    assert any(line.startswith("after turn 1 mcp_instructions_delta ") for line in lines)
    assert not any(line.startswith(("after turn 2 ", "after turn 3 ")) for line in lines)


def test_mcp_servers_and_tool_names_come_from_prefixes(tmp_path, capsys):
    lines = output(tmp_path, capsys)
    assert "mcp servers seen: alpha beta" in lines
    assert "mcp tool names: 3" in lines


def test_kickoff_and_attachment_bytes_are_reported(tmp_path, capsys):
    lines = output(tmp_path, capsys)
    assert "kickoff 13 bytes" in lines
    assert "startup skill_listing 31 bytes, 2 names: frame plan" in lines
    assert "startup agent_listing_delta 18 bytes, 1 names: Explore" in lines
    assert "after turn 1 mcp_instructions_delta 16 bytes, 1 names" in lines
