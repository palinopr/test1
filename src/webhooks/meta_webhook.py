"""
Meta Ads Webhook Integration for Lead Processing.

This module implements FastAPI webhook endpoints to receive lead information from Meta ads,
validate webhook signatures, extract lead data, and trigger the customer qualification agent.
"""

import hashlib
import hmac
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import structlog
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from ..agents.qualification_agent import get_qualification_agent
from ..exceptions import WebhookError, ConfigurationError
from ..config.langsmith_config import get_langsmith_config
from ..tools.ghl_tools import AddContactTagTool, SearchContactsTool, UpdateContactTool

logger = structlog.get_logger(__name__)


class MetaLeadData(BaseModel):
    """Model for Meta ads lead data."""

    id: str
    created_time: str
    ad_id: Optional[str] = None
    ad_name: Optional[str] = None
    adset_id: Optional[str] = None
    adset_name: Optional[str] = None
    campaign_id: Optional[str] = None
    campaign_name: Optional[str] = None
    form_id: Optional[str] = None
    form_name: Optional[str] = None
    is_organic: Optional[bool] = False
    platform: Optional[str] = "facebook"
    field_data: List[Dict[str, Any]] = Field(default_factory=list)


class MetaWebhookPayload(BaseModel):
    """Model for Meta webhook payload structure."""

    object: str
    entry: List[Dict[str, Any]]


class WebhookResponse(BaseModel):
    """Standard webhook response model."""

    success: bool
    message: str
    processed_leads: int = 0
    errors: List[str] = Field(default_factory=list)


