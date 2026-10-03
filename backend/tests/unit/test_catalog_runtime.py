from jsonschema import Draft202012Validator

from lucia.connectors.slack import SCOPES
from lucia.firms.schemas import FirmSettings
from lucia.registry.catalog import TOOLS
from lucia.registry.sync import catalog_rows

RUNTIME_TOOLS = {"vapi.place_call", "slack.send_message", "slack.read_thread"}


def test_runtime_tools_declare_valid_input_and_output_schemas() -> None:
    tools = {t.name: t for t in TOOLS}
    for name in RUNTIME_TOOLS:
        Draft202012Validator.check_schema(tools[name].input_schema)
        Draft202012Validator.check_schema(tools[name].output_schema)
    call = tools["vapi.place_call"].input_schema
    assert set(call["required"]) == {"to_contact_id", "script", "first_message"}


def test_sync_rows_carry_the_schemas() -> None:
    row = next(r for r in catalog_rows() if r["name"] == "vapi.place_call")
    assert row["input_schema"]["properties"]["to_contact_id"]["format"] == "uuid"
    assert row["output_schema"]["properties"]["call_id"]["type"] == "string"


def test_slack_scopes_are_final() -> None:
    assert set(SCOPES.split(",")) == {
        "app_mentions:read",
        "chat:write",
        "channels:history",
        "groups:history",
        "files:write",
        "im:write",
        "reactions:write",
        "users:read",
    }


def test_firms_can_route_alerts_in_app() -> None:
    settings = FirmSettings.model_validate({"alert_routing": {"P1": ["in_app", "slack_dm"]}})
    assert settings.alert_routing["P1"] == ["in_app", "slack_dm"]
