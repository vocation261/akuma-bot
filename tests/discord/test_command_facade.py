import unittest

from akuma_bot.infrastructure.discord.command_handlers import register_commands, register_tree_error_handler


class CommandFacadeTests(unittest.TestCase):
    def test_command_facade_exports_callables(self):
        self.assertTrue(callable(register_commands))
        self.assertTrue(callable(register_tree_error_handler))


if __name__ == "__main__":
    unittest.main()
