"""
Custom exception classes for GHL Customer Qualification Webhook.

This module provides standardized exception classes for different error types
to improve error handling consistency and debugging across the application.
"""


class GHLQualificationError(Exception):
    """Base exception class for all GHL qualification webhook errors."""

    def __init__(self, message: str, context: dict = None):
        self.message = message
        self.context = context or {}
        super().__init__(self.message)

    def __str__(self):
        if self.context:
            context_str = ", ".join(f"{k}={v}" for k, v in self.context.items())
            return f"{self.message} (Context: {context_str})"
        return self.message


class GHLAPIError(GHLQualificationError):
    """Exception raised for Go High Level API related errors."""

    def __init__(
        self,
        message: str,
        status_code: int = None,
        response_data: dict = None,
        contact_id: str = None,
        api_endpoint: str = None,
    ):
        context = {}
        if status_code:
            context["status_code"] = status_code
        if contact_id:
            context["contact_id"] = contact_id
        if api_endpoint:
            context["api_endpoint"] = api_endpoint
        if response_data:
            context["response_data"] = str(response_data)

        super().__init__(message, context)
        self.status_code = status_code
        self.response_data = response_data
        self.contact_id = contact_id
        self.api_endpoint = api_endpoint


class QualificationError(GHLQualificationError):
    """Exception raised for customer qualification process errors."""

    def __init__(
        self,
        message: str,
        contact_id: str = None,
        thread_id: str = None,
        conversation_stage: str = None,
        qualification_data: dict = None,
    ):
        context = {}
        if contact_id:
            context["contact_id"] = contact_id
        if thread_id:
            context["thread_id"] = thread_id
        if conversation_stage:
            context["conversation_stage"] = conversation_stage
        if qualification_data:
            context["qualification_data"] = str(qualification_data)

        super().__init__(message, context)
        self.contact_id = contact_id
        self.thread_id = thread_id
        self.conversation_stage = conversation_stage
        self.qualification_data = qualification_data


class WebhookError(GHLQualificationError):
    """Exception raised for webhook processing errors."""

    def __init__(
        self,
        message: str,
        webhook_type: str = None,
        payload_data: dict = None,
        contact_id: str = None,
        lead_id: str = None,
    ):
        context = {}
        if webhook_type:
            context["webhook_type"] = webhook_type
        if contact_id:
            context["contact_id"] = contact_id
        if lead_id:
            context["lead_id"] = lead_id
        if payload_data:
            # Only include essential payload info to avoid logging sensitive data
            context["payload_size"] = len(str(payload_data))

        super().__init__(message, context)
        self.webhook_type = webhook_type
        self.payload_data = payload_data
        self.contact_id = contact_id
        self.lead_id = lead_id


class ConfigurationError(GHLQualificationError):
    """Exception raised for configuration and environment setup errors."""

    def __init__(
        self,
        message: str,
        config_key: str = None,
        config_value: str = None,
        required_keys: list = None,
    ):
        context = {}
        if config_key:
            context["config_key"] = config_key
        if config_value:
            # Mask sensitive values
            if any(
                sensitive in config_key.lower()
                for sensitive in ["key", "secret", "token", "password"]
            ):
                context["config_value"] = "***MASKED***"
            else:
                context["config_value"] = config_value
        if required_keys:
            context["required_keys"] = ", ".join(required_keys)

        super().__init__(message, context)
        self.config_key = config_key
        self.config_value = config_value
        self.required_keys = required_keys


class DatabaseError(GHLQualificationError):
    """Exception raised for database operation errors."""

    def __init__(
        self,
        message: str,
        operation: str = None,
        table_name: str = None,
        record_id: str = None,
    ):
        context = {}
        if operation:
            context["operation"] = operation
        if table_name:
            context["table_name"] = table_name
        if record_id:
            context["record_id"] = record_id

        super().__init__(message, context)
        self.operation = operation
        self.table_name = table_name
        self.record_id = record_id


class LangGraphError(GHLQualificationError):
    """Exception raised for LangGraph workflow errors."""

    def __init__(
        self,
        message: str,
        workflow_state: str = None,
        node_name: str = None,
        thread_id: str = None,
    ):
        context = {}
        if workflow_state:
            context["workflow_state"] = workflow_state
        if node_name:
            context["node_name"] = node_name
        if thread_id:
            context["thread_id"] = thread_id

        super().__init__(message, context)
        self.workflow_state = workflow_state
        self.node_name = node_name
        self.thread_id = thread_id
