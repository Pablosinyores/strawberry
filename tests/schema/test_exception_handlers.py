import dataclasses
import inspect
from collections.abc import AsyncGenerator
from typing import Annotated, Generic, TypeVar

import pytest

import strawberry
from strawberry.extensions.field_extension import FieldExtension
from strawberry.field_extensions import InputMutationExtension
from strawberry.permission import BasePermission
from strawberry.types import Info
from strawberry.types.execution import PreExecutionError
from strawberry.types.field import StrawberryField
from strawberry.utils.aio import aclosing

T = TypeVar("T")


class CustomValidationError(Exception):
    pass


class UnexpectedError(Exception):
    pass


@strawberry.type
class ValidationErrorPayload:
    message: str


@strawberry.type
class OtherErrorPayload:
    message: str


@strawberry.type
class Success:
    value: str


ValidationResult = Annotated[
    Success | ValidationErrorPayload,
    strawberry.union("ValidationResult"),
]


class CustomValidationHandler(strawberry.ExceptionHandler):
    exception_type = CustomValidationError
    error_type = ValidationErrorPayload

    def handle(
        self,
        exception: Exception,
        *,
        field: StrawberryField,
        info: Info,
    ) -> ValidationErrorPayload:
        return ValidationErrorPayload(message=str(exception))


class FirstValidationHandler(CustomValidationHandler):
    def handle(
        self,
        exception: Exception,
        *,
        field: StrawberryField,
        info: Info,
    ) -> ValidationErrorPayload:
        return ValidationErrorPayload(message="first")


class SecondValidationHandler(CustomValidationHandler):
    def handle(
        self,
        exception: Exception,
        *,
        field: StrawberryField,
        info: Info,
    ) -> ValidationErrorPayload:
        return ValidationErrorPayload(message="second")


class OtherValidationHandler(CustomValidationHandler):
    error_type = OtherErrorPayload

    def handle(
        self,
        exception: Exception,
        *,
        field: StrawberryField,
        info: Info,
    ) -> OtherErrorPayload:
        return OtherErrorPayload(message="other")


@strawberry.input
class CustomInput:
    value: str

    def __post_init__(self) -> None:
        if len(self.value) < 2:
            raise CustomValidationError("value is too short")


@strawberry.type
class Query:
    ok: bool = True


def test_exception_handler_converts_argument_conversion_error_to_union_type():
    @strawberry.type
    class Mutation:
        @strawberry.mutation
        def create(self, input: CustomInput) -> Success | ValidationErrorPayload:
            return Success(value=input.value)

    schema = strawberry.Schema(
        query=Query,
        mutation=Mutation,
        exception_handlers=[CustomValidationHandler()],
    )

    result = schema.execute_sync(
        """
        mutation {
            create(input: { value: "a" }) {
                ... on Success {
                    value
                }
                ... on ValidationErrorPayload {
                    message
                }
            }
        }
        """
    )

    assert result.errors is None
    assert result.data == {"create": {"message": "value is too short"}}


def test_exception_handler_does_not_handle_when_error_type_is_not_in_return_union():
    @strawberry.type
    class Mutation:
        @strawberry.mutation
        def create(self, input: CustomInput) -> Success:
            return Success(value=input.value)

    schema = strawberry.Schema(
        query=Query,
        mutation=Mutation,
        exception_handlers=[CustomValidationHandler()],
    )

    result = schema.execute_sync(
        """
        mutation {
            create(input: { value: "a" }) {
                value
            }
        }
        """
    )

    assert result.errors is not None
    assert result.errors[0].message == "value is too short"
    assert result.data is None


def test_exception_handler_does_not_handle_unmatched_exception_type():
    processed_errors = []

    class TrackingSchema(strawberry.Schema):
        def process_errors(self, errors, execution_context=None):
            processed_errors.extend(errors)

    @strawberry.type
    class Mutation:
        @strawberry.mutation
        def create(self, value: str) -> Success | ValidationErrorPayload:
            raise UnexpectedError(f"unexpected value: {value}")

    schema = TrackingSchema(
        query=Query,
        mutation=Mutation,
        exception_handlers=[CustomValidationHandler()],
    )

    result = schema.execute_sync(
        """
        mutation {
            create(value: "abc") {
                ... on Success {
                    value
                }
                ... on ValidationErrorPayload {
                    message
                }
            }
        }
        """
    )

    assert result.errors is not None
    assert result.errors[0].message == "unexpected value: abc"
    assert result.data is None
    assert len(processed_errors) == 1
    assert processed_errors[0].message == "unexpected value: abc"


