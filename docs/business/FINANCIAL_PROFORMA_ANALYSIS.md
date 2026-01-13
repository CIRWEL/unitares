# Financial Proforma Analysis - UNITARES Governance MCP

**Date:** December 20, 2025  
**Analysis Type:** Pre-seed Round ($2.25M, 24-month runway)

---

## Executive Assessment: **REALISTIC with Minor Adjustments**

Overall, this is a **well-structured proforma** for a DeepTech AI governance startup. The assumptions are conservative and achievable. Minor adjustments recommended below.

---

## Runway Math Check

### Monthly Burn Rate Calculation

**Months 0-2 (Founder only):**
- Founder salary: $10,000/month
- Infrastructure: $3,000
- Dev tools: $2,000
- Legal/Admin: $8,300 (legal $3k + accounting $1.5k + insurance $0.8k + office $2.5k + travel $1.5k)
- **Total: $23,300/month**

**Months 3-5 (Founder + Backend Engineer):**
- Founder: $10,000
- Backend: $15,833
- Infrastructure: $3,000
- Dev tools: $2,000
- Legal/Admin: $8,300
- **Total: $39,133/month**

**Months 6-8 (Founder + Backend + ML Engineer):**
- Founder: $10,000
- Backend: $15,833
- ML: $15,000
- Infrastructure: $3,000
- Dev tools: $2,000
- Legal/Admin: $8,300
- **Total: $54,133/month**

**Months 9-11 (Founder + Backend + ML + AI Safety):**
- Founder: $10,000
- Backend: $15,833
- ML: $15,000
- AI Safety: $15,417
- Infrastructure: $3,000
- Dev tools: $2,000
- Legal/Admin: $8,300
- **Total: $69,550/month**

**Months 12-17 (Add Full-Stack Engineer):**
- Founder: $10,000
- Backend: $15,833
- ML: $15,000
- AI Safety: $15,417
- Full-Stack: $15,000
- Infrastructure: $6,000 (increased)
- Dev tools: $2,000
- Legal/Admin: $8,300
- **Total: $87,550/month**

**Months 18-24 (Add GTM Lead 0.5 FTE):**
- Founder: $10,000
- Backend: $15,833
- ML: $15,000
- AI Safety: $15,417
- Full-Stack: $15,000
- GTM: $7,083
- Infrastructure: $6,000
- Dev tools: $2,000
- Legal/Admin: $8,300
- **Total: $94,633/month**

### Cumulative Burn

| Period | Monthly Burn | Months | Total Burn |
|--------|-------------|--------|------------|
| M0-2 | $23,300 | 3 | $69,900 |
| M3-5 | $39,133 | 3 | $117,399 |
| M6-8 | $54,133 | 3 | $162,399 |
| M9-11 | $69,550 | 3 | $208,650 |
| M12-17 | $87,550 | 6 | $525,300 |
| M18-24 | $94,633 | 7 | $662,431 |
| **TOTAL** | | **25** | **$1,747,079** |

**Remaining at M24:** $2,250,000 - $1,747,079 = **$502,921** ✅

**Runway Extension:** With $502k remaining, you have ~5-6 months additional runway beyond M24.

---

## Revenue Assumptions Analysis

### Current Plan
- **First Revenue:** M12 ($12,500/month)
- **M12-24:** 3 pilots × $12,500 = $37,500/month
- **ARR by M24:** $450,000

### Revenue Timeline
- **M12:** $12,500 (1 pilot)
- **M13-17:** $25,000/month (2 pilots)
- **M18-24:** $37,500/month (3 pilots)

### Cumulative Revenue (M12-24)
- M12: $12,500
- M13-17: $25,000 × 5 = $125,000
- M18-24: $37,500 × 7 = $262,500
- **Total: $400,000**

**Note:** ARR of $450k by M24 means $37.5k/month × 12 = $450k, which matches the 3-pilot assumption.

### Revenue vs. Burn
- **M12-17:** Revenue $25k/month, Burn $87.5k/month = **-$62.5k/month net**
- **M18-24:** Revenue $37.5k/month, Burn $94.6k/month = **-$57.1k/month net**

**Assessment:** Revenue helps but doesn't cover burn. This is **normal for pre-seed** - you're buying time to prove product-market fit before Series A.

---

## Strengths of This Proforma

### ✅ **Conservative Hiring Timeline**
- 3-month gaps between hires allow for onboarding
- Founder builds MVP before first engineer (smart)
- GTM at M18 is appropriate (after product is built)

### ✅ **Realistic Salary Assumptions**
- Colorado market rates are accurate
- Remote-friendly = can hire from broader talent pool
- Fully-loaded costs included (health insurance, payroll taxes, etc.)

