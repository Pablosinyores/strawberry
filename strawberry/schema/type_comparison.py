from __future__ import annotations

from strawberry.types.base import (
    StrawberryObjectDefinition,
    StrawberryOptional,
    StrawberryType,
    has_object_definition,
)
from strawberry.types.lazy_type import LazyType


def resolve_lazy_type(type_: object) -> object:
    if isinstance(type_, LazyType):
        return type_.resolve_type()

    if isinstance(type_, StrawberryOptional) and isinstance(type_.of_type, LazyType):
        return StrawberryOptional(type_.of_type.resolve_type())

    return type_


def get_object_definition(type_: object) -> StrawberryObjectDefinition | None:
    type_ = resolve_lazy_type(type_)

    if isinstance(type_, StrawberryObjectDefinition):
        return type_

    if has_object_definition(type_):
        return type_.__strawberry_definition__

    return None


def is_same_type(left: object, right: object) -> bool:
    left = resolve_lazy_type(left)
    right = resolve_lazy_type(right)

    if left is right:
        return True

    left_definition = get_object_definition(left)
    right_definition = get_object_definition(right)

    if left_definition is None or right_definition is None:
        return False

    return is_same_type_definition(left_definition, right_definition)


def is_same_type_definition(
    first_type_definition: StrawberryObjectDefinition | StrawberryType,
    second_type_definition: StrawberryObjectDefinition | StrawberryType,
) -> bool:
    # TODO: maybe move this on the StrawberryType class
    if not isinstance(
        first_type_definition, StrawberryObjectDefinition
    ) or not isinstance(second_type_definition, StrawberryObjectDefinition):
        return False

    if first_type_definition.origin is second_type_definition.origin:
        return True

    # When sys.modules is cleared (e.g. by test runners or Django reloaders)
    # and a module is reimported, Python creates brand-new class objects.
    # The identity check above fails, so fall back to comparing the
    # fully-qualified class name which survives reimports.
    first_origin = first_type_definition.origin
    second_origin = second_type_definition.origin
    if (
        first_origin.__qualname__ == second_origin.__qualname__
        and first_origin.__module__ == second_origin.__module__
    ):
        return True

    if (
        first_type_definition.concrete_of is None
        or first_type_definition.concrete_of != second_type_definition.concrete_of
        or (
            first_type_definition.type_var_map.keys()
            != second_type_definition.type_var_map.keys()
        )
    ):
        return False

    for type_var, type1 in first_type_definition.type_var_map.items():
        type2 = second_type_definition.type_var_map[type_var]

        resolved_type1 = resolve_lazy_type(type1)
        resolved_type2 = resolve_lazy_type(type2)

        same_type = resolved_type1 == resolved_type2
        # If both types have object definitions, we are handling a nested generic
        # type like `Foo[Foo[int]]`, meaning we need to compare their type definitions
        # as they will actually be different instances of the type.
        if (
            not same_type
            and has_object_definition(resolved_type1)
            and has_object_definition(resolved_type2)
        ):
            same_type = is_same_type_definition(
                resolved_type1.__strawberry_definition__,
                resolved_type2.__strawberry_definition__,
            )

        if not same_type:
            return False

    return True


__all__ = [
    "get_object_definition",
    "is_same_type",
    "is_same_type_definition",
    "resolve_lazy_type",
]