def test_exception_handler_converts_resolver_error_to_union_type():
    @strawberry.type
    class Mutation:
        @strawberry.mutation
        def create(self, value: str) -> Success | ValidationErrorPayload:
            raise CustomValidationError(f"invalid value: {value}")

    schema = strawberry.Schema(
        query=Query,
        mutation=Mutation,
        exception_handlers=[CustomValidationHandler()],
    )

    result = schema.execute_sync(
        """
        mutation {
            create(value: "abc") {
                ... on Success {
                    value
                }
                ... on ValidationErrorPayload {
                    message
                }
            }
        }
        """
    )

    assert result.errors is None
    assert result.data == {"create": {"message": "invalid value: abc"}}


def test_exception_handler_converted_error_is_not_processed():
    processed_errors = []

    class TrackingSchema(strawberry.Schema):
        def process_errors(self, errors, execution_context=None):
            processed_errors.extend(errors)

    @strawberry.type
    class Mutation:
        @strawberry.mutation
        def create(self, value: str) -> Success | ValidationErrorPayload:
            raise CustomValidationError(f"invalid value: {value}")

    schema = TrackingSchema(
        query=Query,
        mutation=Mutation,
        exception_handlers=[CustomValidationHandler()],
    )

    result = schema.execute_sync(
        """
        mutation {
            create(value: "abc") {
                ... on Success {
                    value
                }
                ... on ValidationErrorPayload {
                    message
                }
            }
        }
        """
    )

    assert result.errors is None
    assert result.data == {"create": {"message": "invalid value: abc"}}
    assert processed_errors == []


def test_exception_handler_uses_first_matching_handler():
    @strawberry.type
    class Mutation:
        @strawberry.mutation
        def create(self, value: str) -> Success | ValidationErrorPayload:
            raise CustomValidationError(f"invalid value: {value}")

    schema = strawberry.Schema(
        query=Query,
        mutation=Mutation,
        exception_handlers=[FirstValidationHandler(), SecondValidationHandler()],
    )

    result = schema.execute_sync(
        """
        mutation {
            create(value: "abc") {
                ... on Success {
                    value
                }
                ... on ValidationErrorPayload {
                    message
                }
            }
        }
        """
    )

    assert result.errors is None
    assert result.data == {"create": {"message": "first"}}


def test_exception_handler_uses_later_matching_handler():
    @strawberry.type
    class Mutation:
        @strawberry.mutation
        def create(self, value: str) -> Success | ValidationErrorPayload:
            raise CustomValidationError(f"invalid value: {value}")

    schema = strawberry.Schema(
        query=Query,
        mutation=Mutation,
        exception_handlers=[OtherValidationHandler(), SecondValidationHandler()],
    )

    result = schema.execute_sync(
        """
        mutation {
            create(value: "abc") {
                ... on Success {
                    value
                }
                ... on ValidationErrorPayload {
                    message
                }
            }
        }
        """
    )

    assert result.errors is None
    assert result.data == {"create": {"message": "second"}}


def test_exception_handler_converts_error_for_optional_union_type():
    @strawberry.type
    class Mutation:
        @strawberry.mutation
        def create(self, input: CustomInput) -> Success | ValidationErrorPayload | None:
            return Success(value=input.value)

    schema = strawberry.Schema(
        query=Query,
        mutation=Mutation,
        exception_handlers=[CustomValidationHandler()],
    )

    result = schema.execute_sync(
        """
        mutation {
            create(input: { value: "a" }) {
                ... on Success {
                    value
                }
                ... on ValidationErrorPayload {
                    message
                }
            }
        }
        """
    )

    assert result.errors is None
    assert result.data == {"create": {"message": "value is too short"}}


def test_exception_handler_can_return_none_for_optional_union_type():
    class NullValidationHandler(CustomValidationHandler):
        def handle(
            self,
            exception: Exception,
            *,
            field: StrawberryField,
            info: Info,
        ) -> None:
            return None

    @strawberry.type
    class Mutation:
        @strawberry.mutation
        def create(self, input: CustomInput) -> Success | ValidationErrorPayload | None:
            return Success(value=input.value)

    schema = strawberry.Schema(
        query=Query,
        mutation=Mutation,
        exception_handlers=[NullValidationHandler()],
    )

    result = schema.execute_sync(
        """
        mutation {
            create(input: { value: "a" }) {
                ... on Success {
                    value
                }
                ... on ValidationErrorPayload {
                    message
                }
            }
        }
        """
    )

    assert result.errors is None
    assert result.data == {"create": None}


