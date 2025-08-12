"""
LangSmith configuration and tracing setup with comprehensive error handling.

This module provides robust LangSmith integration with fallback options for local development
and comprehensive troubleshooting for common deployment issues.
"""

import os
import logging
from typing import Optional, Dict, Any
from functools import wraps

import structlog
from langsmith import Client
from langchain_core.tracers.langchain import LangChainTracer
from langchain_core.callbacks import CallbackManager

logger = structlog.get_logger(__name__)


class LangSmithConfig:
    """
    LangSmith configuration manager with error handling and fallback options.
    
    Handles common deployment issues:
    - Missing API keys
    - Network connectivity problems
    - Licensing errors
    - Invalid project configurations
    """
    
    def __init__(self):
        self.api_key: Optional[str] = None
        self.project_name: Optional[str] = None
        self.endpoint: Optional[str] = None
        self.client: Optional[Client] = None
        self.tracer: Optional[LangChainTracer] = None
        self.is_enabled: bool = False
        self.fallback_mode: bool = False
        
    def initialize(self) -> bool:
        """
        Initialize LangSmith configuration with comprehensive error handling.
        
        Returns:
            bool: True if LangSmith is successfully configured, False if fallback mode
        """
        try:
            # Load configuration from environment
            self.api_key = os.getenv("LANGSMITH_API_KEY")
            self.project_name = os.getenv("LANGSMITH_PROJECT", "ghl-qualification-webhook")
            self.endpoint = os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")
            tracing_enabled = os.getenv("LANGSMITH_TRACING", "true").lower() == "true"
            
            if not tracing_enabled:
                logger.info("LangSmith tracing disabled via LANGSMITH_TRACING=false")
                return self._enable_fallback_mode("Tracing disabled by configuration")
            
            if not self.api_key:
                return self._enable_fallback_mode("LANGSMITH_API_KEY not found in environment")
            
            # Test LangSmith connection
            return self._setup_langsmith_client()
            
        except Exception as e:
            return self._enable_fallback_mode(f"Unexpected error during initialization: {str(e)}")
    
    def _setup_langsmith_client(self) -> bool:
        """Setup LangSmith client with connection testing."""
        try:
            # Initialize LangSmith client
            self.client = Client(
                api_key=self.api_key,
                api_url=self.endpoint
            )
            
            # Test connection by attempting to get project info
            try:
                # This will raise an exception if the API key is invalid or there are connection issues
                self.client.list_runs(project_name=self.project_name, limit=1)
                logger.info("LangSmith connection test successful", project=self.project_name)
            except Exception as conn_error:
                # Try to create the project if it doesn't exist
                try:
                    self.client.create_project(project_name=self.project_name)
                    logger.info("Created new LangSmith project", project=self.project_name)
                except Exception as create_error:
                    return self._handle_connection_error(conn_error, create_error)
            
            # Setup tracer
            self.tracer = LangChainTracer(
                project_name=self.project_name,
                client=self.client
            )
            
            self.is_enabled = True
            logger.info(
                "LangSmith successfully configured",
                project=self.project_name,
                endpoint=self.endpoint
            )
            return True
            
        except Exception as e:
            return self._enable_fallback_mode(f"Failed to setup LangSmith client: {str(e)}")
    
    def _handle_connection_error(self, conn_error: Exception, create_error: Exception) -> bool:
        """Handle connection and project creation errors with specific guidance."""
        error_msg = str(conn_error).lower()
        
        if "unauthorized" in error_msg or "invalid api key" in error_msg:
            return self._enable_fallback_mode(
                "Invalid LangSmith API key. Please check LANGSMITH_API_KEY environment variable."
            )
        elif "forbidden" in error_msg or "license" in error_msg:
            return self._enable_fallback_mode(
                "LangSmith licensing issue. Please verify your subscription and permissions."
            )
        elif "not found" in error_msg:
            return self._enable_fallback_mode(
                f"Project '{self.project_name}' not found and couldn't be created: {str(create_error)}"
            )
        elif "timeout" in error_msg or "connection" in error_msg:
            return self._enable_fallback_mode(
                "Network connectivity issue with LangSmith. Check your internet connection and firewall settings."
            )
        else:
            return self._enable_fallback_mode(
                f"LangSmith connection failed: {str(conn_error)}"
            )
    
    def _enable_fallback_mode(self, reason: str) -> bool:
        """Enable fallback mode with logging."""
        self.fallback_mode = True
        self.is_enabled = False
        logger.warning(
            "LangSmith fallback mode enabled - continuing without tracing",
            reason=reason
        )
        return False
    
    def get_callback_manager(self) -> CallbackManager:
        """
        Get callback manager with LangSmith tracer if available.
        
        Returns:
            CallbackManager: Configured callback manager
        """
        callbacks = []
        if self.is_enabled and self.tracer:
            callbacks.append(self.tracer)
        
        return CallbackManager(callbacks)
    
    def get_run_config(self, **kwargs) -> Dict[str, Any]:
        """
        Get run configuration for LangGraph with optional LangSmith integration.
        
        Args:
            **kwargs: Additional configuration parameters
            
        Returns:
            Dict[str, Any]: Run configuration
        """
        config = {
            "callbacks": self.get_callback_manager(),
            **kwargs
        }
        
        if self.is_enabled:
            config.update({
                "tags": kwargs.get("tags", []) + ["ghl-qualification"],
                "metadata": {
                    "project": self.project_name,
                    "environment": os.getenv("ENVIRONMENT", "development"),
                    **kwargs.get("metadata", {})
                }
            })
        
        return config
    
    def create_run(self, name: str, inputs: Dict[str, Any], **kwargs) -> Optional[str]:
        """
        Create a new run in LangSmith if available.
        
        Args:
            name: Run name
            inputs: Input data
            **kwargs: Additional run parameters
            
        Returns:
            Optional[str]: Run ID if successful, None if in fallback mode
        """
        if not self.is_enabled or not self.client:
            return None
        
        try:
            run = self.client.create_run(
                name=name,
                inputs=inputs,
                project_name=self.project_name,
                **kwargs
            )
            return str(run.id)
        except Exception as e:
            logger.warning("Failed to create LangSmith run", error=str(e))
            return None
    
    def end_run(self, run_id: str, outputs: Dict[str, Any], **kwargs) -> None:
        """
        End a run in LangSmith if available.
        
        Args:
            run_id: Run ID to end
            outputs: Output data
            **kwargs: Additional parameters
        """
        if not self.is_enabled or not self.client or not run_id:
            return
        
        try:
            self.client.update_run(
                run_id=run_id,
                outputs=outputs,
                **kwargs
            )
        except Exception as e:
            logger.warning("Failed to end LangSmith run", run_id=run_id, error=str(e))
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get current LangSmith configuration status.
        
        Returns:
            Dict[str, Any]: Status information
        """
        return {
            "enabled": self.is_enabled,
            "fallback_mode": self.fallback_mode,
            "project_name": self.project_name,
            "endpoint": self.endpoint,
            "has_api_key": bool(self.api_key),
            "has_client": bool(self.client),
            "has_tracer": bool(self.tracer)
        }


# Global LangSmith configuration instance
langsmith_config = LangSmithConfig()


def with_langsmith_tracing(run_name: Optional[str] = None):
    """
    Decorator to add LangSmith tracing to functions.
    
    Args:
        run_name: Optional custom run name
    """
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            if not langsmith_config.is_enabled:
                return await func(*args, **kwargs)
            
            name = run_name or f"{func.__module__}.{func.__name__}"
            run_id = langsmith_config.create_run(
                name=name,
                inputs={"args": str(args), "kwargs": str(kwargs)}
            )
            
            try:
                result = await func(*args, **kwargs)
                if run_id:
                    langsmith_config.end_run(run_id, {"result": str(result)})
                return result
            except Exception as e:
                if run_id:
                    langsmith_config.end_run(run_id, {"error": str(e)})
                raise
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            if not langsmith_config.is_enabled:
                return func(*args, **kwargs)
            
            name = run_name or f"{func.__module__}.{func.__name__}"
            run_id = langsmith_config.create_run(
                name=name,
                inputs={"args": str(args), "kwargs": str(kwargs)}
            )
            
            try:
                result = func(*args, **kwargs)
                if run_id:
                    langsmith_config.end_run(run_id, {"result": str(result)})
                return result
            except Exception as e:
                if run_id:
                    langsmith_config.end_run(run_id, {"error": str(e)})
                raise
        
        # Return appropriate wrapper based on function type
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator


def initialize_langsmith() -> bool:
    """
    Initialize LangSmith configuration.
    
    Returns:
        bool: True if successful, False if fallback mode
    """
    return langsmith_config.initialize()


def get_langsmith_config() -> LangSmithConfig:
    """Get the global LangSmith configuration instance."""
    return langsmith_config


def setup_logging():
    """Setup structured logging configuration."""
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer()
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    
    # Configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, log_level, logging.INFO),
    )
