"""Runtime implementations of tools, by name. A tool without one can't be planned."""

from lucia.harness.tools import harness_tools, slack_tool
from lucia.harness.tools.base import ToolImpl

IMPLS: dict[str, ToolImpl] = {
    "harness.emit_finding": harness_tools.emit_finding,
    "harness.journal_append": harness_tools.journal_append,
    "slack.send_message": slack_tool.send_message,
    "slack.read_thread": slack_tool.read_thread,
}
