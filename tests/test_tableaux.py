"""/tableaux: guidance served from a mocked GitHub contents API."""

import json

CONTENTS = "https://api.github.com/repos/dataesr/tableaux/contents"
INDEX = {
    "guidance": [{"id": "agents", "title": "Agents", "path": "AGENTS.md"}],
    "templates": [],
    "components": [],
    "data_sources": [],
}


def mock_repo(upstream):
    upstream.get(f"{CONTENTS}/docs/dashboard-prototype/prototype.index.json").respond(text=json.dumps(INDEX))
    upstream.get(f"{CONTENTS}/AGENTS.md").respond(text="# Agents guide")


def test_lists_the_tableaux_tools(connect):
    assert {"list_guidance", "get_guidance", "validate_dashboard_spec", "validate_board_bundle"} <= set(connect("/tableaux").tool_names())


def test_list_guidance_reads_the_repository_index(connect, upstream):
    mock_repo(upstream)
    result = connect("/tableaux").call("list_guidance").data
    assert result == {"repository": "dataesr/tableaux", "ref": "staging", "guidance": INDEX["guidance"]}


def test_get_guidance_returns_the_file_content(connect, upstream):
    mock_repo(upstream)
    result = connect("/tableaux").call("get_guidance", {"guidance_id": "agents"}).data
    assert result["content"] == "# Agents guide"


def test_unknown_guidance_lists_the_known_ids(connect, upstream):
    mock_repo(upstream)
    result = connect("/tableaux").call("get_guidance", {"guidance_id": "nope"})
    assert result.is_error
    assert "Known: agents" in result.text


def test_list_existing_boards_walks_the_directories(connect, upstream):
    upstream.get(f"{CONTENTS}/client/src/boards").respond(
        json=[{"type": "dir", "path": "client/src/boards/atlas"}, {"type": "dir", "path": "client/src/boards/integration"}]
    )
    upstream.get(f"{CONTENTS}/client/src/boards/atlas").respond(json=[{"type": "file", "path": "client/src/boards/atlas/routes.tsx"}])
    upstream.get(f"{CONTENTS}/client/src/boards/integration").respond(
        json=[{"type": "file", "path": "client/src/boards/integration/routes.tsx"}]
    )
    assert connect("/tableaux").call("list_existing_boards").data["board_ids"] == ["atlas"]


def test_github_refusal_is_reported_as_a_tool_error(connect, upstream):
    upstream.get(url__startswith=CONTENTS).respond(403)
    result = connect("/tableaux").call("list_guidance")
    assert result.is_error
    assert "GITHUB_TOKEN" in result.text