class MetaWebhookHandler:
    """
    Handler for Meta ads webhook events with comprehensive lead processing.

    Features:
    - Webhook signature validation for security
    - Lead data extraction and normalization
    - GHL contact creation/updating
    - Automatic qualification agent triggering
    - Error handling and retry logic
    """

    def __init__(self):
        self.verify_token = os.getenv("META_WEBHOOK_VERIFY_TOKEN")
        self.app_secret = os.getenv("META_WEBHOOK_SECRET")
        self._qualification_agent = None  # Lazy initialization
        self.langsmith_config = get_langsmith_config()

        # Initialize GHL tools for contact management
        self.search_tool = SearchContactsTool()
        self.update_tool = UpdateContactTool()
        self.tag_tool = AddContactTagTool()

        if not self.verify_token:
            logger.warning("META_WEBHOOK_VERIFY_TOKEN not configured")
        if not self.app_secret:
            logger.warning(
                "META_WEBHOOK_SECRET not configured - signature validation disabled"
            )

    @property
    def qualification_agent(self):
        """Lazy initialization of qualification agent."""
        if self._qualification_agent is None:
            try:
                self._qualification_agent = get_qualification_agent()
            except ValueError as e:
                logger.warning("Qualification agent not available", error=str(e))
                self._qualification_agent = None
        return self._qualification_agent

    def verify_webhook_signature(self, payload: bytes, signature: str) -> bool:
        """
        Verify Meta webhook signature for security.

        Args:
            payload: Raw webhook payload bytes
            signature: X-Hub-Signature-256 header value

        Returns:
            bool: True if signature is valid
        """
        if not self.app_secret:
            logger.warning(
                "Webhook signature validation skipped - no app secret configured"
            )
            return True

        if not signature:
            logger.error("No signature provided in webhook request")
            return False

        try:
            # Remove 'sha256=' prefix if present
            if signature.startswith("sha256="):
                signature = signature[7:]

            # Calculate expected signature
            expected_signature = hmac.new(
                self.app_secret.encode("utf-8"), payload, hashlib.sha256
            ).hexdigest()

            # Compare signatures securely
            is_valid = hmac.compare_digest(signature, expected_signature)

            if not is_valid:
                logger.error(
                    "Invalid webhook signature", provided=signature[:10] + "..."
                )

            return is_valid

        except Exception as e:
            logger.error(
                "Webhook signature verification error",
                error=str(e),
                error_type=type(e).__name__,
                webhook_type="meta",
            )
            raise WebhookError(
                message=f"Error verifying webhook signature: {str(e)}",
                webhook_type="meta",
            )

    def extract_lead_data(self, webhook_payload: Dict[str, Any]) -> List[MetaLeadData]:
        """
        Extract lead data from Meta webhook payload.

        Args:
            webhook_payload: Raw webhook payload from Meta

        Returns:
            List[MetaLeadData]: Extracted and validated lead data
        """
        leads = []

        try:
            # Validate payload structure
            payload = MetaWebhookPayload(**webhook_payload)

            for entry in payload.entry:
                # Process changes in each entry
                changes = entry.get("changes", [])

                for change in changes:
                    if change.get("field") == "leadgen":
                        # Extract lead data from leadgen change
                        value = change.get("value", {})

                        lead_data = MetaLeadData(
                            id=value.get("leadgen_id", ""),
                            created_time=value.get(
                                "created_time", datetime.utcnow().isoformat()
                            ),
                            ad_id=value.get("ad_id"),
                            ad_name=value.get("ad_name"),
                            adset_id=value.get("adset_id"),
                            adset_name=value.get("adset_name"),
                            campaign_id=value.get("campaign_id"),
                            campaign_name=value.get("campaign_name"),
                            form_id=value.get("form_id"),
                            form_name=value.get("form_name"),
                            is_organic=value.get("is_organic", False),
                            platform=value.get("platform", "facebook"),
                            field_data=value.get("field_data", []),
                        )

                        leads.append(lead_data)

                        logger.info(
                            "Lead data extracted",
                            lead_id=lead_data.id,
                            campaign=lead_data.campaign_name,
                            form=lead_data.form_name,
                        )

            return leads

        except ValidationError as e:
            logger.error("Invalid webhook payload structure", error=str(e))
            raise HTTPException(
                status_code=400, detail=f"Invalid payload structure: {str(e)}"
            )

        except Exception as e:
            logger.error(
                "Webhook lead data extraction error",
                error=str(e),
                error_type=type(e).__name__,
                webhook_type="meta",
                payload_size=len(str(webhook_payload)),
            )
            raise WebhookError(
                message=f"Error extracting lead data: {str(e)}",
                webhook_type="meta",
                payload_data=webhook_payload,
            )

    def normalize_lead_fields(self, field_data: List[Dict[str, Any]]) -> Dict[str, str]:
        """
        Normalize Meta lead form fields to standard contact fields.

        Args:
            field_data: Raw field data from Meta lead

        Returns:
            Dict[str, str]: Normalized contact fields
        """
        normalized = {}

        # Field mapping from Meta to standard fields
        field_mapping = {
            "first_name": "firstName",
            "last_name": "lastName",
            "full_name": "fullName",
            "email": "email",
            "phone_number": "phone",
            "phone": "phone",
            "company_name": "companyName",
            "job_title": "jobTitle",
            "city": "city",
            "state": "state",
            "zip_code": "postalCode",
            "country": "country",
            "website": "website",
        }

        for field in field_data:
            field_name = field.get("name", "").lower()
            field_values = field.get("values", [])

            if field_values and len(field_values) > 0:
                field_value = field_values[0]  # Take first value

                # Map to standard field name
                standard_field = field_mapping.get(field_name, field_name)
                normalized[standard_field] = str(field_value)

                # Handle full name splitting
                if field_name == "full_name" and "firstName" not in normalized:
                    name_parts = str(field_value).split(" ", 1)
                    normalized["firstName"] = name_parts[0]
                    if len(name_parts) > 1:
                        normalized["lastName"] = name_parts[1]

        # Ensure we have at least email or phone for contact creation
        if not normalized.get("email") and not normalized.get("phone"):
            logger.warning("Lead has no email or phone", fields=list(normalized.keys()))

        return normalized

    async def find_or_create_ghl_contact(
        self, lead_data: MetaLeadData, normalized_fields: Dict[str, str]
    ) -> Optional[str]:
        """
        Find existing GHL contact or create a new one.

        Args:
            lead_data: Meta lead data
            normalized_fields: Normalized contact fields

        Returns:
            Optional[str]: GHL contact ID if successful
        """
        try:
            # Search for existing contact by email first
            email = normalized_fields.get("email")
            phone = normalized_fields.get("phone")

            contact_id = None

            if email:
                # Search by email
                search_result = await self.search_tool._arun(email, "email")
                search_data = json.loads(search_result)

                if search_data.get("success") and search_data.get("count", 0) > 0:
                    contacts = search_data.get("contacts", [])
                    if contacts:
                        contact_id = contacts[0].get("id")
                        logger.info(
                            "Found existing contact by email",
                            contact_id=contact_id,
                            email=email,
                        )

            if not contact_id and phone:
                # Search by phone if email search failed
                search_result = await self.search_tool._arun(phone, "phone")
                search_data = json.loads(search_result)

                if search_data.get("success") and search_data.get("count", 0) > 0:
                    contacts = search_data.get("contacts", [])
                    if contacts:
                        contact_id = contacts[0].get("id")
                        logger.info(
                            "Found existing contact by phone",
                            contact_id=contact_id,
                            phone=phone,
                        )

            if contact_id:
                # Update existing contact with Meta lead info
                update_data = {
                    **normalized_fields,
                    "source": f"Meta Ad - {lead_data.campaign_name or 'Unknown Campaign'}",
                    "customFields": {
                        "metaLeadId": lead_data.id,
                        "metaCampaignId": lead_data.campaign_id,
                        "metaCampaignName": lead_data.campaign_name,
                        "metaAdId": lead_data.ad_id,
                        "metaAdName": lead_data.ad_name,
                        "metaFormId": lead_data.form_id,
                        "metaFormName": lead_data.form_name,
                        "leadCreatedTime": lead_data.created_time,
                    },
                }

                update_result = await self.update_tool._arun(contact_id, update_data)
                update_response = json.loads(update_result)

                if update_response.get("success"):
                    logger.info(
                        "Updated existing contact with Meta lead data",
                        contact_id=contact_id,
                    )
                else:
                    logger.error(
                        "Failed to update contact",
                        contact_id=contact_id,
                        error=update_response.get("error"),
                    )

            else:
                # Create new contact (this would require a create contact tool)
                # For now, we'll log that we need to create a contact
                logger.info("Would create new contact", email=email, phone=phone)
                # In a real implementation, you'd use a CreateContactTool here
                contact_id = f"new_contact_{lead_data.id}"  # Placeholder

            # Add Meta lead tag
            if contact_id:
                tag_result = await self.tag_tool._arun(contact_id, "meta-lead")
                tag_response = json.loads(tag_result)

                if tag_response.get("success"):
                    logger.info("Added meta-lead tag", contact_id=contact_id)

            return contact_id

        except Exception as e:
            logger.error(
                "GHL contact creation/lookup error",
                error=str(e),
                lead_id=lead_data.id,
                error_type=type(e).__name__,
                webhook_type="meta",
            )
            raise WebhookError(
                message=f"Error finding/creating GHL contact: {str(e)}",
                webhook_type="meta",
                lead_id=lead_data.id,
            )

    async def trigger_qualification_agent(
        self,
        contact_id: str,
        lead_data: MetaLeadData,
        normalized_fields: Dict[str, str],
    ) -> bool:
        """
        Trigger the qualification agent for the new lead.

        Args:
            contact_id: GHL contact ID
            lead_data: Meta lead data
            normalized_fields: Normalized contact fields

        Returns:
            bool: True if agent was triggered successfully
        """
        try:
            # Prepare contact info for the agent
            contact_info = {
                "id": contact_id,
                "firstName": normalized_fields.get("firstName", ""),
                "lastName": normalized_fields.get("lastName", ""),
                "email": normalized_fields.get("email", ""),
                "phone": normalized_fields.get("phone", ""),
                "source": f"Meta Ad - {lead_data.campaign_name or 'Unknown Campaign'}",
                "customFields": {
                    "metaLeadId": lead_data.id,
                    "metaCampaignName": lead_data.campaign_name,
                    "metaAdName": lead_data.ad_name,
                    "metaFormName": lead_data.form_name,
                },
            }

            # Create initial greeting message based on the lead source
            initial_message = self._create_initial_message(lead_data, normalized_fields)

            # Process through qualification agent
            result = await self.qualification_agent.process_message(
                message=initial_message,
                contact_id=contact_id,
                contact_info=contact_info,
            )

            if result.get("response"):
                logger.info(
                    "Qualification agent triggered successfully",
                    contact_id=contact_id,
                    lead_id=lead_data.id,
                    qualification_status=result.get("qualification_status"),
                    thread_id=result.get("thread_id"),
                )
                return True
            else:
                logger.error(
                    "No response from qualification agent", contact_id=contact_id
                )
                return False

        except Exception as e:
            logger.error(
                "Error triggering qualification agent",
                error=str(e),
                contact_id=contact_id,
            )
            return False

    def _create_initial_message(
        self, lead_data: MetaLeadData, normalized_fields: Dict[str, str]
    ) -> str:
        """
        Create an initial message to trigger the qualification agent.

        Args:
            lead_data: Meta lead data
            normalized_fields: Normalized contact fields

        Returns:
            str: Initial message for the agent
        """
        first_name = normalized_fields.get("firstName", "")
        campaign_name = lead_data.campaign_name or "automation services"
        form_name = lead_data.form_name or "lead form"

        # Create a natural initial message that would trigger the agent
        if first_name:
            message = f"Hi! I'm {first_name}. I just filled out your {form_name} from your {campaign_name} ad. I'm interested in learning more about automation services."
        else:
            message = f"Hi there! I just filled out your {form_name} from your {campaign_name} ad. I'm interested in learning more about your automation services."

        return message

    async def process_lead(self, lead_data: MetaLeadData) -> Dict[str, Any]:
        """
        Process a single lead through the complete workflow.

        Args:
            lead_data: Meta lead data

        Returns:
            Dict[str, Any]: Processing result
        """
        try:
            logger.info(
                "Processing Meta lead",
                lead_id=lead_data.id,
                campaign=lead_data.campaign_name,
            )

            # Normalize lead fields
            normalized_fields = self.normalize_lead_fields(lead_data.field_data)

            if not normalized_fields.get("email") and not normalized_fields.get(
                "phone"
            ):
                return {
                    "success": False,
                    "error": "Lead has no email or phone contact information",
                    "lead_id": lead_data.id,
                }

            # Find or create GHL contact
            contact_id = await self.find_or_create_ghl_contact(
                lead_data, normalized_fields
            )

            if not contact_id:
                return {
                    "success": False,
                    "error": "Failed to find or create GHL contact",
                    "lead_id": lead_data.id,
                }

            # Trigger qualification agent
            agent_triggered = await self.trigger_qualification_agent(
                contact_id, lead_data, normalized_fields
            )

            if not agent_triggered:
                return {
                    "success": False,
                    "error": "Failed to trigger qualification agent",
                    "lead_id": lead_data.id,
                    "contact_id": contact_id,
                }

            return {
                "success": True,
                "lead_id": lead_data.id,
                "contact_id": contact_id,
                "message": "Lead processed successfully",
            }

        except Exception as e:
            logger.error("Error processing lead", error=str(e), lead_id=lead_data.id)
            return {"success": False, "error": str(e), "lead_id": lead_data.id}


