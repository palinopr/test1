#!/usr/bin/env python3
"""
Test script for LangSmith configuration to verify setup works correctly.
"""

import os
import sys
sys.path.append('src')

from src.config.langsmith_config import (
    initialize_langsmith, 
    get_langsmith_config, 
    setup_logging
)

def test_langsmith_config():
    """Test LangSmith configuration with various scenarios."""
    print("Testing LangSmith Configuration...")
    print("=" * 50)
    
    # Setup logging first
    setup_logging()
    
    # Test without API key (should enable fallback mode)
    print("\n1. Testing without API key (fallback mode):")
    os.environ.pop('LANGSMITH_API_KEY', None)
    success = initialize_langsmith()
    config = get_langsmith_config()
    status = config.get_status()
    
    print(f"   Initialization success: {success}")
    print(f"   Enabled: {status['enabled']}")
    print(f"   Fallback mode: {status['fallback_mode']}")
    print(f"   Project name: {status['project_name']}")
    
    # Test with invalid API key
    print("\n2. Testing with invalid API key:")
    os.environ['LANGSMITH_API_KEY'] = 'invalid_key_test'
    config_invalid = get_langsmith_config()
    config_invalid.initialize()
    status_invalid = config_invalid.get_status()
    
    print(f"   Enabled: {status_invalid['enabled']}")
    print(f"   Fallback mode: {status_invalid['fallback_mode']}")
    
    # Test callback manager
    print("\n3. Testing callback manager:")
    callback_manager = config.get_callback_manager()
    print(f"   Callback manager created: {callback_manager is not None}")
    print(f"   Number of callbacks: {len(callback_manager.handlers)}")
    
    # Test run configuration
    print("\n4. Testing run configuration:")
    run_config = config.get_run_config(
        tags=["test"],
        metadata={"test": "value"}
    )
    print(f"   Run config keys: {list(run_config.keys())}")
    
    print("\n" + "=" * 50)
    print("LangSmith configuration test completed!")
    print("The system will work in fallback mode if LangSmith is not available.")

if __name__ == "__main__":
    test_langsmith_config()
