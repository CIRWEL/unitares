# Troubleshooting: Secret Still Not Found

**Created:** January 1, 2026  
**Issue:** Secret created but gateway still can't find it  
**Status:** Diagnostic Guide

---

## Problem

**Error persists:**
```
Failed to resolve secrets.get('huggingface', 'hf_token')
ERROR: sql: no rows in result set
```

**Even after creating the secret.**

---

## Possible Causes

### Cause 1: Secret Name Mismatch

**Check exact names match:**

**In Traffic Policy:**
```yaml
${secrets.get('huggingface', 'hf_token')}
```

**In Secrets Dashboard:**
- Provider: Must be exactly `huggingface` (case-sensitive)
- Key: Must be exactly `hf_token` (case-sensitive)

**Common mistakes:**
- `HuggingFace` vs `huggingface` (case mismatch)
- `hf-token` vs `hf_token` (dash vs underscore)
- Extra spaces

---

### Cause 2: Traffic Policy Not Reloaded

**After creating secret, Traffic Policy might need to be saved again:**

1. Go to: Gateway → Traffic Policy → Edit
2. **Don't change anything** - just click "Save" again
3. This forces gateway to reload and pick up the new secret

---

### Cause 3: Wrong Secret Format

**Verify secret format in dashboard:**

**Correct format:**
- Provider: `huggingface` (lowercase, no spaces)
- Key: `hf_token` (lowercase, underscore)
- Value: `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`

**Check:**
- No extra spaces
- No quotes around values
- Exact spelling

---

### Cause 4: Secret in Wrong Account/Region

**Verify:**
- Secret is in the same ngrok account as gateway
- Secret is accessible to the gateway
- No account/region restrictions

---

## Step-by-Step Verification

### Step 1: Verify Secret Exists

**In Dashboard:**
1. Go to: https://dashboard.ngrok.com/secrets
2. **Look for:** `huggingface/hf_token`
3. **Verify:**
   - Provider: `huggingface` (exact match)
   - Key: `hf_token` (exact match)
   - Value: Starts with `hf_`

---

### Step 2: Check Traffic Policy Reference

**In Traffic Policy, verify:**
```yaml
api_keys:
  - value: ${secrets.get('huggingface', 'hf_token')}
```

**Must match exactly:**
- First parameter: `'huggingface'` (matches Provider)
- Second parameter: `'hf_token'` (matches Key)
- Quotes: Single quotes (not double)

---

### Step 3: Re-save Traffic Policy

**Even if unchanged:**

1. Go to: Gateway → Traffic Policy → Edit
2. **Click "Save"** (forces reload)
3. Wait a few seconds for propagation

---

### Step 4: Test Again

```bash
curl https://unitares.ngrok.io/v1/models \
  -H "Authorization: Bearer $NGROK_API_KEY"
```

---

## Alternative: Use Direct API Key (Quick Fix)

**If secret still doesn't work, use direct API key:**

**Update Traffic Policy:**
```yaml
on_http_request:
  - actions:
      - type: ai-gateway
        config:
          providers:
            - id: "huggingface"
              base_url: "https://router.huggingface.co/v1"
              api_keys:
                - value: "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"  # Direct value
              models:
                - id: "deepseek-ai/DeepSeek-R1"
                - id: "deepseek-ai/DeepSeek-R1:fastest"
```

**This bypasses secrets entirely and works immediately.**

---

## Quick Diagnostic

**Run this to check secret:**

```bash
# List secrets (if you have ngrok CLI)
ngrok api secrets list

# Or check via API
curl https://api.ngrok.com/secrets \
  -H "Authorization: Bearer $NGROK_API_KEY" \
  -H "ngrok-version: 2" | jq '.'
```

**Look for:** `huggingface/hf_token` in the list.

---

## Recommendation

**If secret still doesn't work after verification:**

**Use direct API key** (Option 2 from previous guide):
- Works immediately
- No secret lookup needed
- Less secure (key visible in policy) but functional

**Then troubleshoot secret separately** (can migrate back later).

---

**Status:** Diagnostic guide  
**Next:** Verify secret names match exactly, then re-save Traffic Policy

