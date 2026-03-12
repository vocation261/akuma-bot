import unittest

from infrastructure.discord.commands.registry import (
    _transcript_ended_space_check,
    _upsert_panel_in_invocation_message,
)


class FakeMessage:
    def __init__(self, message_id: int = 1):
        self.id = message_id


class FakeInteraction:
    def __init__(self, message):
        self.guild = object()
        self.channel = object()
        self._message = message

    async def original_response(self):
        return self._message


class FakePanelGateway:
    def __init__(self):
        self.calls = []

    async def upsert(self, guild, channel, note: str = "", target_message=None):
        self.calls.append(
            {
                "guild": guild,
                "channel": channel,
                "note": note,
                "target_message": target_message,
            }
        )
        return target_message, True


class DashAndTranscriptGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_upsert_panel_in_invocation_message_uses_original_response(self):
        target_message = FakeMessage(message_id=77)
        interaction = FakeInteraction(target_message)
        panel_gateway = FakePanelGateway()

        message, updated = await _upsert_panel_in_invocation_message(interaction, panel_gateway, note="refresh")

        self.assertTrue(updated)
        self.assertIs(message, target_message)
        self.assertEqual(len(panel_gateway.calls), 1)
        self.assertIs(panel_gateway.calls[0]["target_message"], target_message)
        self.assertEqual(panel_gateway.calls[0]["note"], "refresh")

    def test_transcript_guard_rejects_live_space(self):
        allowed, message = _transcript_ended_space_check({"is_live": True, "status_key": "live"})

        self.assertFalse(allowed)
        self.assertIn("only works for ended Spaces", message)

    def test_transcript_guard_rejects_unknown_state(self):
        allowed, message = _transcript_ended_space_check({"is_live": False, "status_key": "unknown"})

        self.assertFalse(allowed)
        self.assertIn("Could not confirm", message)

    def test_transcript_guard_accepts_ended_space(self):
        allowed, message = _transcript_ended_space_check({"is_live": False, "status_key": "ended"})

        self.assertTrue(allowed)
        self.assertEqual(message, "")


if __name__ == "__main__":
    unittest.main()
