from slack_bot.formatting import SECTION_LIMIT, markdown_to_mrkdwn, section, user_story_blocks
from tests.conftest import MEETING


def test_markdown_is_converted_to_slack_mrkdwn():
    text = "## Decisions\n- **Eve** owns it\n- See [ticket](https://x.atlassian.net/browse/POC-1)"
    assert markdown_to_mrkdwn(text) == (
        "*Decisions*\n• *Eve* owns it\n• See <https://x.atlassian.net/browse/POC-1|ticket>"
    )


def test_slack_formatting_is_left_alone():
    text = "*already bold* and _italic_"
    assert markdown_to_mrkdwn(text) == text


def test_long_sections_are_truncated_to_slack_limit():
    block = section("x" * 5000)
    assert len(block["text"]["text"]) == SECTION_LIMIT


def test_user_stories_empty_state():
    blocks = user_story_blocks({**MEETING, "user_stories": []})
    assert blocks[1]["text"]["text"] == "No user stories came up."
