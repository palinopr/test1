# Deployment Guide for GHL Customer Qualification Webhook

This guide provides comprehensive instructions for deploying the AI-powered customer qualification webhook system for Go High Level using LangGraph.

## Table of Contents

- [Overview](#overview)
- [Deployment Options](#deployment-options)
- [Environment Configuration](#environment-configuration)
- [LangGraph Cloud Deployment](#langgraph-cloud-deployment)
- [Docker Deployment](#docker-deployment)
- [Local Development](#local-development)
- [Troubleshooting](#troubleshooting)
- [Monitoring and Health Checks](#monitoring-and-health-checks)
- [Security Considerations](#security-considerations)

## Overview

The system implements the following flow:
```
Meta Ad → Go High Level (GHL) → GHL Webhook → LangGraph Agent → Response via GHL Tools
```

### Architecture Components

- **FastAPI Application Server** - Main webhook endpoint and API server
- **LangGraph Qualification Agent** - AI-powered customer qualification using StateGraph
- **Go High Level Integration** - Tools for messaging, contact management, and CRM operations
- **LangSmith Tracing** - Optional monitoring and debugging (with fallback support)
- **Conversation State Management** - Persistent state across webhook calls

## Deployment Options

### 1. LangGraph Cloud (Recommended for Production)

LangGraph Cloud provides managed deployment with automatic scaling and monitoring.

**Prerequisites:**
- LangGraph Cloud account
- LangSmith API key (optional but recommended)

**Deployment Steps:**
```bash
# 1. Install LangGraph CLI
pip install langgraph-cli

# 2. Login to LangGraph Cloud
langgraph login

# 3. Deploy from project root
langgraph deploy
```

### 2. Docker Deployment

Containerized deployment suitable for any Docker-compatible environment.

**Prerequisites:**
- Docker and Docker Compose installed
- Environment variables configured

### 3. Local Development

Direct Python execution for development and testing.

**Prerequisites:**
- Python 3.9+ installed
- All dependencies installed via pip

## Environment Configuration

### Required Environment Variables

Create a `.env` file based on `.env.example`:

```bash
# Core Application
APP_HOST=0.0.0.0
APP_PORT=8000
APP_DEBUG=false
LOG_LEVEL=INFO

# OpenAI Configuration (Required)
OPENAI_API_KEY=your_openai_api_key_here

# Go High Level Configuration (Required)
GHL_API_KEY=your_ghl_api_key_here
GHL_BASE_URL=https://services.leadconnectorhq.com
GHL_WEBHOOK_VERIFY_TOKEN=your_webhook_verify_token_here

# LangSmith Configuration (Optional)
LANGSMITH_API_KEY=your_langsmith_api_key_here
LANGSMITH_PROJECT=ghl-qualification-webhook
LANGSMITH_TRACING=true

# Database Configuration
DATABASE_URL=sqlite:///./data/conversation_states.db

# Security
SECRET_KEY=your_secret_key_here_change_in_production
TRUSTED_HOSTS=your-domain.com,localhost
```

### Environment Variable Details

#### Required Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `OPENAI_API_KEY` | OpenAI API key for the qualification agent | `sk-...` |
| `GHL_API_KEY` | Go High Level API key | `ghl_...` |
| `GHL_WEBHOOK_VERIFY_TOKEN` | Token for webhook verification | `secure_token_123` |

#### Optional Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `LANGSMITH_API_KEY` | LangSmith API key for tracing | None (fallback mode) |
| `LANGSMITH_TRACING` | Enable/disable tracing | `true` |
| `APP_DEBUG` | Enable debug mode | `false` |
| `LOG_LEVEL` | Logging level | `INFO` |

## LangGraph Cloud Deployment

### Configuration File

The `langgraph.json` file configures LangGraph Cloud deployment:

```json
{
  "dependencies": ["."],
  "graphs": {
    "qualification_agent": "./src/agents/qualification_agent.py:get_qualification_agent"
  },
  "env": ".env",
  "dockerfile_lines": [
    "RUN apt-get update && apt-get install -y sqlite3",
    "RUN pip install --no-cache-dir -r requirements.txt"
  ],
  "python_version": "3.11"
}
```

### Deployment Process

1. **Prepare Environment**
   ```bash
   # Ensure all environment variables are set
   cp .env.example .env
   # Edit .env with your actual values
   ```

2. **Deploy to LangGraph Cloud**
   ```bash
   langgraph deploy
   ```

3. **Configure Webhook URL**
   - Get your deployment URL from LangGraph Cloud
   - Configure GHL webhook URL: `https://your-deployment-url.com/webhook/ghl`

### LangGraph Cloud Troubleshooting

#### Common Issues

**1. Deployment Fails with "Invalid License" Error**
```
Error: INVALID_LICENSE
```
**Solution:** Verify your LangGraph Cloud subscription and API key.

**2. Graph Recursion Limit Exceeded**
```
Error: GRAPH_RECURSION_LIMIT
```
**Solution:** Check for infinite loops in conversation logic. Increase recursion limit if needed.

**3. Concurrent Graph Update Error**
```
Error: INVALID_CONCURRENT_GRAPH_UPDATE
```
**Solution:** Ensure proper state management and avoid concurrent updates to the same conversation thread.

## Docker Deployment

### Using Docker Compose (Recommended)

1. **Build and Start Services**
   ```bash
   # Build the application
   docker-compose build
   
   # Start services
   docker-compose up -d
   
   # View logs
   docker-compose logs -f ghl-qualification-webhook
   ```

2. **Health Check**
   ```bash
   curl http://localhost:8000/health
   ```

### Using Docker Directly

1. **Build Image**
   ```bash
   docker build -t ghl-qualification-webhook .
   ```

2. **Run Container**
   ```bash
   docker run -d \
     --name ghl-webhook \
     -p 8000:8000 \
     --env-file .env \
     -v $(pwd)/data:/app/data \
     ghl-qualification-webhook
   ```

### Docker Troubleshooting

#### Common Issues

**1. Container Exits Immediately**
```bash
# Check logs
docker logs ghl-qualification-webhook

# Common causes:
# - Missing required environment variables
# - Invalid OpenAI API key
# - Port already in use
```

**2. Health Check Failures**
```bash
# Check container health
docker ps

# If unhealthy, check logs and environment variables
```

**3. Permission Issues with Volumes**
```bash
# Fix volume permissions
sudo chown -R 1000:1000 ./data ./logs
```

## Local Development

### Setup

1. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure Environment**
   ```bash
   cp .env.example .env
   # Edit .env with your values
   ```

3. **Run Application**
   ```bash
   python -m src.main
   ```

### Development Tools

**Start with Auto-Reload**
```bash
uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```

**Run Tests**
```bash
# Test individual components
python test_langsmith_config.py
python test_ghl_tools.py
python test_qualification_agent.py
python test_conversation_state.py
python test_main_app.py

# Test webhook functionality
python test_meta_webhook.py
```

## Troubleshooting

### LangSmith Integration Issues

#### Problem: LangSmith Tracing Not Working
**Symptoms:**
- No traces appearing in LangSmith dashboard
- "LangSmith fallback mode enabled" in logs

**Solutions:**
1. **Check API Key**
   ```bash
   # Verify API key is set
   echo $LANGSMITH_API_KEY
   ```

2. **Check Network Connectivity**
   ```bash
   # Test LangSmith API connectivity
   curl -H "Authorization: Bearer $LANGSMITH_API_KEY" \
        https://api.smith.langchain.com/info
   ```

3. **Check Project Configuration**
   - Ensure `LANGSMITH_PROJECT` matches your LangSmith project name
   - Verify project exists in your LangSmith account

#### Problem: License Errors
**Error:** `INVALID_LICENSE`

**Solutions:**
1. Verify LangSmith subscription status
2. Check API key permissions
3. Contact LangSmith support if issue persists

### Go High Level Integration Issues

#### Problem: GHL API Authentication Failures
**Symptoms:**
- "Unauthorized - check GHL API key" errors
- 401/403 responses from GHL API

**Solutions:**
1. **Verify API Key**
   ```bash
   # Test GHL API connectivity
   curl -H "Authorization: Bearer $GHL_API_KEY" \
        https://services.leadconnectorhq.com/contacts
   ```

2. **Check API Permissions**
   - Ensure API key has required scopes
   - Verify account has necessary permissions

3. **Check Rate Limits**
   - GHL has rate limits that may cause temporary failures
   - Implement retry logic if needed

#### Problem: Webhook Verification Failures
**Symptoms:**
- GHL webhook setup fails
- "Verification failed" errors

**Solutions:**
1. **Check Webhook URL**
   - Ensure URL is publicly accessible
   - Verify HTTPS is used (required by GHL)

2. **Verify Token**
   ```bash
   # Test webhook verification
   curl "https://your-domain.com/webhook/ghl?challenge=test&verify_token=$GHL_WEBHOOK_VERIFY_TOKEN"
   ```

### OpenAI Integration Issues

#### Problem: OpenAI API Failures
**Symptoms:**
- "OPENAI_API_KEY environment variable is required" errors
- Agent initialization failures

**Solutions:**
1. **Verify API Key**
   ```bash
   # Test OpenAI API
   curl -H "Authorization: Bearer $OPENAI_API_KEY" \
        https://api.openai.com/v1/models
   ```

2. **Check Usage Limits**
   - Verify account has sufficient credits
   - Check rate limits and quotas

3. **Model Availability**
   - Ensure requested model (gpt-4o-mini) is available
   - Check for model deprecations

### Database Issues

#### Problem: SQLite Database Errors
**Symptoms:**
- "Database locked" errors
- Conversation state not persisting

**Solutions:**
1. **Check File Permissions**
   ```bash
   # Ensure database directory is writable
   chmod 755 ./data
   touch ./data/conversation_states.db
   ```

2. **Database Corruption**
   ```bash
   # Check database integrity
   sqlite3 ./data/conversation_states.db "PRAGMA integrity_check;"
   
   # Recreate if corrupted
   rm ./data/conversation_states.db
   # Restart application to recreate
   ```

### Memory and Performance Issues

#### Problem: High Memory Usage
**Solutions:**
1. **Adjust Cache Settings**
   - Reduce conversation state cache size
   - Implement more aggressive cleanup

2. **Database Optimization**
   ```bash
   # Clean up old conversations
   curl -X POST http://localhost:8000/api/cleanup
   ```

#### Problem: Slow Response Times
**Solutions:**
1. **Check Component Health**
   ```bash
   curl http://localhost:8000/health/detailed
   ```

2. **Optimize Database**
   - Add indexes for frequently queried fields
   - Implement connection pooling

## Monitoring and Health Checks

### Health Check Endpoints

**Basic Health Check**
```bash
curl http://localhost:8000/health
# Response: "OK"
```

**Detailed Health Check**
```bash
curl http://localhost:8000/health/detailed
# Returns JSON with component status
```

### Monitoring Metrics

The application provides several monitoring endpoints:

- `/health` - Basic health status
- `/health/detailed` - Component-level health information
- `/api/conversations` - Active conversation metrics

### Log Monitoring

**Application Logs**
```bash
# Docker Compose
docker-compose logs -f ghl-qualification-webhook

# Docker
docker logs -f ghl-qualification-webhook

# Local
tail -f logs/application.log
```

**Log Levels**
- `ERROR` - Critical errors requiring attention
- `WARNING` - Issues that don't stop operation
- `INFO` - General operational information
- `DEBUG` - Detailed debugging information

## Security Considerations

### API Security

1. **Environment Variables**
   - Never commit API keys to version control
   - Use secure secret management in production
   - Rotate keys regularly

2. **Webhook Security**
   - Always use HTTPS for webhook URLs
   - Implement webhook signature verification
   - Use strong verification tokens

3. **Network Security**
   - Configure `TRUSTED_HOSTS` appropriately
   - Use firewall rules to restrict access
   - Implement rate limiting if needed

### Container Security

1. **Non-Root User**
   - Application runs as non-root user in container
   - Minimal system dependencies installed

2. **Image Security**
   - Based on official Python slim image
   - Regular security updates applied
   - No unnecessary packages installed

### Data Security

1. **Database Security**
   - SQLite database with appropriate file permissions
   - Consider encryption for sensitive data
   - Regular backups recommended

2. **Conversation Data**
   - Customer information handled securely
   - Automatic cleanup of old conversations
   - GDPR compliance considerations

## Production Deployment Checklist

### Pre-Deployment

- [ ] All environment variables configured
- [ ] API keys tested and validated
- [ ] Webhook URLs configured in GHL
- [ ] SSL certificates installed
- [ ] Monitoring and alerting configured
- [ ] Backup procedures established

### Post-Deployment

- [ ] Health checks passing
- [ ] Webhook verification successful
- [ ] Test conversation flow end-to-end
- [ ] Monitor logs for errors
- [ ] Verify LangSmith tracing (if enabled)
- [ ] Performance testing completed

### Ongoing Maintenance

- [ ] Regular log monitoring
- [ ] Database cleanup scheduling
- [ ] API key rotation
- [ ] Security updates
- [ ] Performance optimization
- [ ] Backup verification

## Support and Resources

### Documentation
- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [Go High Level API Documentation](https://highlevel.stoplight.io/)
- [OpenAI API Documentation](https://platform.openai.com/docs)

### Troubleshooting Resources
- Check application logs first
- Use detailed health check endpoint
- Test individual components separately
- Verify environment variable configuration

### Getting Help
- Review this deployment guide
- Check the troubleshooting section
- Test with minimal configuration
- Contact support with specific error messages and logs
