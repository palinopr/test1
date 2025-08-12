<general_rules>
When developing code for this repository, follow these essential practices:

- **Search Before Creating**: Always search existing modules in `src/agents/`, `src/tools/`, `src/state/`, `src/webhooks/`, and `src/config/` directories before creating new functions or classes. Reuse existing functionality when possible.

- **Code Formatting**: Use Black formatter with line-length 88 for all Python code. Configuration is already set in `pyproject.toml`. Run `black src/` to format code. Pre-commit hooks are configured to automatically run Black and isort on commit.

- **Import Organization**: Use isort for import sorting, configured to be compatible with Black. Run `isort src/` to organize imports properly.

- **Module Patterns**: Follow the established architectural patterns:
  - `src/agents/`: LangGraph StateGraph workflows and qualification logic
  - `src/tools/`: GHL API integration utilities and LangChain tools
  - `src/state/`: Conversation state management and persistence
  - `src/webhooks/`: Webhook handlers for Meta/GHL integration
  - `src/config/`: Configuration management, validation, and LangSmith tracing setup

- **Environment Variables**: Always use environment variables for API keys and configuration. Reference `.env.example` for required variables. Use the configuration validation system in `src/config/validation.py` to ensure proper setup.

- **Logging**: Use structured logging with `structlog` following the patterns established in existing modules. Include relevant context like `contact_id`, `thread_id`, and `conversation_id` in log messages.

- **Error Handling**: Use the custom exception classes defined in `src/exceptions.py` for consistent error handling. Implement comprehensive error handling with fallback modes, especially for external API integrations (OpenAI, GHL, LangSmith). All exceptions should include descriptive messages and relevant context for debugging.

- **Development Setup**: Use the provided `setup-dev.sh` script to automatically set up the development environment with all required dependencies and tools.

- **Code Quality**: Run pre-commit hooks before committing code. Use `pre-commit run --all-files` to check all files at once.
</general_rules>

<repository_structure>
This is a FastAPI-based webhook system for GHL (Go High Level) customer qualification using LangGraph for conversational AI workflows.

**Main Application Flow**: Meta Ad → Go High Level → GHL Webhook → LangGraph Agent → Response via GHL Tools

**Core Components**:
- **FastAPI Server** (`src/main.py`): Main application server with webhook endpoints, comprehensive health checks, and API routes
- **Qualification Agent** (`src/agents/`): LangGraph StateGraph implementation for multi-stage customer qualification conversations
- **GHL Integration** (`src/tools/`): Comprehensive Go High Level API wrapper tools for messaging, contact management, and CRM operations
- **State Management** (`src/state/`): Persistent conversation state using SQLite database with qualification tracking
- **Webhook Handlers** (`src/webhooks/`): Meta webhook integration for processing inbound messages and contact events
- **Configuration** (`src/config/`): Environment validation, LangSmith tracing setup with fallback support, and structured logging configuration
- **Exception Handling** (`src/exceptions.py`): Custom exception classes for consistent error handling across the application

**Key Files**:
- `conversation_states.db`: SQLite database for persistent conversation state
- `langgraph.json`: LangGraph Cloud deployment configuration
- `setup-dev.sh`: Development environment setup script
- `.pre-commit-config.yaml`: Pre-commit hooks for code quality
- `examples/`: Sample API responses, webhook payloads, and conversation flows
- Root-level test files: Custom test scripts for each major component

**Development Tools**:
- **Code Quality**: Black formatter (line-length 88), isort for import sorting, pre-commit hooks
- **Testing**: Custom test scripts with fallback modes for missing API keys
- **Configuration**: Comprehensive environment variable validation and connectivity testing
- **Error Handling**: Structured exception hierarchy with detailed logging

**Deployment Support**: Docker, docker-compose for local development, and LangGraph Cloud for production deployment.
</repository_structure>

<dependencies_and_installation>
**Requirements**: Python 3.9 or higher

**Quick Development Setup**:
1. Run the automated setup script: `./setup-dev.sh`
   - This script handles all installation steps automatically
   - Installs core and development dependencies
   - Sets up environment configuration
   - Validates that all required dev tools are properly installed

**Manual Installation Steps**:
1. Install core dependencies: `pip install -r requirements.txt`
2. Copy environment template: `cp .env.example .env`
3. Configure required API keys in `.env` file (OpenAI, GHL, LangSmith)
4. For development, install optional dependencies: `pip install -e .[dev]` (includes pytest, black, isort, pre-commit)
5. Install pre-commit hooks: `pre-commit install`

**Key Dependencies**:
- **LangGraph/LangChain**: Core AI workflow and conversation management
- **FastAPI + Uvicorn**: Web server and API framework
- **OpenAI**: Language model integration
- **Structlog**: Structured logging
- **HTTPx/Requests**: HTTP client for API integrations
- **Pydantic**: Data validation and serialization

**Development Dependencies** (in `pyproject.toml`):
- pytest, pytest-asyncio for testing
- black, isort for code formatting
- Additional dev tools for code quality

**Environment Configuration**: All sensitive configuration is managed through environment variables. Use `.env.example` as a template and ensure all required API keys are properly configured before running the application.
</dependencies_and_installation>

<testing_instructions>
This repository uses a custom test script approach rather than standard pytest framework patterns.

**Test Structure**:
- Test files are located in the root directory with `test_` prefix
- Each major component has its own test file: `test_qualification_agent.py`, `test_ghl_tools.py`, `test_conversation_state.py`, `test_meta_webhook.py`, `test_main_app.py`

**Running Tests**:
- Run all tests: `python -m pytest`
- Run individual test files directly: `python test_qualification_agent.py`
- Tests are designed to work with or without API keys (fallback/mock modes)

**Test Coverage**:
- **Agent Testing**: LangGraph workflow validation, conversation flow testing, qualification logic
- **Tools Testing**: GHL API integration, tool functionality, error handling
- **State Testing**: Conversation persistence, state management, qualification scoring
- **Webhook Testing**: Meta webhook handling, payload processing, integration flows
- **Application Testing**: FastAPI endpoints, health checks, error handlers

**Testing Environment**: Tests are designed to be runnable in development environments without requiring live API connections. Mock modes and fallback handling ensure tests can run even with missing API keys.
</testing_instructions>

<pull_request_formatting>
</pull_request_formatting>



