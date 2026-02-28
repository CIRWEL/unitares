#!/usr/bin/env python3
"""
Audit error messages for standardization

Identifies error responses that could use standardized helpers from error_helpers.py
"""

import sys
import re
from pathlib import Path
from collections import defaultdict

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

def audit_error_messages():
    """Audit error message usage across handlers"""
    
    handlers_dir = Path(__file__).parent.parent.parent / "src" / "mcp_handlers"
    
    # Patterns to find
    error_pattern = re.compile(r'error_response\s*\([^)]+\)', re.MULTILINE)
    helper_pattern = re.compile(r'from.*error_helpers import|from \.error_helpers import')
    
    # Standardized helpers available
    standard_helpers = {
        'agent_not_found_error',
        'agent_not_registered_error',
        'authentication_error',
        'authentication_required_error',
        'ownership_error',
        'rate_limit_error',
        'timeout_error',
        'invalid_parameters_error',
        'validation_error',
        'resource_not_found_error',
        'system_error'
    }
    
    # Common error patterns that could use helpers
    error_patterns = {
        'agent.*not found': 'agent_not_found_error',
        'agent.*not registered': 'agent_not_registered_error',
        'authentication.*failed': 'authentication_error',
        'api key.*required': 'authentication_required_error',
        'unauthorized': 'ownership_error',
        'rate limit': 'rate_limit_error',
        'timeout': 'timeout_error',
        'invalid.*parameter': 'invalid_parameters_error',
        'validation': 'validation_error',
        'not found': 'resource_not_found_error',
        'system error': 'system_error',
    }
    
    results = defaultdict(list)
    total_errors = 0
    files_with_helpers = set()
    
    for py_file in handlers_dir.rglob("*.py"):
        if py_file.name == "__init__.py":
            continue
            
        content = py_file.read_text()
        
        # Check if file imports error_helpers
        if helper_pattern.search(content):
            files_with_helpers.add(py_file.relative_to(handlers_dir.parent))
        
        # Find all error_response calls
        errors = error_pattern.findall(content)
        if errors:
            total_errors += len(errors)
            relative_path = py_file.relative_to(handlers_dir.parent)
            
            # Check each error for potential standardization
            for error in errors:
                error_lower = error.lower()
                suggested_helper = None
                
                for pattern, helper in error_patterns.items():
                    if re.search(pattern, error_lower):
                        suggested_helper = helper
                        break
                
                results[relative_path].append({
                    'error': error[:100] + '...' if len(error) > 100 else error,
                    'suggested_helper': suggested_helper
                })
    
    # Print report
    print("=" * 80)
    print("ERROR MESSAGE STANDARDIZATION AUDIT")
    print("=" * 80)
    print()
    print(f"Total error_response() calls found: {total_errors}")
    print(f"Files using error_helpers: {len(files_with_helpers)}")
    print()
    
    if results:
        print("Files with error responses:")
        print("-" * 80)
        
        for file_path, errors in sorted(results.items()):
            uses_helpers = file_path in files_with_helpers
            helper_status = "✓ Uses helpers" if uses_helpers else "✗ No helpers imported"
            
            print(f"\n{file_path} ({len(errors)} errors) - {helper_status}")
            
            # Group by suggested helper
            by_helper = defaultdict(list)
            no_suggestion = []
            
            for err in errors:
                if err['suggested_helper']:
                    by_helper[err['suggested_helper']].append(err['error'])
                else:
                    no_suggestion.append(err['error'])
            
            if by_helper:
                print("  Suggested improvements:")
                for helper, error_list in sorted(by_helper.items()):
                    print(f"    → Use {helper}() for {len(error_list)} error(s)")
                    if len(error_list) <= 3:
                        for e in error_list:
                            print(f"      - {e}")
            
            if no_suggestion:
                print(f"  {len(no_suggestion)} error(s) without clear standardization pattern")
    
    print()
    print("=" * 80)
    print("RECOMMENDATIONS:")
    print("=" * 80)
    print()
    print("1. Files without error_helpers import should add:")
    print("   from .error_helpers import (helpers...)")
    print()
    print("2. Common patterns to standardize:")
    print("   - Agent not found → agent_not_found_error()")
    print("   - Authentication failures → authentication_error()")
    print("   - Missing API keys → authentication_required_error()")
    print("   - System errors → system_error()")
    print()
    print("3. Priority order:")
    print("   - High-frequency errors (agent_not_found, auth errors)")
    print("   - Security-critical errors (authentication, ownership)")
    print("   - User-facing errors (validation, parameters)")
    print()


if __name__ == "__main__":
    audit_error_messages()

