"""
Configuration validation module for GHL Customer Qualification Webhook.

This module provides comprehensive validation of environment variables,
API key connectivity tests, and system health checks for application startup
and health monitoring endpoints.
"""

import asyncio
import os
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

import httpx
import structlog
from openai import AsyncOpenAI

from ..exceptions import ConfigurationError

logger = structlog.get_logger(__name__)


class ConfigurationValidator:
    """Validates application configuration and external service connectivity."""

    def __init__(self):
        self.required_env_vars = {
            # Core API Keys (required for basic functionality)
            "OPENAI_API_KEY": {
                "description": "OpenAI API key for LLM functionality",
                "required": True,
                "sensitive": True,
            },
            "GHL_API_KEY": {
                "description": "Go High Level API key for CRM integration",
                "required": True,
                "sensitive": True,
            },
            # LangSmith Configuration (optional but recommended)
            "LANGSMITH_API_KEY": {
                "description": "LangSmith API key for tracing and monitoring",
                "required": False,
                "sensitive": True,
            },
            "LANGSMITH_PROJECT": {
                "description": "LangSmith project name",
                "required": False,
                "sensitive": False,
                "default": "ghl-qualification-webhook",
            },
            "LANGSMITH_TRACING": {
                "description": "Enable LangSmith tracing",
                "required": False,
                "sensitive": False,
                "default": "true",
            },
            # Meta Webhook Configuration (required for webhook functionality)
            "META_WEBHOOK_VERIFY_TOKEN": {
                "description": "Meta webhook verification token",
                "required": True,
                "sensitive": True,
            },
            "META_WEBHOOK_SECRET": {
                "description": "Meta webhook secret for signature verification",
                "required": True,
                "sensitive": True,
            },
            # Application Configuration
            "APP_HOST": {
                "description": "Application host address",
                "required": False,
                "sensitive": False,
                "default": "0.0.0.0",
            },
            "APP_PORT": {
                "description": "Application port number",
                "required": False,
                "sensitive": False,
                "default": "8000",
            },
            "APP_DEBUG": {
                "description": "Enable debug mode",
                "required": False,
                "sensitive": False,
                "default": "false",
            },
            "LOG_LEVEL": {
                "description": "Logging level",
                "required": False,
                "sensitive": False,
                "default": "INFO",
            },
            # Database Configuration
            "DATABASE_URL": {
                "description": "Database URL for conversation state storage",
                "required": False,
                "sensitive": False,
                "default": "sqlite:///./conversation_states.db",
            },
            # Security
            "SECRET_KEY": {
                "description": "Application secret key",
                "required": True,
                "sensitive": True,
            },
            # GHL Configuration
            "GHL_BASE_URL": {
                "description": "Go High Level API base URL",
                "required": False,
                "sensitive": False,
                "default": "https://services.leadconnectorhq.com",
            },
        }

    def validate_environment_variables(self) -> Dict[str, Any]:
        """
        Validate all required environment variables.
        
        Returns:
            Dict containing validation results and missing/invalid variables.
        """
        validation_result = {
            "valid": True,
            "missing_required": [],
            "missing_optional": [],
            "invalid_values": [],
            "configured_vars": [],
            "total_required": 0,
            "total_configured": 0,
        }

        for var_name, config in self.required_env_vars.items():
            value = os.getenv(var_name)
            is_required = config.get("required", False)
            default_value = config.get("default")

            if is_required:
                validation_result["total_required"] += 1

            if value is None:
                if default_value is not None:
                    # Use default value
                    os.environ[var_name] = default_value
                    validation_result["configured_vars"].append(
                        {
                            "name": var_name,
                            "status": "default",
                            "description": config["description"],
                        }
                    )
                    validation_result["total_configured"] += 1
                elif is_required:
                    validation_result["missing_required"].append(
                        {
                            "name": var_name,
                            "description": config["description"],
                        }
                    )
                    validation_result["valid"] = False
                else:
                    validation_result["missing_optional"].append(
                        {
                            "name": var_name,
                            "description": config["description"],
                        }
                    )
            else:
                # Validate specific values
                if var_name in ["APP_PORT"]:
                    try:
                        port = int(value)
                        if not (1 <= port <= 65535):
                            raise ValueError("Port must be between 1 and 65535")
                    except ValueError as e:
                        validation_result["invalid_values"].append(
                            {
                                "name": var_name,
                                "value": value,
                                "error": str(e),
                            }
                        )
                        validation_result["valid"] = False
                        continue

                elif var_name in ["LANGSMITH_TRACING", "APP_DEBUG"]:
                    if value.lower() not in ["true", "false"]:
                        validation_result["invalid_values"].append(
                            {
                                "name": var_name,
                                "value": value,
                                "error": "Must be 'true' or 'false'",
                            }
                        )
                        validation_result["valid"] = False
                        continue

                elif var_name == "LOG_LEVEL":
                    valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
                    if value.upper() not in valid_levels:
                        validation_result["invalid_values"].append(
                            {
                                "name": var_name,
                                "value": value,
                                "error": f"Must be one of: {', '.join(valid_levels)}",
                            }
                        )
                        validation_result["valid"] = False
                        continue

                # Variable is configured and valid
                validation_result["configured_vars"].append(
                    {
                        "name": var_name,
                        "status": "configured",
                        "description": config["description"],
                        "sensitive": config.get("sensitive", False),
                    }
                )
                validation_result["total_configured"] += 1

        return validation_result

    async def test_openai_connectivity(self) -> Dict[str, Any]:
        """
        Test OpenAI API connectivity and authentication.
        
        Returns:
            Dict containing connectivity test results.
        """
        result = {
            "connected": False,
            "authenticated": False,
            "error": None,
            "model_available": False,
            "response_time_ms": None,
        }

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key or api_key == "your_openai_api_key_here":
            result["error"] = "OpenAI API key not configured"
            return result

        try:
            import time

            start_time = time.time()

            client = AsyncOpenAI(api_key=api_key)

            # Test with a minimal completion request
            response = await client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": "Hello"}],
                max_tokens=1,
                timeout=10.0,
            )

            end_time = time.time()
            result["response_time_ms"] = int((end_time - start_time) * 1000)

            if response and response.choices:
                result["connected"] = True
                result["authenticated"] = True
                result["model_available"] = True

        except Exception as e:
            result["error"] = str(e)
            if "authentication" in str(e).lower() or "api key" in str(e).lower():
                result["connected"] = True  # Connection works, but auth failed
            elif "timeout" in str(e).lower():
                result["error"] = "Connection timeout"
            elif "connection" in str(e).lower():
                result["error"] = "Connection failed"

        return result

    async def test_ghl_connectivity(self) -> Dict[str, Any]:
        """
        Test Go High Level API connectivity and authentication.
        
        Returns:
            Dict containing connectivity test results.
        """
        result = {
            "connected": False,
            "authenticated": False,
            "error": None,
            "base_url": None,
            "response_time_ms": None,
        }

        api_key = os.getenv("GHL_API_KEY")
        base_url = os.getenv("GHL_BASE_URL", "https://services.leadconnectorhq.com")

        if not api_key or api_key == "your_ghl_api_key_here":
            result["error"] = "GHL API key not configured"
            return result

        result["base_url"] = base_url

        try:
            import time

            start_time = time.time()

            async with httpx.AsyncClient(timeout=10.0) as client:
                # Test with a simple API endpoint (locations or similar)
                response = await client.get(
                    f"{base_url}/locations/",
                    headers={"Authorization": f"Bearer {api_key}"},
                )

                end_time = time.time()
                result["response_time_ms"] = int((end_time - start_time) * 1000)

                if response.status_code == 200:
                    result["connected"] = True
                    result["authenticated"] = True
                elif response.status_code == 401:
                    result["connected"] = True
                    result["error"] = "Authentication failed - invalid API key"
                elif response.status_code == 403:
                    result["connected"] = True
                    result["error"] = "Access forbidden - check API key permissions"
                else:
                    result["connected"] = True
                    result["error"] = f"API returned status {response.status_code}"

        except httpx.TimeoutException:
            result["error"] = "Connection timeout"
        except httpx.ConnectError:
            result["error"] = "Connection failed - check network connectivity"
        except Exception as e:
            result["error"] = str(e)

        return result

    def test_database_connectivity(self) -> Dict[str, Any]:
        """
        Test SQLite database connectivity and basic operations.
        
        Returns:
            Dict containing database connectivity test results.
        """
        result = {
            "connected": False,
            "writable": False,
            "error": None,
            "database_path": None,
            "tables_exist": False,
        }

        database_url = os.getenv("DATABASE_URL", "sqlite:///./conversation_states.db")

        # Extract SQLite path from URL
        if database_url.startswith("sqlite:///"):
            db_path = database_url[10:]  # Remove 'sqlite:///'
        else:
            result["error"] = "Unsupported database URL format"
            return result

        result["database_path"] = db_path

        try:
            # Test connection
            conn = sqlite3.connect(db_path, timeout=5.0)
            result["connected"] = True

            # Test if we can query the database
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = cursor.fetchall()

            # Check if conversation_states table exists
            table_names = [table[0] for table in tables]
            if "conversation_states" in table_names:
                result["tables_exist"] = True

            # Test write capability
            cursor.execute("CREATE TEMP TABLE test_write (id INTEGER);")
            cursor.execute("INSERT INTO test_write (id) VALUES (1);")
            cursor.execute("SELECT COUNT(*) FROM test_write;")
            count = cursor.fetchone()[0]

            if count == 1:
                result["writable"] = True

            conn.close()

        except sqlite3.OperationalError as e:
            result["error"] = f"Database operation failed: {str(e)}"
        except Exception as e:
            result["error"] = str(e)

        return result

    def validate_on_startup(self) -> None:
        """
        Validate configuration on application startup.
        Raises ConfigurationError if critical validation fails.
        """
        logger.info("Starting configuration validation")

        # Validate environment variables
        env_validation = self.validate_environment_variables()

        if not env_validation["valid"]:
            missing_required = env_validation["missing_required"]
            invalid_values = env_validation["invalid_values"]

            error_details = []
            if missing_required:
                missing_names = [var["name"] for var in missing_required]
                error_details.append(f"Missing required variables: {', '.join(missing_names)}")

            if invalid_values:
                invalid_details = [
                    f"{var['name']}={var['value']} ({var['error']})"
                    for var in invalid_values
                ]
                error_details.append(f"Invalid values: {'; '.join(invalid_details)}")

            raise ConfigurationError(
                message="Configuration validation failed on startup",
                required_keys=[var["name"] for var in missing_required],
            )

        logger.info(
            "Configuration validation completed",
            total_configured=env_validation["total_configured"],
            total_required=env_validation["total_required"],
            missing_optional=len(env_validation["missing_optional"]),
        )

    async def get_comprehensive_health_status(self) -> Dict[str, Any]:
        """
        Get comprehensive health status including all connectivity tests.
        
        Returns:
            Dict containing complete system health information.
        """
        health_status = {
            "status": "healthy",
            "timestamp": None,
            "configuration": {},
            "connectivity": {},
            "database": {},
            "summary": {
                "total_checks": 0,
                "passed_checks": 0,
                "failed_checks": 0,
                "warnings": 0,
            },
        }

        # Add timestamp
        from datetime import datetime

        health_status["timestamp"] = datetime.utcnow().isoformat() + "Z"

        # Configuration validation
        env_validation = self.validate_environment_variables()
        health_status["configuration"] = {
            "valid": env_validation["valid"],
            "total_configured": env_validation["total_configured"],
            "total_required": env_validation["total_required"],
            "missing_required": len(env_validation["missing_required"]),
            "missing_optional": len(env_validation["missing_optional"]),
            "invalid_values": len(env_validation["invalid_values"]),
        }

        health_status["summary"]["total_checks"] += 1
        if env_validation["valid"]:
            health_status["summary"]["passed_checks"] += 1
        else:
            health_status["summary"]["failed_checks"] += 1
            health_status["status"] = "unhealthy"

        # Connectivity tests
        connectivity_tests = await asyncio.gather(
            self.test_openai_connectivity(),
            self.test_ghl_connectivity(),
            return_exceptions=True,
        )

        # OpenAI connectivity
        openai_result = connectivity_tests[0]
        if isinstance(openai_result, Exception):
            openai_result = {"connected": False, "error": str(openai_result)}

        health_status["connectivity"]["openai"] = openai_result
        health_status["summary"]["total_checks"] += 1
        if openai_result.get("connected") and openai_result.get("authenticated"):
            health_status["summary"]["passed_checks"] += 1
        else:
            health_status["summary"]["failed_checks"] += 1
            if health_status["status"] == "healthy":
                health_status["status"] = "degraded"

        # GHL connectivity
        ghl_result = connectivity_tests[1]
        if isinstance(ghl_result, Exception):
            ghl_result = {"connected": False, "error": str(ghl_result)}

        health_status["connectivity"]["ghl"] = ghl_result
        health_status["summary"]["total_checks"] += 1
        if ghl_result.get("connected") and ghl_result.get("authenticated"):
            health_status["summary"]["passed_checks"] += 1
        else:
            health_status["summary"]["failed_checks"] += 1
            if health_status["status"] == "healthy":
                health_status["status"] = "degraded"

        # Database connectivity
        db_result = self.test_database_connectivity()
        health_status["database"] = db_result
        health_status["summary"]["total_checks"] += 1
        if db_result.get("connected") and db_result.get("writable"):
            health_status["summary"]["passed_checks"] += 1
        else:
            health_status["summary"]["warnings"] += 1
            if health_status["status"] == "healthy":
                health_status["status"] = "degraded"

        return health_status


# Global validator instance
_config_validator = None


def get_config_validator() -> ConfigurationValidator:
    """Get the global configuration validator instance."""
    global _config_validator
    if _config_validator is None:
        _config_validator = ConfigurationValidator()
    return _config_validator
