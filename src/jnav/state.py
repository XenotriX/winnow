from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from jnav.field_mapping import FieldMapping
from jnav.filtering import FilterGroup
from jnav.selector_provider import Selector


class AppState(BaseModel):
    filter_root: FilterGroup = Field(default_factory=FilterGroup)
    selectors: list[Selector] = Field(default_factory=list)
    role_mapping: FieldMapping = Field(default_factory=FieldMapping)
    search_term: str = ""
    filtering_enabled: bool = True
    expanded_mode: bool = True
    detail_visible: bool = False
    show_selected_only: bool = False
    entry_index: int = 0


def load(path: Path) -> AppState:
    if not path.exists():
        return AppState()
    try:
        return AppState.model_validate_json(path.read_text())
    except ValidationError, OSError, ValueError:
        return AppState()


def save(path: Path, state: AppState) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(state.model_dump_json())
    except OSError:
        pass
