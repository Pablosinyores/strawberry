from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any, Protocol, get_origin

from strawberry.annotation import StrawberryAnnotation
from strawberry.schema.type_comparison import is_same_type, resolve_lazy_type
from strawberry.types.base import StrawberryOptional
from strawberry.types.union import StrawberryUnion

if TYPE_CHECKING:
    from collections.abc import Collection

    from strawberry.types.field import StrawberryField
    from strawberry.types.info import Info


class ExceptionHandler(Protocol):
    exception_type: type[Exception] | Collection[type[Exception]]
    error_type: type

    def handle(
        self,
        exception: Exception,
        *,
        field: StrawberryField,
        info: Info,
    ) -> Any: ...


def field_contains_type(field: StrawberryField, type_: type) -> bool:
    field_type = resolve_lazy_type(field.type)

    if get_origin(field_type) is Annotated:
        field_type = StrawberryAnnotation(field_type).resolve()

    if isinstance(field_type, StrawberryOptional):
        field_type = resolve_lazy_type(field_type.of_type)
        if get_origin(field_type) is Annotated:
            field_type = StrawberryAnnotation(field_type).resolve()

    if not isinstance(field_type, StrawberryUnion):
        return False

    return any(is_same_type(union_type, type_) for union_type in field_type.types)


def get_exception_types(
    handler: ExceptionHandler,
) -> tuple[type[Exception], ...]:
    exception_type = handler.exception_type

    if isinstance(exception_type, type):
        return (exception_type,)

    return tuple(exception_type)


def should_handle_exception(
    handler: ExceptionHandler,
    exception: Exception,
    field: StrawberryField,
) -> bool:
    if not isinstance(exception, get_exception_types(handler)):
        return False

    return field_contains_type(field, handler.error_type)


__all__ = [
    "ExceptionHandler",
    "field_contains_type",
    "get_exception_types",
    "should_handle_exception",
]
