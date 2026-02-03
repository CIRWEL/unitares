# Hugging Face Token Setup Guide

**Created:** January 1, 2026  
**Status:** Quick Reference  
**Priority:** High

---

## Quick Steps to Get HF Token

### Step 1: Sign Up / Log In

1. Go to: **https://huggingface.co/join**
2. Sign up (free account) or log in if you already have one

### Step 2: Create Access Token

1. Go to: **https://huggingface.co/settings/tokens**
2. Click **"New token"** button
3. Fill in:
   - **Name:** `unitares-inference` (or any name you prefer)
   - **Type:** Select **"Read"** (for Inference Providers)
   - **Permissions:** ✅ Check **"Make calls to Inference Providers"**
4. Click **"Generate token"**
5. **Copy the token immediately** (you won't see it again!)

**Token looks like:** `hf_abc123def456ghi789jkl012mno345pqr678stu901vwx234yz`

---

### Step 3: Set Environment Variable

**Option A: Export in Terminal (Temporary)**
```bash
export HF_TOKEN=hf_abc123def456ghi789jkl012mno345pqr678stu901vwx234yz
```

**Option B: Add to `.env` File (Permanent)**
```bash
# Add to your .env file in project root
echo "HF_TOKEN=hf_abc123def456ghi789jkl012mno345pqr678stu901vwx234yz" >> .env
```

**Option C: Add to Shell Profile (System-wide)**
```bash
# For zsh (macOS default)
echo 'export HF_TOKEN=hf_abc123def456ghi789jkl012mno345pqr678stu901vwx234yz' >> ~/.zshrc
source ~/.zshrc

# For bash
echo 'export HF_TOKEN=hf_abc123def456ghi789jkl012mno345pqr678stu901vwx234yz' >> ~/.bashrc
source ~/.bashrc
```

---

### Step 4: Verify Token is Set

```bash
# Check if token is set
echo $HF_TOKEN

# Should show your token (or empty if not set)
```

---

### Step 5: Test Token Works

**Quick test:**
```bash
# Test HF Inference Providers API
curl https://router.huggingface.co/v1/models \
  -H "Authorization: Bearer $HF_TOKEN"

# Should return list of available models
```

**Or test via Python:**
```python
import os
from openai import OpenAI

client = OpenAI(
    base_url="https://router.huggingface.co/v1",
    api_key=os.getenv("HF_TOKEN")
)

# List models
models = client.models.list()
print([m.id for m in models])
```

---

## Token Permissions

**For Inference Providers, you need:**
- ✅ **Read** token type
- ✅ **"Make calls to Inference Providers"** permission

**You DON'T need:**
- ❌ Write permissions
- ❌ Fine-grained tokens (unless you want more control)

---

## Troubleshooting

### "Token not found" or "HF_TOKEN not set"

**Problem:** Environment variable not set

**Fix:**
```bash
# Check if set
env | grep HF_TOKEN

# If empty, set it
export HF_TOKEN=your_token_here

# Verify
echo $HF_TOKEN
```

---

### "Invalid token" or "Unauthorized"

**Problem:** Token doesn't have correct permissions

**Fix:**
1. Go to: https://huggingface.co/settings/tokens
2. Check token has **"Make calls to Inference Providers"** permission
3. If not, create new token with correct permissions
4. Update environment variable

---

### "Token expired"

**Problem:** Token was revoked or expired

**Fix:**
1. Go to: https://huggingface.co/settings/tokens
2. Create new token
3. Update environment variable

---

## Security Best Practices

1. **Never commit tokens to git:**
   ```bash
   # Add to .gitignore
   echo ".env" >> .gitignore
   echo "*token*" >> .gitignore
   ```

2. **Use environment variables** (not hardcoded in code)

3. **Rotate tokens periodically** (every 90 days recommended)

4. **Use different tokens** for different projects

---

## Quick Reference

**Get Token:**
- URL: https://huggingface.co/settings/tokens
- Click: "New token"
- Permission: ✅ "Make calls to Inference Providers"

**Set Token:**
```bash
export HF_TOKEN=your_token_here
```

**Verify:**
```bash
echo $HF_TOKEN
```

**Test:**
```bash
curl https://router.huggingface.co/v1/models \
  -H "Authorization: Bearer $HF_TOKEN"
```

---

## Next Steps

1. ✅ Get token from https://huggingface.co/settings/tokens
2. ✅ Set environment variable: `export HF_TOKEN=your_token`
3. ✅ Verify: `echo $HF_TOKEN`
4. ✅ Restart MCP server
5. ✅ Test: `call_model(prompt="Hello!", provider="hf")`

---

## Links

- **Token Settings:** https://huggingface.co/settings/tokens
- **Inference Providers Docs:** https://huggingface.co/docs/inference-providers/index
- **Available Models:** https://huggingface.co/models?inference_provider=all

---

**Status:** ✅ Ready to use  
**Time:** ~2 minutes to set up