def test_exception_handler_accepts_multiple_exception_types():
    class MultipleValidationHandler(CustomValidationHandler):
        exception_type = (CustomValidationError, UnexpectedError)

    @strawberry.type
    class Mutation:
        @strawberry.mutation
        def create(self, value: str) -> Success | ValidationErrorPayload:
            raise UnexpectedError(f"unexpected value: {value}")

    schema = strawberry.Schema(
        query=Query,
        mutation=Mutation,
        exception_handlers=[MultipleValidationHandler()],
    )

    result = schema.execute_sync(
        """
        mutation {
            create(value: "abc") {
                ... on Success {
                    value
                }
                ... on ValidationErrorPayload {
                    message
                }
            }
        }
        """
    )

    assert result.errors is None
    assert result.data == {"create": {"message": "unexpected value: abc"}}


def test_exception_handler_does_not_handle_list_of_union_type():
    @strawberry.type
    class Mutation:
        @strawberry.mutation
        def create(self, value: str) -> list[Success | ValidationErrorPayload]:
            raise CustomValidationError(f"invalid value: {value}")

    schema = strawberry.Schema(
        query=Query,
        mutation=Mutation,
        exception_handlers=[CustomValidationHandler()],
    )

    result = schema.execute_sync(
        """
        mutation {
            create(value: "abc") {
                ... on Success {
                    value
                }
                ... on ValidationErrorPayload {
                    message
                }
            }
        }
        """
    )

    assert result.errors is not None
    assert result.errors[0].message == "invalid value: abc"
    assert result.data is None


def test_exception_handler_matches_lazy_error_type_in_union():
    LazyValidationErrorPayload = Annotated[
        "ValidationErrorPayload",
        strawberry.lazy("tests.schema.test_exception_handlers"),
    ]

    @strawberry.type
    class Mutation:
        @strawberry.mutation
        def create(self, value: str) -> Success | LazyValidationErrorPayload:
            raise CustomValidationError(f"invalid value: {value}")

    schema = strawberry.Schema(
        query=Query,
        mutation=Mutation,
        exception_handlers=[CustomValidationHandler()],
    )

    result = schema.execute_sync(
        """
        mutation {
            create(value: "abc") {
                ... on Success {
                    value
                }
                ... on ValidationErrorPayload {
                    message
                }
            }
        }
        """
    )

    assert result.errors is None
    assert result.data == {"create": {"message": "invalid value: abc"}}


def test_exception_handler_matches_lazy_union_return_type():
    LazyValidationResult = Annotated[
        "ValidationResult",
        strawberry.lazy("tests.schema.test_exception_handlers"),
    ]

    @strawberry.type
    class Mutation:
        @strawberry.mutation
        def create(self, value: str) -> LazyValidationResult:
            raise CustomValidationError(f"invalid value: {value}")

    schema = strawberry.Schema(
        query=Query,
        mutation=Mutation,
        exception_handlers=[CustomValidationHandler()],
    )

    result = schema.execute_sync(
        """
        mutation {
            create(value: "abc") {
                ... on Success {
                    value
                }
                ... on ValidationErrorPayload {
                    message
                }
            }
        }
        """
    )

    assert result.errors is None
    assert result.data == {"create": {"message": "invalid value: abc"}}


def test_exception_handler_converts_resolver_error_inside_field_extension():
    class PassthroughExtension(FieldExtension):
        def resolve(self, next_, source, info, **kwargs):  # noqa: ANN003
            return next_(source, info, **kwargs)

    @strawberry.type
    class Mutation:
        @strawberry.mutation(extensions=[PassthroughExtension()])
        def create(self, value: str) -> Success | ValidationErrorPayload:
            raise CustomValidationError(f"invalid value: {value}")

    schema = strawberry.Schema(
        query=Query,
        mutation=Mutation,
        exception_handlers=[CustomValidationHandler()],
    )

    result = schema.execute_sync(
        """
        mutation {
            create(value: "abc") {
                ... on Success {
                    value
                }
                ... on ValidationErrorPayload {
                    message
                }
            }
        }
        """
    )

    assert result.errors is None
    assert result.data == {"create": {"message": "invalid value: abc"}}


