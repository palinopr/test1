"""
Main FastAPI Application Server for GHL Customer Qualification Webhook.

This is the main entry point that combines all components:
- GHL webhook endpoints (corrected flow: Meta → GHL → GHL webhook → LangGraph)
- Customer qualification agent
- LangSmith tracing setup
- Health check endpoints
- Proper error handling and logging
"""

import asyncio
import os
import sys
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

import structlog
import uvicorn
from dotenv import load_dotenv
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse

from .agents.qualification_agent import get_qualification_agent

# Import our modules
from .config.langsmith_config import (
    get_langsmith_config,
    initialize_langsmith,
    setup_logging,
)
from .exceptions import ConfigurationError, QualificationError
from .state.conversation_state import get_state_manager
from .tools.ghl_tools import test_ghl_connection

# Load environment variables
load_dotenv()

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager for startup and shutdown procedures."""
    # Startup
    logger.info("Starting GHL Customer Qualification Webhook Server")

    # Initialize logging
    setup_logging()
    logger.info("Logging configured")

    # Initialize LangSmith (with fallback)
    langsmith_success = initialize_langsmith()
    if langsmith_success:
        logger.info("LangSmith tracing enabled")
    else:
        logger.info("LangSmith tracing disabled - running in fallback mode")

    # Initialize state manager
    state_manager = get_state_manager()
    logger.info("Conversation state manager initialized")

    # Test GHL connection
    try:
        ghl_status = await test_ghl_connection()
        if ghl_status["connected"]:
            logger.info("GHL API connection successful")
        else:
            logger.warning("GHL API connection failed", error=ghl_status.get("error"))
    except Exception as e:
        logger.warning("Could not test GHL connection", error=str(e))

    # Initialize qualification agent (lazy loading)
    try:
        agent = get_qualification_agent()
        logger.info("Qualification agent initialized")
    except Exception as e:
        logger.warning("Qualification agent initialization failed", error=str(e))

    logger.info("Application startup completed")

    yield

    # Shutdown
    logger.info("Shutting down GHL Customer Qualification Webhook Server")

    # Cleanup old conversation states
    try:
        cleanup_count = state_manager.cleanup_old_states(days_old=30)
        logger.info("Cleaned up old conversation states", count=cleanup_count)
    except Exception as e:
        logger.error("Error during state cleanup", error=str(e))

    logger.info("Application shutdown completed")


# Create FastAPI application
app = FastAPI(
    title="GHL Customer Qualification Webhook",
    description="AI-powered customer qualification system for Go High Level using LangGraph",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Add middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add trusted host middleware for security
trusted_hosts = os.getenv("TRUSTED_HOSTS", "*").split(",")
if "*" not in trusted_hosts:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=trusted_hosts)


# Health Check Endpoints
@app.get("/health", response_class=PlainTextResponse)
async def health_check():
    """Basic health check endpoint."""
    return "OK"


@app.get("/health/detailed")
async def detailed_health_check():
    """Detailed health check with component status."""
    health_status = {
        "status": "healthy",
        "timestamp": structlog.get_logger().info("Health check requested"),
        "components": {},
    }

    # Check LangSmith configuration
    langsmith_config = get_langsmith_config()
    health_status["components"]["langsmith"] = {
        "enabled": langsmith_config.is_enabled,
        "fallback_mode": langsmith_config.fallback_mode,
        "status": "healthy" if not langsmith_config.fallback_mode else "degraded",
    }

    # Check GHL API connection
    try:
        ghl_status = await test_ghl_connection()
        health_status["components"]["ghl_api"] = {
            "connected": ghl_status["connected"],
            "has_api_key": ghl_status["has_api_key"],
            "status": "healthy" if ghl_status["connected"] else "unhealthy",
            "error": ghl_status.get("error"),
        }
    except Exception as e:
        health_status["components"]["ghl_api"] = {"status": "error", "error": str(e)}

    # Check qualification agent
    try:
        agent = get_qualification_agent()
        health_status["components"]["qualification_agent"] = {
            "status": "healthy" if agent else "unhealthy",
            "model": getattr(agent, "model_name", "unknown") if agent else None,
        }
    except Exception as e:
        health_status["components"]["qualification_agent"] = {
            "status": "error",
            "error": str(e),
        }

    # Check state manager
    try:
        state_manager = get_state_manager()
        active_conversations = state_manager.get_active_conversations(limit=1)
        health_status["components"]["state_manager"] = {
            "status": "healthy",
            "database_accessible": True,
            "active_conversations_sample": len(active_conversations),
        }
    except Exception as e:
        health_status["components"]["state_manager"] = {
            "status": "error",
            "error": str(e),
        }

    # Determine overall status
    component_statuses = [
        comp.get("status", "unknown") for comp in health_status["components"].values()
    ]
    if "error" in component_statuses:
        health_status["status"] = "unhealthy"
    elif "unhealthy" in component_statuses:
        health_status["status"] = "degraded"
    elif "degraded" in component_statuses:
        health_status["status"] = "degraded"

    return JSONResponse(content=health_status)


# GHL Webhook Endpoints (Corrected Flow)
@app.get("/webhook/ghl")
async def verify_ghl_webhook(request: Request):
    """
    GHL webhook verification endpoint.

    This handles the webhook verification process from Go High Level.
    """
    try:
        # GHL webhook verification logic
        challenge = request.query_params.get("challenge")
        verify_token = request.query_params.get("verify_token")

        expected_token = os.getenv("GHL_WEBHOOK_VERIFY_TOKEN")

        logger.info(
            "GHL webhook verification request",
            has_challenge=bool(challenge),
            has_token=bool(verify_token),
        )

        if challenge and verify_token == expected_token:
            logger.info("GHL webhook verification successful")
            return PlainTextResponse(content=challenge)
        else:
            logger.error("GHL webhook verification failed")
            raise HTTPException(status_code=403, detail="Verification failed")

    except Exception as e:
        logger.error("Error in GHL webhook verification", error=str(e))
        raise HTTPException(status_code=500, detail="Verification error")


@app.post("/webhook/ghl")
async def handle_ghl_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Main GHL webhook endpoint for receiving lead and conversation events.

    This is the corrected flow: Meta ad → GHL → GHL webhook → LangGraph
    """
    try:
        # Get raw payload
        payload = await request.json()

        logger.info("GHL webhook received", event_type=payload.get("type", "unknown"))

        # Handle different GHL webhook event types
        event_type = payload.get("type")

        if event_type == "ContactCreate":
            # New contact created in GHL (potentially from Meta ad)
            background_tasks.add_task(handle_contact_create, payload)

        elif event_type == "InboundMessage":
            # Incoming message from customer
            background_tasks.add_task(handle_inbound_message, payload)

        elif event_type == "ContactUpdate":
            # Contact information updated
            background_tasks.add_task(handle_contact_update, payload)

        else:
            logger.info("Unhandled GHL webhook event type", event_type=event_type)

        return JSONResponse(content={"success": True, "message": "Webhook processed"})

    except Exception as e:
        logger.error("Error processing GHL webhook", error=str(e))
        raise HTTPException(
            status_code=500, detail=f"Webhook processing error: {str(e)}"
        )


