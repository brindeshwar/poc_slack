from slack_bot.formatting import SECTION_LIMIT, section, user_story_blocks
from tests.conftest import MEETING


def test_long_sections_are_truncated_to_slack_limit():
    block = section("x" * 5000)
    assert len(block["text"]["text"]) == SECTION_LIMIT


def test_user_stories_empty_state():
    blocks = user_story_blocks({**MEETING, "user_stories": []})
    assert blocks[1]["text"]["text"] == "No user stories came up."
