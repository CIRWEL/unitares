# Fixed: Indentation Issue

**Created:** January 1, 2026  
**Issue:** `api_keys` indentation incorrect  
**Status:** Fixed

---

## Problem

**Your config had:**
```yaml
- id: "huggingface"
  base_url: "https://router.huggingface.co/v1"

api_keys:  # ← Wrong indentation (not aligned)
  - value: "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"

  models:  # ← Also wrong indentation
```

**Issue:** `api_keys` and `models` were not properly indented under the provider.

---

## Correct Format

**Fixed configuration:**

```yaml
on_http_request:
  - actions:
      - type: ai-gateway
        config:
          providers:
            - id: "huggingface"
              base_url: "https://router.huggingface.co/v1"
              api_keys:
                - value: "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"
              models:
                - id: "deepseek-ai/DeepSeek-R1"
                - id: "deepseek-ai/DeepSeek-R1:fastest"
                - id: "openai/gpt-oss-120b"
```

**Key points:**
- `api_keys` aligns with `base_url` (same indentation level)
- `models` aligns with `api_keys` (same indentation level)
- All are children of the provider (`- id: "huggingface"`)

---

## Indentation Guide

**YAML uses 2-space indentation:**

```yaml
providers:
  - id: "huggingface"           # 2 spaces
    base_url: "..."              # 4 spaces (child of id)
    api_keys:                    # 4 spaces (child of id)
      - value: "..."             # 6 spaces (child of api_keys)
    models:                      # 4 spaces (child of id)
      - id: "..."                # 6 spaces (child of models)
```

---

## Copy-Paste Ready Config

**Use this exact configuration:**

```yaml
on_http_request:
  - actions:
      - type: ai-gateway
        config:
          providers:
            - id: "huggingface"
              base_url: "https://router.huggingface.co/v1"
              api_keys:
                - value: "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"
              models:
                - id: "deepseek-ai/DeepSeek-R1"
                - id: "deepseek-ai/DeepSeek-R1:fastest"
                - id: "openai/gpt-oss-120b"
```

---

## After Saving

**Test the gateway:**

```bash
curl https://unitares.ngrok.io/v1/models \
  -H "Authorization: Bearer $NGROK_API_KEY"
```

**Expected:** List of models (no 400 error).

---

**Status:** ✅ Configuration fixed  
**Action:** Copy corrected YAML above and save in Traffic Policy

