# Duplicate ngrok Endpoints Fix

**Created:** January 1, 2026  
**Status:** Fixed - removed duplicate processes

---

## Problem

**Two ngrok processes running:**
1. `ngrok http --url=unitares.ngrok.io --pooling-enabled 8765` ✅ (custom domain)
2. `ngrok http 8765` ❌ (random URL, duplicate)

**Both pointing to:** `localhost:8765`

**Result:** Conflicts, confusion, and the Traffic Policy still blocking requests.

---

## Solution

**Keep only the custom domain tunnel:**

```bash
# Stop all ngrok processes
pkill -f "ngrok http"

# Start only the custom domain tunnel
ngrok http --url=unitares.ngrok.io --pooling-enabled 8765
```

---

## Remaining Issue

**Traffic Policy is still active** on `unitares.ngrok.io`:
- Intercepts ALL requests
- Routes them as AI Gateway calls
- Breaks MCP requests

**Fix:** Remove Traffic Policy in ngrok dashboard:
1. Go to: https://dashboard.ngrok.com/endpoints
2. Click: `https://unitares.ngrok.io`
3. Remove/clear Traffic Policy
4. Save

---

## Verification

**After removing Traffic Policy:**

```bash
# Should return JSON, not HTML error
curl https://unitares.ngrok.io/health

# Should return MCP server response
curl https://unitares.ngrok.io/mcp
```

---

**Status:** Duplicate processes removed, Traffic Policy still needs removal  
**Action:** Remove Traffic Policy in ngrok dashboard

