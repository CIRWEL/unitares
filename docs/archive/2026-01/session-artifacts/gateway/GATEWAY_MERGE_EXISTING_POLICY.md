# Merging Provider Config into Existing Traffic Policy

**Created:** January 1, 2026  
**Issue:** Duplicate `on_http_request` key error  
**Solution:** Merge into existing policy

---

## Problem

**Error:**
```
mapping key "on_http_request" already defined at line 1
```

**Cause:** Traffic Policy already has an `on_http_request` section. You need to **add** to it, not create a new one.

---

## Solution: Add to Existing Policy

### Step 1: View Current Traffic Policy

1. **Go to:** Gateway → Traffic Policy → Edit
2. **Copy** the entire existing YAML
3. **Note** the structure - it likely looks like:

```yaml
on_http_request:
  - type: some-existing-type
    config:
      # existing config
```

---

### Step 2: Add Provider Config to Existing Section

**You have two options:**

#### Option A: Add as Second Item in Array

**If your existing policy looks like:**
```yaml
on_http_request:
  - type: existing-type
    config:
      # existing config
```

**Add the AI Gateway as a second item:**
```yaml
on_http_request:
  - type: existing-type
    config:
      # existing config
  
  - type: ai-gateway
    config:
      providers:
        - id: "huggingface"
          base_url: "https://router.huggingface.co/v1"
          api_keys:
            - value: ${secrets.get('huggingface', 'hf_token')}
          models:
            - id: "deepseek-ai/DeepSeek-R1"
            - id: "deepseek-ai/DeepSeek-R1:fastest"
            - id: "openai/gpt-oss-120b"
```

**Key:** Notice the `-` (dash) before `type: ai-gateway` - this makes it a second item in the array.

---

#### Option B: Merge Configs (If Same Type)

**If your existing policy is already `ai-gateway` type:**
```yaml
on_http_request:
  - type: ai-gateway
    config:
      # existing providers/config
```

**Add Hugging Face to the existing `providers` array:**
```yaml
on_http_request:
  - type: ai-gateway
    config:
      providers:
        # existing providers here (if any)
        
        # Add Hugging Face provider
        - id: "huggingface"
          base_url: "https://router.huggingface.co/v1"
          api_keys:
            - value: ${secrets.get('huggingface', 'hf_token')}
          models:
            - id: "deepseek-ai/DeepSeek-R1"
            - id: "deepseek-ai/DeepSeek-R1:fastest"
            - id: "openai/gpt-oss-120b"
```

---

## Complete Example: Adding to Existing Policy

**Example: Existing policy with other rules:**

```yaml
on_http_request:
  - type: request-headers
    config:
      add:
        X-Custom-Header: "value"
  
  - type: ai-gateway
    config:
      providers:
        - id: "huggingface"
          base_url: "https://router.huggingface.co/v1"
          api_keys:
            - value: ${secrets.get('huggingface', 'hf_token')}
          models:
            - id: "deepseek-ai/DeepSeek-R1"
            - id: "deepseek-ai/DeepSeek-R1:fastest"
            - id: "openai/gpt-oss-120b"
```

**Notice:** Each rule type is a separate item in the array (each starts with `-`).

---

## Step-by-Step Fix

### 1. Open Traffic Policy Editor

- Gateway → Traffic Policy → Edit

### 2. Find Existing `on_http_request` Section

Look for:
```yaml
on_http_request:
```

### 3. Check Structure

**If it's an array (starts with `-`):**
```yaml
on_http_request:
  - type: something
```

**Add AI Gateway as new item:**
```yaml
on_http_request:
  - type: something
    # existing config
  
  - type: ai-gateway  # ← Add this as new item
    config:
      providers:
        - id: "huggingface"
          base_url: "https://router.huggingface.co/v1"
          api_keys:
            - value: ${secrets.get('huggingface', 'hf_token')}
          models:
            - id: "deepseek-ai/DeepSeek-R1"
            - id: "deepseek-ai/DeepSeek-R1:fastest"
```

