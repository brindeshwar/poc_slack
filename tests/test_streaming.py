from slack_sdk.errors import SlackApiError

from slack_bot.streaming import LimitedStream
from tests.conftest import Recorder


class Stream:
    def __init__(self, fail_with=None):
        self.text, self.chunks, self.stopped_with, self.fail_with = [], [], None, fail_with

    async def append(self, *, markdown_text=None, chunks=None):
        if self.fail_with:
            error, self.fail_with = self.fail_with, None
            raise SlackApiError(error, {"error": error})
        if markdown_text is not None:
            self.text.append(markdown_text)
        if chunks is not None:
            self.chunks.extend(chunks)

    async def stop(self, **kwargs):
        self.stopped_with = kwargs


class Opener:
    def __init__(self, *streams):
        self.queue, self.opened = list(streams), []

    async def __call__(self):
        stream = self.queue.pop(0) if self.queue else Stream()
        self.opened.append(stream)
        return stream


async def test_short_answer_uses_one_stream():
    opener, client = Opener(), Recorder()
    stream = LimitedStream(opener, client, "C1", "1.0")
    await stream.task("t1", "Searching meetings", "in_progress")
    await stream.text("Hello")
    await stream.finish(blocks=[{"type": "divider"}])
    [only] = opener.opened
    assert only.chunks == [
        {"type": "task_update", "id": "t1", "title": "Searching meetings", "status": "in_progress"}
    ]
    assert only.text == ["Hello"]
    assert only.stopped_with == {"blocks": [{"type": "divider"}], "session_status": "active"}


async def test_rolls_over_before_slacks_12000_character_limit():
    opener = Opener()
    stream = LimitedStream(opener, Recorder(), "C1", "1.0", rollover_at=10)
    await stream.text("abcdef")
    await stream.text("ghijkl")  # would pass 10 → new message first
    await stream.finish()
    first, second = opener.opened
    assert first.text == ["abcdef"] and first.stopped_with == {"session_status": "processing"}
    assert second.text == ["ghijkl"] and second.stopped_with["session_status"] == "active"


async def test_one_huge_delta_is_split_across_messages():
    opener = Opener()
    stream = LimitedStream(opener, Recorder(), "C1", "1.0", rollover_at=10)
    await stream.text("x" * 25)
    await stream.finish()
    assert ["".join(s.text) for s in opener.opened] == ["x" * 10, "x" * 10, "x" * 5]


async def test_msg_too_long_from_slack_triggers_rollover_and_retry():
    opener = Opener(Stream(fail_with="msg_too_long"))
    stream = LimitedStream(opener, Recorder(), "C1", "1.0")
    await stream.text("hello")
    await stream.finish()
    first, second = opener.opened
    assert first.text == [] and second.text == ["hello"]


async def test_stream_closed_by_slack_falls_back_to_plain_messages():
    client = Recorder()
    opener = Opener(Stream(fail_with="message_not_in_streaming_state"))
    stream = LimitedStream(opener, client, "C1", "1.0")
    await stream.text("late text")
    await stream.text("more")
    await stream.finish()  # nothing left to stop
    assert client.calls == [
        ("chat_postMessage", {"channel": "C1", "thread_ts": "1.0", "markdown_text": "late text"}),
        ("chat_postMessage", {"channel": "C1", "thread_ts": "1.0", "markdown_text": "more"}),
    ]


async def test_other_slack_errors_propagate():
    opener = Opener(Stream(fail_with="channel_not_found"))
    stream = LimitedStream(opener, Recorder(), "C1", "1.0")
    try:
        await stream.text("x")
    except SlackApiError as exc:
        assert exc.response["error"] == "channel_not_found"
    else:
        raise AssertionError("expected SlackApiError")
