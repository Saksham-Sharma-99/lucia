import pytest

from lucia.db.base import Base, table_name


@pytest.mark.parametrize(
    ("cls", "table"),
    [
        ("Firm", "firms"),
        ("AppUser", "app_users"),
        ("RegistryEntry", "registry_entries"),
        ("AgentPrompt", "agent_prompts"),
        ("CompiledAgentFirmMapping", "compiled_agent_firm_mappings"),
        ("Key", "keys"),
        ("Day", "days"),
    ],
)
def test_table_name_is_snake_case_plural(cls: str, table: str) -> None:
    assert table_name(cls) == table


def test_table_names_are_derived_not_declared() -> None:
    for mapper in Base.registry.mappers:
        cls = mapper.class_
        assert "__tablename__" not in vars(cls), cls.__name__
        assert table_name(cls.__name__) in Base.metadata.tables, cls.__name__


def test_id_first_and_timestamps_last() -> None:
    for table in Base.metadata.tables.values():
        columns = [c.name for c in table.columns]
        assert columns[0] == "id", table.name
        assert columns[-2:] == ["created_at", "updated_at"], table.name