**If it's already `ai-gateway` type:**
```yaml
on_http_request:
  - type: ai-gateway
    config:
      providers: []  # ← Add to this array
```

**Add provider to existing array:**
```yaml
on_http_request:
  - type: ai-gateway
    config:
      providers:
        - id: "huggingface"  # ← Add this provider
          base_url: "https://router.huggingface.co/v1"
          api_keys:
            - value: ${secrets.get('huggingface', 'hf_token')}
          models:
            - id: "deepseek-ai/DeepSeek-R1"
            - id: "deepseek-ai/DeepSeek-R1:fastest"
```

---

## Common Structures

### Structure 1: Multiple Rule Types

```yaml
on_http_request:
  - type: request-headers
    config:
      add:
        Header: "value"
  
  - type: ai-gateway  # ← Add here
    config:
      providers:
        - id: "huggingface"
          # ... config
```

### Structure 2: Single AI Gateway

```yaml
on_http_request:
  - type: ai-gateway
    config:
      providers:
        - id: "huggingface"  # ← Add provider here
          # ... config
```

### Structure 3: Empty/New Policy

```yaml
on_http_request:
  - type: ai-gateway  # ← This is fine if policy is empty
    config:
      providers:
        - id: "huggingface"
          # ... config
```

---

## Quick Fix Template

**If you're not sure of the structure, use this safe approach:**

1. **Copy entire existing policy**
2. **Add AI Gateway as new array item:**

```yaml
# Your existing policy here (keep as-is)
on_http_request:
  - type: existing-type
    config:
      # existing config

# Add this as a NEW item (notice the dash)
  - type: ai-gateway
    config:
      providers:
        - id: "huggingface"
          base_url: "https://router.huggingface.co/v1"
          api_keys:
            - value: ${secrets.get('huggingface', 'hf_token')}
          models:
            - id: "deepseek-ai/DeepSeek-R1"
            - id: "deepseek-ai/DeepSeek-R1:fastest"
            - id: "openai/gpt-oss-120b"
```

**Key:** The `-` (dash) before `type: ai-gateway` makes it a second item, not a duplicate key.

---

## Validation

**After saving, verify:**

1. **No duplicate `on_http_request` keys** (should only appear once)
2. **Array items properly indented** (each `-` at same level)
3. **YAML syntax valid** (colons, dashes, indentation)

**Test:**
```bash
curl https://unitares.ngrok.io/v1/models \
  -H "Authorization: Bearer $NGROK_API_KEY"
```

---

## Troubleshooting

### Still Getting "Already Defined" Error

**Problem:** YAML structure incorrect

**Fix:**
1. Check indentation (use spaces, not tabs)
2. Verify only ONE `on_http_request:` key at top level
3. All rule types should be array items (start with `-`)

### "Invalid YAML" Error

**Problem:** Indentation or syntax issue

**Fix:**
1. Use 2 spaces for indentation (not tabs)
2. Verify colons after keys
3. Check dashes are properly aligned

---

## Example: Complete Merged Policy

**Before (existing):**
```yaml
on_http_request:
  - type: request-headers
    config:
      add:
        X-Forwarded-For: "${remote_addr}"
```

**After (merged):**
```yaml
on_http_request:
  - type: request-headers
    config:
      add:
        X-Forwarded-For: "${remote_addr}"
  
  - type: ai-gateway
    config:
      providers:
        - id: "huggingface"
          base_url: "https://router.huggingface.co/v1"
          api_keys:
            - value: ${secrets.get('huggingface', 'hf_token')}
          models:
            - id: "deepseek-ai/DeepSeek-R1"
            - id: "deepseek-ai/DeepSeek-R1:fastest"
            - id: "openai/gpt-oss-120b"
```

**Notice:** Two items in the array, each starting with `-`.

---

**Status:** ✅ Fix for duplicate key error  
**Solution:** Add as array item, not duplicate key