def test_exception_handler_does_not_convert_field_extension_error():
    class FailingExtension(FieldExtension):
        def resolve(self, next_, source, info, **kwargs):  # noqa: ANN003
            raise CustomValidationError("extension failed")

    @strawberry.type
    class Mutation:
        @strawberry.mutation(extensions=[FailingExtension()])
        def create(self, value: str) -> Success | ValidationErrorPayload:
            return Success(value=value)

    schema = strawberry.Schema(
        query=Query,
        mutation=Mutation,
        exception_handlers=[CustomValidationHandler()],
    )

    result = schema.execute_sync(
        """
        mutation {
            create(value: "abc") {
                ... on Success {
                    value
                }
                ... on ValidationErrorPayload {
                    message
                }
            }
        }
        """
    )

    assert result.errors is not None
    assert result.errors[0].message == "extension failed"
    assert result.data is None


def test_exception_handler_converts_exception_that_blocks_attribute_assignment():
    # Some exception types (frozen dataclasses, C-extension types such as
    # pydantic's ValidationError) do not allow setting arbitrary attributes, so
    # the conversion must not depend on mutating the raised exception.
    @dataclasses.dataclass(frozen=True)
    class FrozenValidationError(Exception):
        detail: str = "frozen"

    class FrozenValidationHandler(strawberry.ExceptionHandler):
        exception_type = FrozenValidationError
        error_type = ValidationErrorPayload

        def handle(
            self,
            exception: Exception,
            *,
            field: StrawberryField,
            info: Info,
        ) -> ValidationErrorPayload:
            return ValidationErrorPayload(message=str(exception))

    @strawberry.type
    class Mutation:
        @strawberry.mutation
        def create(self, value: str) -> Success | ValidationErrorPayload:
            raise FrozenValidationError(value)

    schema = strawberry.Schema(
        query=Query,
        mutation=Mutation,
        exception_handlers=[FrozenValidationHandler()],
    )

    result = schema.execute_sync(
        """
        mutation {
            create(value: "abc") {
                ... on Success {
                    value
                }
                ... on ValidationErrorPayload {
                    message
                }
            }
        }
        """
    )

    assert result.errors is None
    assert result.data == {"create": {"message": "abc"}}


def test_exception_handler_matches_reimported_error_type_definition():
    OriginalReloadedError = strawberry.type(
        type(
            "ReloadedError",
            (),
            {"__module__": __name__, "__annotations__": {"message": str}},
        )
    )
    ReimportedReloadedError = strawberry.type(
        type(
            "ReloadedError",
            (),
            {"__module__": __name__, "__annotations__": {"message": str}},
        )
    )

    class ReimportedValidationHandler(CustomValidationHandler):
        error_type = ReimportedReloadedError

        def handle(
            self,
            exception: Exception,
            *,
            field: StrawberryField,
            info: Info,
        ):
            return OriginalReloadedError(message=str(exception))

    @strawberry.type
    class Mutation:
        @strawberry.mutation
        def create(self, value: str) -> Success | OriginalReloadedError:
            raise CustomValidationError(f"invalid value: {value}")

    schema = strawberry.Schema(
        query=Query,
        mutation=Mutation,
        exception_handlers=[ReimportedValidationHandler()],
    )

    result = schema.execute_sync(
        """
        mutation {
            create(value: "abc") {
                ... on Success {
                    value
                }
                ... on ReloadedError {
                    message
                }
            }
        }
        """
    )

    assert result.errors is None
    assert result.data == {"create": {"message": "invalid value: abc"}}


def test_permissions_run_before_argument_conversion_error_is_mapped():
    seen_kwargs = {}

    class Deny(BasePermission):
        message = "denied"

        def has_permission(self, source, info, **kwargs):  # noqa: ANN003
            seen_kwargs.update(kwargs)
            return False

    @strawberry.type
    class Mutation:
        @strawberry.mutation(permission_classes=[Deny])
        def create(self, input: CustomInput) -> Success | ValidationErrorPayload:
            return Success(value=input.value)

    schema = strawberry.Schema(
        query=Query,
        mutation=Mutation,
        exception_handlers=[CustomValidationHandler()],
    )

    result = schema.execute_sync(
        """
        mutation {
            create(input: { value: "a" }) {
                ... on Success {
                    value
                }
                ... on ValidationErrorPayload {
                    message
                }
            }
        }
        """
    )

    assert result.errors is not None
    assert result.errors[0].message == "denied"
    assert result.data is None
    assert seen_kwargs == {"input": {"value": "a"}}


