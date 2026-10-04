"""Chord remote-service wire contracts and error types."""

from .errors import REMOTE_SERVICE_ERROR_CODES, RemoteServiceError, is_remote_service_error_code
from .wire import (
    create_service_catalogue_call,
    create_service_subscribe_call,
    create_service_unsubscribe_call,
    decode_service_control_call,
    parse_service_call,
    parse_service_catalogue,
    parse_service_provider_update,
    parse_service_subscription_snapshot,
    parse_wire_service_provider_update,
    parse_wire_service_subscription_snapshot,
)
from .state_codec import create_service_state_decoder, create_service_state_encoder
from .provider import RemoteServiceProvider, Service, create_loopback_service_transport, define_service
from .consumer import RemoteServiceBinding, create_remote_service_binding

__all__ = [
    "REMOTE_SERVICE_ERROR_CODES",
    "RemoteServiceError",
    "RemoteServiceProvider",
    "RemoteServiceBinding",
    "Service",
    "create_service_catalogue_call",
    "create_service_subscribe_call",
    "create_service_unsubscribe_call",
    "create_loopback_service_transport",
    "create_remote_service_binding",
    "create_service_state_decoder",
    "create_service_state_encoder",
    "decode_service_control_call",
    "define_service",
    "is_remote_service_error_code",
    "parse_service_call",
    "parse_service_catalogue",
    "parse_service_provider_update",
    "parse_service_subscription_snapshot",
    "parse_wire_service_provider_update",
    "parse_wire_service_subscription_snapshot",
]