### ✅ **Infrastructure Scaling**
- $3k → $6k at M12 makes sense (more compute for ML/embeddings)
- $2k/month for dev tools is reasonable (GitHub, CI/CD, monitoring)

### ✅ **Revenue Assumptions**
- $12.5k/month per pilot is conservative (enterprise AI governance could be $25k-50k+)
- 3 pilots by M24 is achievable with strong product
- Design partner model is smart (paying customers = validation)

### ✅ **Runway Buffer**
- $502k remaining at M24 provides safety margin
- Allows for Series A fundraising timeline (3-6 months)

---

## Recommendations & Adjustments

### 1. **Add Contingency Buffer (5-10%)**
- **Current:** $1.75M burn
- **Recommended:** Add $87k-175k contingency
- **Reason:** Unexpected hires, infrastructure spikes, legal costs

### 2. **Consider Earlier Revenue (M9-10)**
- **Current:** First revenue M12
- **Recommendation:** Target M9-10 with early design partner
- **Benefit:** Proves market demand earlier, reduces net burn

### 3. **GTM Lead Timing**
- **Current:** M18 (0.5 FTE)
- **Consideration:** Could start M15 as fractional (0.25 FTE)
- **Benefit:** Earlier pipeline development, smoother transition

### 4. **Infrastructure Cost Validation**
- **Current:** $3k (M0-12), $6k (M13-24)
- **Question:** Does this include:
  - PostgreSQL hosting (managed service?)
  - Apache AGE infrastructure
  - pgvector compute
  - Embedding model inference costs
- **Recommendation:** Break down by service to validate

### 5. **Travel/Conferences**
- **Current:** $1,500/month = $18k/year
- **Assessment:** Reasonable for 2-3 conferences + customer visits
- **Consider:** May need to increase if doing GTM at M18

### 6. **Legal/IP Costs**
- **Current:** $3,000/month = $36k/year
- **Assessment:** Reasonable for:
  - Patent filings (if pursuing IP)
  - Corporate legal
  - Compliance (AI governance = regulatory attention)
- **Consider:** May spike in M18-24 if raising Series A

---

## Risk Factors

### 🔴 **High Risk**
1. **Revenue Timing:** If first pilot delayed to M15, net burn increases
2. **Infrastructure Costs:** ML/embeddings compute can spike unexpectedly
3. **Hiring Delays:** 3-month gaps assume smooth hiring (may take longer)

### 🟡 **Medium Risk**
1. **Salary Inflation:** AI/ML talent market is hot (may need to adjust)
2. **GTM Effectiveness:** 0.5 FTE may not be enough for 3 pilots
3. **Series A Timeline:** Need to start fundraising M18-20 (6 months before M24)

### 🟢 **Low Risk**
1. **Runway Math:** Numbers work with buffer
2. **Hiring Plan:** Conservative and achievable
3. **Revenue Assumptions:** Conservative (could be higher)

---

## Comparison to Typical Pre-Seed

| Metric | Your Plan | Typical Pre-Seed | Assessment |
|--------|-----------|------------------|------------|
| **Round Size** | $2.25M | $1M-3M | ✅ Normal |
| **Runway** | 24 months | 18-24 months | ✅ Good |
| **Team Size (M24)** | 5.5 FTE | 4-6 FTE | ✅ Normal |
| **First Revenue** | M12 | M9-15 | ✅ Conservative |
| **ARR by M24** | $450k | $200k-1M | ✅ Achievable |
| **Burn Rate (M24)** | $94.6k/month | $80k-120k/month | ✅ Normal |

**Verdict:** Your plan aligns with typical pre-seed metrics.

---

## Final Verdict

### ✅ **REALISTIC** with minor adjustments

**Strengths:**
- Conservative assumptions
- Runway math works
- Hiring timeline is achievable
- Revenue targets are reasonable

**Recommendations:**
1. Add 5-10% contingency buffer ($87k-175k)
2. Validate infrastructure costs (break down by service)
3. Consider earlier revenue (M9-10) if possible
4. Plan Series A fundraising start at M18-20

**Overall Grade: A-**

This is a **well-thought-out proforma** that demonstrates:
- Understanding of startup economics
- Conservative planning (good for investor confidence)
- Realistic hiring and revenue assumptions
- Appropriate runway for DeepTech product development

---

## Questions for Investor Presentation

1. **What's the path to $1M ARR?** (Series A milestone)
2. **How does revenue scale beyond 3 pilots?** (GTM strategy)
3. **What's the infrastructure cost per customer?** (unit economics)
4. **How long to onboard a design partner?** (revenue timing risk)
5. **What's the Series A target?** ($5M-10M typical for DeepTech)

---

**Document Version:** 1.0  
**Last Updated:** December 20, 2025

