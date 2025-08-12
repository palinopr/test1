"""
Go High Level API integration tools for LangGraph agents.

This module provides comprehensive GHL API wrapper functions for customer qualification
workflows, including messaging, contact management, tagging, and notes functionality.
"""

import os
import json
from typing import Dict, Any, List, Optional, Union
from datetime import datetime
import asyncio

import httpx
import structlog
from pydantic import BaseModel, Field
from langchain_core.tools import BaseTool

logger = structlog.get_logger(__name__)


class GHLConfig:
    """Go High Level API configuration."""

    def __init__(self):
        self.api_key = os.getenv("GHL_API_KEY")
        self.base_url = os.getenv(
            "GHL_BASE_URL", "https://services.leadconnectorhq.com"
        )
        self.timeout = 30

        if not self.api_key:
            logger.warning("GHL_API_KEY not found in environment variables")

    @property
    def headers(self) -> Dict[str, str]:
        """Get headers for GHL API requests."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }


class GHLResponse(BaseModel):
    """Standard response model for GHL API operations."""

    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    status_code: Optional[int] = None


class GHLAPIClient:
    """Async HTTP client for Go High Level API operations."""

    def __init__(self, config: GHLConfig):
        self.config = config
        self.client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        self.client = httpx.AsyncClient(
            base_url=self.config.base_url,
            headers=self.config.headers,
            timeout=self.config.timeout,
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.client:
            await self.client.aclose()

    async def request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> GHLResponse:
        """Make an authenticated request to the GHL API."""
        if not self.client:
            return GHLResponse(success=False, error="HTTP client not initialized")

        if not self.config.api_key:
            return GHLResponse(success=False, error="GHL API key not configured")

        try:
            logger.info(
                "Making GHL API request",
                method=method,
                endpoint=endpoint,
                has_data=bool(data),
            )

            response = await self.client.request(
                method=method, url=endpoint, json=data, params=params
            )

            # Handle different response scenarios
            if response.status_code == 200:
                try:
                    response_data = response.json()
                    return GHLResponse(
                        success=True,
                        data=response_data,
                        status_code=response.status_code,
                    )
                except json.JSONDecodeError:
                    return GHLResponse(
                        success=True,
                        data={"message": response.text},
                        status_code=response.status_code,
                    )

            elif response.status_code == 201:
                # Created successfully
                try:
                    response_data = response.json()
                    return GHLResponse(
                        success=True,
                        data=response_data,
                        status_code=response.status_code,
                    )
                except json.JSONDecodeError:
                    return GHLResponse(
                        success=True,
                        data={"message": "Resource created successfully"},
                        status_code=response.status_code,
                    )

            elif response.status_code == 401:
                return GHLResponse(
                    success=False,
                    error="Unauthorized - check GHL API key",
                    status_code=response.status_code,
                )

            elif response.status_code == 403:
                return GHLResponse(
                    success=False,
                    error="Forbidden - insufficient permissions",
                    status_code=response.status_code,
                )

            elif response.status_code == 404:
                return GHLResponse(
                    success=False,
                    error="Resource not found",
                    status_code=response.status_code,
                )

            elif response.status_code == 429:
                return GHLResponse(
                    success=False,
                    error="Rate limit exceeded - please retry later",
                    status_code=response.status_code,
                )

            else:
                # Other error codes
                try:
                    error_data = response.json()
                    error_message = error_data.get(
                        "message", f"HTTP {response.status_code}"
                    )
                except:
                    error_message = f"HTTP {response.status_code}: {response.text}"

                return GHLResponse(
                    success=False, error=error_message, status_code=response.status_code
                )

        except httpx.TimeoutException:
            return GHLResponse(
                success=False, error="Request timeout - GHL API may be slow"
            )

        except httpx.ConnectError:
            return GHLResponse(
                success=False, error="Connection error - check internet connectivity"
            )

        except Exception as e:
            logger.error("Unexpected error in GHL API request", error=str(e))
            return GHLResponse(success=False, error=f"Unexpected error: {str(e)}")


# Global GHL configuration
ghl_config = GHLConfig()


class SendMessageTool(BaseTool):
    """Tool to send messages to contacts via GHL."""

    name: str = "send_message"
    description: str = """
    Send a message to a contact in Go High Level.
    Use this tool to respond to customers, ask questions, or provide information.
    
    Args:
        contact_id: The GHL contact ID to send the message to
        message: The message content to send
        message_type: Type of message ('SMS', 'Email', or 'WhatsApp')
    """

    def _run(self, contact_id: str, message: str, message_type: str = "SMS") -> str:
        """Send message synchronously."""
        return asyncio.run(self._arun(contact_id, message, message_type))

    async def _arun(
        self, contact_id: str, message: str, message_type: str = "SMS"
    ) -> str:
        """Send a message to a contact."""
        async with GHLAPIClient(ghl_config) as client:
            # Prepare message data based on type
            if message_type.upper() == "SMS":
                endpoint = f"/conversations/messages"
                data = {"type": "SMS", "contactId": contact_id, "message": message}
            elif message_type.upper() == "EMAIL":
                endpoint = f"/conversations/messages"
                data = {
                    "type": "Email",
                    "contactId": contact_id,
                    "subject": "Response from Automation Team",
                    "message": message,
                }
            elif message_type.upper() == "WHATSAPP":
                endpoint = f"/conversations/messages"
                data = {"type": "WhatsApp", "contactId": contact_id, "message": message}
            else:
                return json.dumps(
                    {
                        "success": False,
                        "error": f"Unsupported message type: {message_type}",
                    }
                )

            response = await client.request("POST", endpoint, data=data)

            if response.success:
                logger.info(
                    "Message sent successfully",
                    contact_id=contact_id,
                    message_type=message_type,
                )
                return json.dumps(
                    {
                        "success": True,
                        "message": f"{message_type} message sent successfully",
                        "data": response.data,
                    }
                )
            else:
                logger.error(
                    "Failed to send message",
                    contact_id=contact_id,
                    error=response.error,
                )
                return json.dumps({"success": False, "error": response.error})


class AddContactTagTool(BaseTool):
    """Tool to add tags to contacts in GHL."""

    name: str = "add_contact_tag"
    description: str = """
    Add a tag to a contact in Go High Level.
    Use this tool to categorize contacts, mark qualification status, or track customer journey.
    
    Args:
        contact_id: The GHL contact ID to tag
        tag: The tag to add (e.g., 'qualified', 'interested', 'automation-prospect')
    """

    def _run(self, contact_id: str, tag: str) -> str:
        """Add tag synchronously."""
        return asyncio.run(self._arun(contact_id, tag))

    async def _arun(self, contact_id: str, tag: str) -> str:
        """Add a tag to a contact."""
        async with GHLAPIClient(ghl_config) as client:
            endpoint = f"/contacts/{contact_id}/tags"
            data = {"tags": [tag]}

            response = await client.request("POST", endpoint, data=data)

            if response.success:
                logger.info("Tag added successfully", contact_id=contact_id, tag=tag)
                return json.dumps(
                    {
                        "success": True,
                        "message": f"Tag '{tag}' added successfully",
                        "data": response.data,
                    }
                )
            else:
                logger.error(
                    "Failed to add tag", contact_id=contact_id, error=response.error
                )
                return json.dumps({"success": False, "error": response.error})


class CreateContactNoteTool(BaseTool):
    """Tool to create notes for contacts in GHL."""

    name: str = "create_contact_note"
    description: str = """
    Create a note for a contact in Go High Level.
    Use this tool to record important information, conversation summaries, or qualification details.
    
    Args:
        contact_id: The GHL contact ID to add the note to
        note: The note content
        note_type: Type of note (optional, defaults to 'general')
    """

    def _run(self, contact_id: str, note: str, note_type: str = "general") -> str:
        """Create note synchronously."""
        return asyncio.run(self._arun(contact_id, note, note_type))

    async def _arun(
        self, contact_id: str, note: str, note_type: str = "general"
    ) -> str:
        """Create a note for a contact."""
        async with GHLAPIClient(ghl_config) as client:
            endpoint = f"/contacts/{contact_id}/notes"
            data = {
                "body": note,
                "userId": "system",  # Can be configured based on needs
                "dateAdded": datetime.utcnow().isoformat() + "Z",
            }

            response = await client.request("POST", endpoint, data=data)

            if response.success:
                logger.info("Note created successfully", contact_id=contact_id)
                return json.dumps(
                    {
                        "success": True,
                        "message": "Note created successfully",
                        "data": response.data,
                    }
                )
            else:
                logger.error(
                    "Failed to create note", contact_id=contact_id, error=response.error
                )
                return json.dumps({"success": False, "error": response.error})


class UpdateContactTool(BaseTool):
    """Tool to update contact information in GHL."""

    name: str = "update_contact"
    description: str = """
    Update contact information in Go High Level.
    Use this tool to update customer details, qualification status, or custom fields.
    
    Args:
        contact_id: The GHL contact ID to update
        updates: Dictionary of fields to update (e.g., {"firstName": "John", "customField": "value"})
    """

    def _run(self, contact_id: str, updates: Union[str, Dict[str, Any]]) -> str:
        """Update contact synchronously."""
        return asyncio.run(self._arun(contact_id, updates))

    async def _arun(self, contact_id: str, updates: Union[str, Dict[str, Any]]) -> str:
        """Update contact information."""
        # Handle string input (JSON string)
        if isinstance(updates, str):
            try:
                updates = json.loads(updates)
            except json.JSONDecodeError:
                return json.dumps(
                    {"success": False, "error": "Invalid JSON format for updates"}
                )

        async with GHLAPIClient(ghl_config) as client:
            endpoint = f"/contacts/{contact_id}"

            response = await client.request("PUT", endpoint, data=updates)

            if response.success:
                logger.info("Contact updated successfully", contact_id=contact_id)
                return json.dumps(
                    {
                        "success": True,
                        "message": "Contact updated successfully",
                        "data": response.data,
                    }
                )
            else:
                logger.error(
                    "Failed to update contact",
                    contact_id=contact_id,
                    error=response.error,
                )
                return json.dumps({"success": False, "error": response.error})


class GetContactDetailsTool(BaseTool):
    """Tool to get contact details from GHL."""

    name: str = "get_contact_details"
    description: str = """
    Get detailed information about a contact from Go High Level.
    Use this tool to retrieve customer information for personalization and context.
    
    Args:
        contact_id: The GHL contact ID to retrieve details for
    """

    def _run(self, contact_id: str) -> str:
        """Get contact details synchronously."""
        return asyncio.run(self._arun(contact_id))

    async def _arun(self, contact_id: str) -> str:
        """Get contact details."""
        async with GHLAPIClient(ghl_config) as client:
            endpoint = f"/contacts/{contact_id}"

            response = await client.request("GET", endpoint)

            if response.success:
                logger.info(
                    "Contact details retrieved successfully", contact_id=contact_id
                )

                # Extract key information for the agent
                contact_data = response.data.get("contact", {}) if response.data else {}

                # Create a structured summary for the agent
                summary = {
                    "success": True,
                    "contact_info": {
                        "id": contact_data.get("id"),
                        "firstName": contact_data.get("firstName"),
                        "lastName": contact_data.get("lastName"),
                        "email": contact_data.get("email"),
                        "phone": contact_data.get("phone"),
                        "tags": contact_data.get("tags", []),
                        "customFields": contact_data.get("customFields", {}),
                        "source": contact_data.get("source"),
                        "dateAdded": contact_data.get("dateAdded"),
                    },
                    "full_data": response.data,
                }

                return json.dumps(summary)
            else:
                logger.error(
                    "Failed to get contact details",
                    contact_id=contact_id,
                    error=response.error,
                )
                return json.dumps({"success": False, "error": response.error})


class SearchContactsTool(BaseTool):
    """Tool to search for contacts in GHL."""

    name: str = "search_contacts"
    description: str = """
    Search for contacts in Go High Level by email, phone, or name.
    Use this tool to find existing contacts before creating new ones.
    
    Args:
        query: Search query (email, phone, or name)
        search_type: Type of search ('email', 'phone', or 'name')
    """

    def _run(self, query: str, search_type: str = "email") -> str:
        """Search contacts synchronously."""
        return asyncio.run(self._arun(query, search_type))

    async def _arun(self, query: str, search_type: str = "email") -> str:
        """Search for contacts."""
        async with GHLAPIClient(ghl_config) as client:
            endpoint = "/contacts/search"
            params = {"query": query, "type": search_type}

            response = await client.request("GET", endpoint, params=params)

            if response.success:
                contacts = response.data.get("contacts", []) if response.data else []
                logger.info(
                    "Contact search completed", query=query, results_count=len(contacts)
                )

                return json.dumps(
                    {"success": True, "contacts": contacts, "count": len(contacts)}
                )
            else:
                logger.error(
                    "Failed to search contacts", query=query, error=response.error
                )
                return json.dumps({"success": False, "error": response.error})


# Tool instances for LangGraph integration
ghl_tools = [
    SendMessageTool(),
    AddContactTagTool(),
    CreateContactNoteTool(),
    UpdateContactTool(),
    GetContactDetailsTool(),
    SearchContactsTool(),
]


def get_ghl_tools() -> List[BaseTool]:
    """Get all GHL tools for LangGraph agent integration."""
    return ghl_tools


def create_wow_moment_context(contact_data: Dict[str, Any]) -> str:
    """
    Create context for 'wow moments' based on contact information.

    Args:
        contact_data: Contact information from GHL

    Returns:
        str: Formatted context for personalized responses
    """
    context_parts = []

    # Personal information
    first_name = contact_data.get("firstName", "")
    if first_name:
        context_parts.append(f"Customer's name is {first_name}")

    # Source information
    source = contact_data.get("source", "")
    if source:
        context_parts.append(f"They came from {source}")

    # Tags for qualification status
    tags = contact_data.get("tags", [])
    if tags:
        context_parts.append(f"Current tags: {', '.join(tags)}")

    # Custom fields for business information
    custom_fields = contact_data.get("customFields", {})
    business_info = []
    for field_name, field_value in custom_fields.items():
        if field_value and "business" in field_name.lower():
            business_info.append(f"{field_name}: {field_value}")

    if business_info:
        context_parts.append(f"Business info: {'; '.join(business_info)}")

    # Date added for timing context
    date_added = contact_data.get("dateAdded")
    if date_added:
        context_parts.append(f"Contact added: {date_added}")

    return (
        " | ".join(context_parts)
        if context_parts
        else "No additional context available"
    )


async def test_ghl_connection() -> Dict[str, Any]:
    """Test GHL API connection and return status."""
    async with GHLAPIClient(ghl_config) as client:
        # Try a simple API call to test connection
        response = await client.request("GET", "/contacts", params={"limit": 1})

        return {
            "connected": response.success,
            "error": response.error if not response.success else None,
            "status_code": response.status_code,
            "has_api_key": bool(ghl_config.api_key),
        }