@pytest.mark.asyncio
async def test_exception_handler_converts_async_resolver_error_to_union_type():
    @strawberry.type
    class Mutation:
        @strawberry.mutation
        async def create(self, value: str) -> Success | ValidationErrorPayload:
            raise CustomValidationError(f"invalid value: {value}")

    schema = strawberry.Schema(
        query=Query,
        mutation=Mutation,
        exception_handlers=[CustomValidationHandler()],
    )

    result = await schema.execute(
        """
        mutation {
            create(value: "abc") {
                ... on Success {
                    value
                }
                ... on ValidationErrorPayload {
                    message
                }
            }
        }
        """
    )

    assert result.errors is None
    assert result.data == {"create": {"message": "invalid value: abc"}}


@pytest.mark.asyncio
async def test_exception_handler_converts_async_argument_conversion_error():
    @strawberry.type
    class Mutation:
        @strawberry.mutation
        async def create(self, input: CustomInput) -> Success | ValidationErrorPayload:
            return Success(value=input.value)

    schema = strawberry.Schema(
        query=Query,
        mutation=Mutation,
        exception_handlers=[CustomValidationHandler()],
    )

    result = await schema.execute(
        """
        mutation {
            create(input: { value: "a" }) {
                ... on Success {
                    value
                }
                ... on ValidationErrorPayload {
                    message
                }
            }
        }
        """
    )

    assert result.errors is None
    assert result.data == {"create": {"message": "value is too short"}}


@pytest.mark.asyncio
async def test_exception_handler_does_not_handle_subscription_setup_error():
    @strawberry.type
    class Subscription:
        @strawberry.subscription
        async def create(
            self, input: CustomInput
        ) -> AsyncGenerator[Success | ValidationErrorPayload, None]:
            yield Success(value=input.value)

    schema = strawberry.Schema(
        query=Query,
        subscription=Subscription,
        exception_handlers=[CustomValidationHandler()],
    )

    result_source = await schema.subscribe(
        """
        subscription {
            create(input: { value: "a" }) {
                ... on Success {
                    value
                }
                ... on ValidationErrorPayload {
                    message
                }
            }
        }
        """
    )

    async with aclosing(result_source) as subscription_result:
        result = await subscription_result.__anext__()

    assert isinstance(result, PreExecutionError)
    assert result.errors[0].message == "value is too short"
    assert result.data is None


def test_federation_schema_passes_exception_handlers_to_resolvers():
    @strawberry.type
    class Mutation:
        @strawberry.mutation
        def create(self, input: CustomInput) -> Success | ValidationErrorPayload:
            return Success(value=input.value)

    schema = strawberry.federation.Schema(
        query=Query,
        mutation=Mutation,
        exception_handlers=[CustomValidationHandler()],
    )

    result = schema.execute_sync(
        """
        mutation {
            create(input: { value: "a" }) {
                ... on Success {
                    value
                }
                ... on ValidationErrorPayload {
                    message
                }
            }
        }
        """
    )

    assert result.errors is None
    assert result.data == {"create": {"message": "value is too short"}}


@pytest.mark.asyncio
async def test_exception_handler_converts_conversion_error_with_async_extension():
    # An async field extension `await`s the inner result, so the handled payload
    # produced on the conversion-error path must be awaitable too.
    class Allow(BasePermission):
        message = "denied"

        async def has_permission(self, source, info, **kwargs) -> bool:  # noqa: ANN003
            return True

    @strawberry.type
    class Mutation:
        @strawberry.mutation(permission_classes=[Allow])
        async def create(self, input: CustomInput) -> Success | ValidationErrorPayload:
            return Success(value=input.value)

    schema = strawberry.Schema(
        query=Query,
        mutation=Mutation,
        exception_handlers=[CustomValidationHandler()],
    )

    result = await schema.execute(
        """
        mutation {
            create(input: { value: "a" }) {
                ... on Success {
                    value
                }
                ... on ValidationErrorPayload {
                    message
                }
            }
        }
        """
    )

    assert result.errors is None
    assert result.data == {"create": {"message": "value is too short"}}


