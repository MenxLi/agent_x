# https://pydantic.dev/docs/validation/latest/concepts/types/#named-recursive-types
import sys
if sys.version_info >= (3, 12):
    type JsonType = str | int | float | bool | None | dict[str, JsonType] | list[JsonType]
else:
    from typing import Union
    from typing_extensions import TypeAliasType
    JsonType = TypeAliasType(
        'JsonType',
        'Union[dict[str, JsonType], list[JsonType], str, int, float, bool, None]',  
    )

from typing import Literal
type ModelCapabilityType = Literal['vision']
ModelCapabilityOptions = set(['vision'])