from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    Protocol,
    get_origin,
    runtime_checkable,
)

from strawberry.annotation import StrawberryAnnotation
from strawberry.schema.type_comparison import is_same_type, resolve_lazy_type
from strawberry.types.base import StrawberryOptional
from strawberry.types.union import StrawberryUnion

if TYPE_CHECKING:
    from collections.abc import Collection

    from strawberry.types.field import StrawberryField
    from strawberry.types.info import Info


@runtime_checkable
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

    # Resolve the target the same way the union members were resolved at schema
    # build time. A concrete generic error type (e.g. ``Error[int]``) otherwise
    # collapses to the bare generic definition and silently never matches the
    # ``Error[int]`` member of the union.
    target_type = resolve_lazy_type(type_)
    if get_origin(target_type) is not None:
        target_type = StrawberryAnnotation(target_type).resolve()

    return any(is_same_type(union_type, target_type) for union_type in field_type.types)


def get_exception_types(
    handler: ExceptionHandler,
) -> tuple[type[Exception], ...]:
    exception_type = handler.exception_type

    if isinstance(exception_type, type):
        return (exception_type,)

    return tuple(exception_type)


def validate_exception_handlers(handlers: tuple[ExceptionHandler, ...]) -> None:
    """Validate exception handlers eagerly, at schema-construction time.

    A misconfigured handler otherwise only fails when a matching exception is
    raised at request time, where it typically masks the original error (a bad
    ``exception_type`` raises ``TypeError`` inside ``isinstance``; a class passed
    instead of an instance, or a mistyped ``handle`` method, surfaces as an
    unrelated error). Failing here keeps the real cause visible.
    """
    from collections.abc import Collection

    for handler in handlers:
        name = handler.__name__ if isinstance(handler, type) else type(handler).__name__

        if isinstance(handler, type):
            raise TypeError(
                f"Exception handler '{name}' must be passed as an instance, not a "
                f"class (did you mean '{name}()'?)."
            )

        exception_type = getattr(handler, "exception_type", None)

        if isinstance(exception_type, type):
            exception_types: tuple[object, ...] = (exception_type,)
        elif isinstance(exception_type, Collection) and not isinstance(
            exception_type, (str, bytes)
        ):
            exception_types = tuple(exception_type)
        else:
            exception_types = ()

        if not exception_types or not all(
            isinstance(candidate, type) and issubclass(candidate, BaseException)
            for candidate in exception_types
        ):
            raise TypeError(
                f"Exception handler '{name}' must define 'exception_type' as an "
                f"exception class or a collection of exception classes, got "
                f"{exception_type!r}."
            )

        if getattr(handler, "error_type", None) is None:
            raise TypeError(
                f"Exception handler '{name}' must define 'error_type' as the "
                f"GraphQL type it returns."
            )

        handle = getattr(type(handler), "handle", None)

        if handle is None or handle is ExceptionHandler.handle:
            raise TypeError(
                f"Exception handler '{name}' must implement a 'handle' method."
            )


__all__ = [
    "ExceptionHandler",
    "field_contains_type",
    "get_exception_types",
    "validate_exception_handlers",
]