def test_exception_handler_converts_conversion_error_with_input_mutation_extension():
    # `InputMutationExtension` calls `vars(input)` on the arguments; the raw
    # values passed on the conversion-error path must not crash it before the
    # handler runs.
    @strawberry.type
    class Mutation:
        @strawberry.mutation(extensions=[InputMutationExtension()])
        def create(self, data: CustomInput) -> Success | ValidationErrorPayload:
            return Success(value=data.value)

    schema = strawberry.Schema(
        query=Query,
        mutation=Mutation,
        exception_handlers=[CustomValidationHandler()],
    )

    result = schema.execute_sync(
        """
        mutation {
            create(input: { data: { value: "a" } }) {
                ... on Success {
                    value
                }
                ... on ValidationErrorPayload {
                    message
                }
            }
        }
        """
    )

    assert result.errors is None
    assert result.data == {"create": {"message": "value is too short"}}


def test_exception_handler_matches_concrete_generic_error_type_in_union():
    @strawberry.type
    class GenericError(Generic[T]):
        message: str
        value: T

    class GenericHandler(strawberry.ExceptionHandler):
        exception_type = CustomValidationError
        error_type = GenericError[int]

        def handle(self, exception, *, field, info) -> "GenericError[int]":
            return GenericError[int](message=str(exception), value=0)

    @strawberry.type
    class Mutation:
        @strawberry.mutation
        def create(self) -> Success | GenericError[int]:
            raise CustomValidationError("boom")

    schema = strawberry.Schema(
        query=Query,
        mutation=Mutation,
        exception_handlers=[GenericHandler()],
    )

    result = schema.execute_sync(
        """
        mutation {
            create {
                ... on Success {
                    value
                }
                ... on IntGenericError {
                    message
                    intValue: value
                }
            }
        }
        """
    )

    assert result.errors is None
    assert result.data == {"create": {"message": "boom", "intValue": 0}}


def test_exception_handler_converts_basic_field_error_to_union_type():
    # A "basic" field (a plain attribute with no resolver) whose return type is
    # a union should still have its errors converted; whether an unrelated
    # extension is attached must not change this.
    @strawberry.type
    class Query:
        ok: bool = True
        result: Success | ValidationErrorPayload

    class Root:
        ok = True

        @property
        def result(self) -> None:
            raise CustomValidationError("basic field boom")

    schema = strawberry.Schema(
        query=Query,
        exception_handlers=[CustomValidationHandler()],
    )

    result = schema.execute_sync(
        """
        {
            result {
                ... on Success {
                    value
                }
                ... on ValidationErrorPayload {
                    message
                }
            }
        }
        """,
        root_value=Root(),
    )

    assert result.errors is None
    assert result.data == {"result": {"message": "basic field boom"}}


def test_exception_handler_protocol_is_runtime_checkable():
    assert isinstance(CustomValidationHandler(), strawberry.ExceptionHandler)


@pytest.mark.parametrize(
    "handler",
    [
        pytest.param(CustomValidationHandler, id="class-not-instance"),
        pytest.param(
            type(
                "MissingExceptionType",
                (strawberry.ExceptionHandler,),
                {
                    "error_type": ValidationErrorPayload,
                    "handle": lambda self, exception, *, field, info: None,
                },
            )(),
            id="missing-exception-type",
        ),
        pytest.param(
            type(
                "StringExceptionType",
                (strawberry.ExceptionHandler,),
                {
                    "exception_type": "CustomValidationError",
                    "error_type": ValidationErrorPayload,
                    "handle": lambda self, exception, *, field, info: None,
                },
            )(),
            id="string-exception-type",
        ),
        pytest.param(
            type(
                "MissingErrorType",
                (strawberry.ExceptionHandler,),
                {
                    "exception_type": CustomValidationError,
                    "handle": lambda self, exception, *, field, info: None,
                },
            )(),
            id="missing-error-type",
        ),
        pytest.param(
            type(
                "MistypedHandle",
                (strawberry.ExceptionHandler,),
                {
                    "exception_type": CustomValidationError,
                    "error_type": ValidationErrorPayload,
                    "handel": lambda self, exception, *, field, info: None,
                },
            )(),
            id="mistyped-handle",
        ),
    ],
)
def test_schema_rejects_malformed_exception_handlers(handler):
    with pytest.raises(TypeError):
        strawberry.Schema(query=Query, exception_handlers=[handler])


def test_federation_schema_exception_handlers_come_after_federation_version():
    # `exception_handlers` must not sit before `federation_version` in the
    # signature, or a positional `federation_version` would land in it.
    parameters = list(
        inspect.signature(strawberry.federation.Schema.__init__).parameters
    )

    assert parameters.index("exception_handlers") > parameters.index(
        "federation_version"
    )