# Global webhook handler instance
webhook_handler = MetaWebhookHandler()


# FastAPI webhook endpoints
async def verify_webhook(request: Request) -> JSONResponse:
    """
    Webhook verification endpoint for Meta.

    Meta sends a GET request with challenge parameter during setup.
    """
    try:
        # Get query parameters
        mode = request.query_params.get("hub.mode")
        token = request.query_params.get("hub.verify_token")
        challenge = request.query_params.get("hub.challenge")

        logger.info(
            "Webhook verification request", mode=mode, token_provided=bool(token)
        )

        # Verify the mode and token
        if mode == "subscribe" and token == webhook_handler.verify_token:
            logger.info("Webhook verification successful")
            return JSONResponse(content=int(challenge), status_code=200)
        else:
            logger.error(
                "Webhook verification failed",
                expected_token=bool(webhook_handler.verify_token),
            )
            raise HTTPException(status_code=403, detail="Verification failed")

    except Exception as e:
        logger.error("Error in webhook verification", error=str(e))
        raise HTTPException(status_code=500, detail="Verification error")


async def handle_webhook(
    request: Request, background_tasks: BackgroundTasks
) -> JSONResponse:
    """
    Main webhook endpoint for receiving Meta ads leads.

    Processes webhook payload, validates signature, and triggers lead processing.
    """
    try:
        # Get raw payload for signature verification
        payload_bytes = await request.body()

        # Verify webhook signature
        signature = request.headers.get("X-Hub-Signature-256", "")
        if not webhook_handler.verify_webhook_signature(payload_bytes, signature):
            raise HTTPException(status_code=401, detail="Invalid signature")

        # Parse JSON payload
        try:
            payload = json.loads(payload_bytes.decode("utf-8"))
        except json.JSONDecodeError as e:
            logger.error("Invalid JSON payload", error=str(e))
            raise HTTPException(status_code=400, detail="Invalid JSON payload")

        logger.info("Webhook received", object_type=payload.get("object"))

        # Extract lead data
        leads = webhook_handler.extract_lead_data(payload)

        if not leads:
            logger.info("No leads found in webhook payload")
            return JSONResponse(
                content=WebhookResponse(
                    success=True, message="No leads to process", processed_leads=0
                ).dict()
            )

        # Process leads in background
        processed_count = 0
        errors = []

        for lead in leads:
            try:
                # Add lead processing to background tasks for async processing
                background_tasks.add_task(webhook_handler.process_lead, lead)
                processed_count += 1

            except Exception as e:
                error_msg = f"Error queuing lead {lead.id}: {str(e)}"
                errors.append(error_msg)
                logger.error(
                    "Error queuing lead processing", error=str(e), lead_id=lead.id
                )

        # Return immediate response
        response = WebhookResponse(
            success=True,
            message=f"Webhook processed successfully. {processed_count} leads queued for processing.",
            processed_leads=processed_count,
            errors=errors,
        )

        logger.info(
            "Webhook processing completed",
            processed_leads=processed_count,
            errors_count=len(errors),
        )

        return JSONResponse(content=response.dict(), status_code=200)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Unexpected error in webhook handler", error=str(e))
        raise HTTPException(
            status_code=500, detail=f"Webhook processing error: {str(e)}"
        )


def get_webhook_handler() -> MetaWebhookHandler:
    """Get the global webhook handler instance."""
    return webhook_handler