async def handle_contact_create(payload: Dict[str, Any]):
    """
    Handle new contact creation from GHL.

    This triggers when a new lead comes from Meta ads into GHL.
    """
    try:
        contact_data = payload.get("contact", {})
        contact_id = contact_data.get("id")

        if not contact_id:
            logger.error("No contact ID in ContactCreate payload")
            return

        logger.info("Processing new contact from GHL", contact_id=contact_id)

        # Extract contact information
        customer_data = {
            "firstName": contact_data.get("firstName"),
            "lastName": contact_data.get("lastName"),
            "email": contact_data.get("email"),
            "phone": contact_data.get("phone"),
            "companyName": contact_data.get("companyName"),
            "source": contact_data.get("source", "GHL"),
            "customFields": contact_data.get("customFields", {}),
        }

        # Create conversation state
        from datetime import datetime

        from .state.conversation_state import create_conversation_state

        thread_id = (
            f"ghl_contact_{contact_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        )
        state = create_conversation_state(thread_id, contact_id, customer_data)

        # Trigger qualification agent with initial greeting
        agent = get_qualification_agent()
        if agent:
            # Create a natural initial message based on the source
            source = customer_data.get("source", "")
            first_name = customer_data.get("firstName", "")

            if "meta" in source.lower() or "facebook" in source.lower():
                initial_message = f"Hi! I'm {first_name}. I just filled out your form from your Facebook ad. I'm interested in learning more about automation services."
            else:
                initial_message = f"Hi there! I'm {first_name}. I'm interested in your automation services."

            # Process through qualification agent
            result = await agent.process_message(
                message=initial_message,
                contact_id=contact_id,
                contact_info=customer_data,
                thread_id=thread_id,
            )

            logger.info(
                "Qualification agent triggered for new contact",
                contact_id=contact_id,
                thread_id=thread_id,
                qualification_status=result.get("qualification_status"),
            )
        else:
            logger.warning(
                "Qualification agent not available for new contact",
                contact_id=contact_id,
            )

    except Exception as e:
        logger.error("Error handling contact creation", error=str(e))


async def handle_inbound_message(payload: Dict[str, Any]):
    """
    Handle inbound messages from customers via GHL.

    This continues the conversation with the qualification agent.
    """
    try:
        message_data = payload.get("message", {})
        contact_id = message_data.get("contactId")
        message_body = message_data.get("body", "")

        if not contact_id or not message_body:
            logger.error("Missing contact ID or message body in InboundMessage payload")
            return

        logger.info(
            "Processing inbound message",
            contact_id=contact_id,
            message_preview=message_body[:50],
        )

        # Find existing conversation state
        from .state.conversation_state import get_state_manager

        state_manager = get_state_manager()

        # Look for existing conversation thread for this contact
        # In a real implementation, you'd have a mapping of contact_id to thread_id
        # For now, we'll create a new thread or use a simple mapping
        thread_id = f"ghl_contact_{contact_id}_conversation"

        existing_state = state_manager.get_state(thread_id)

        if not existing_state:
            # Create new conversation state if none exists
            customer_data = {
                "firstName": message_data.get("contact", {}).get("firstName", ""),
                "lastName": message_data.get("contact", {}).get("lastName", ""),
                "email": message_data.get("contact", {}).get("email", ""),
                "phone": message_data.get("contact", {}).get("phone", ""),
                "source": "GHL Inbound Message",
            }

            from .state.conversation_state import create_conversation_state

            existing_state = create_conversation_state(
                thread_id, contact_id, customer_data
            )

        # Process message through qualification agent
        agent = get_qualification_agent()
        if agent:
            result = await agent.process_message(
                message=message_body,
                contact_id=contact_id,
                contact_info=existing_state.customer_info.to_dict(),
                thread_id=thread_id,
            )

            logger.info(
                "Inbound message processed",
                contact_id=contact_id,
                thread_id=thread_id,
                qualification_status=result.get("qualification_status"),
                conversation_stage=result.get("conversation_stage"),
            )
        else:
            logger.warning(
                "Qualification agent not available for inbound message",
                contact_id=contact_id,
            )

    except Exception as e:
        logger.error("Error handling inbound message", error=str(e))


async def handle_contact_update(payload: Dict[str, Any]):
    """
    Handle contact updates from GHL.

    This updates the conversation state with new contact information.
    """
    try:
        contact_data = payload.get("contact", {})
        contact_id = contact_data.get("id")

        if not contact_id:
            logger.error("No contact ID in ContactUpdate payload")
            return

        logger.info("Processing contact update", contact_id=contact_id)

        # Find and update existing conversation state
        from .state.conversation_state import get_state_manager

        state_manager = get_state_manager()

        thread_id = f"ghl_contact_{contact_id}_conversation"
        existing_state = state_manager.get_state(thread_id)

        if existing_state:
            # Update customer information
            updates = {
                "firstName": contact_data.get("firstName"),
                "lastName": contact_data.get("lastName"),
                "email": contact_data.get("email"),
                "phone": contact_data.get("phone"),
                "companyName": contact_data.get("companyName"),
                "custom_fields": contact_data.get("customFields", {}),
            }

            # Remove None values
            updates = {k: v for k, v in updates.items() if v is not None}

            existing_state.update_customer_info(updates)
            state_manager.save_state(existing_state)

            logger.info(
                "Contact information updated in conversation state",
                contact_id=contact_id,
            )
        else:
            logger.info(
                "No existing conversation state found for contact update",
                contact_id=contact_id,
            )

    except Exception as e:
        logger.error("Error handling contact update", error=str(e))


# API Endpoints for Manual Testing and Management
@app.post("/api/qualify")
async def manual_qualification(request: Request):
    """
    Manual qualification endpoint for testing.

    Allows manual triggering of the qualification process.
    """
    try:
        data = await request.json()

        contact_id = data.get("contact_id")
        message = data.get("message")
        customer_info = data.get("customer_info", {})

        if not contact_id or not message:
            raise HTTPException(
                status_code=400, detail="contact_id and message are required"
            )

        # Process through qualification agent
        agent = get_qualification_agent()
        if not agent:
            raise HTTPException(
                status_code=503, detail="Qualification agent not available"
            )

        result = await agent.process_message(
            message=message, contact_id=contact_id, contact_info=customer_info
        )

        return JSONResponse(content=result)

    except HTTPException:
        raise
    except QualificationError as e:
        logger.error(
            "Manual qualification error",
            error=str(e),
            contact_id=e.contact_id,
            thread_id=e.thread_id,
            conversation_stage=e.conversation_stage,
        )
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(
            "Unexpected error in manual qualification",
            error=str(e),
            error_type=type(e).__name__,
        )
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")


@app.get("/api/conversations")
async def get_active_conversations(limit: int = 50):
    """Get list of active conversations."""
    try:
        state_manager = get_state_manager()
        conversations = state_manager.get_active_conversations(limit=limit)

        return JSONResponse(
            content={"conversations": conversations, "count": len(conversations)}
        )

    except Exception as e:
        logger.error("Error getting active conversations", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/conversation/{thread_id}")
async def get_conversation_details(thread_id: str):
    """Get detailed information about a specific conversation."""
    try:
        agent = get_qualification_agent()
        if not agent:
            raise HTTPException(
                status_code=503, detail="Qualification agent not available"
            )

        summary = agent.get_qualification_summary(thread_id)

        if summary.get("error"):
            raise HTTPException(status_code=404, detail=summary["error"])

        return JSONResponse(content=summary)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error getting conversation details", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# Error Handlers
@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    return JSONResponse(
        status_code=404, content={"error": "Not found", "path": str(request.url.path)}
    )


@app.exception_handler(500)
async def internal_error_handler(request: Request, exc):
    logger.error("Internal server error", error=str(exc), path=str(request.url.path))
    return JSONResponse(status_code=500, content={"error": "Internal server error"})


# Main entry point
def main():
    """Main entry point for the application."""
    host = os.getenv("APP_HOST", "0.0.0.0")
    port = int(os.getenv("APP_PORT", "8000"))
    debug = os.getenv("APP_DEBUG", "false").lower() == "true"

    logger.info("Starting server", host=host, port=port, debug=debug)

    uvicorn.run(
        "src.main:app",
        host=host,
        port=port,
        reload=debug,
        log_level="info" if not debug else "debug",
    )


if __name__ == "__main__":
    main()
