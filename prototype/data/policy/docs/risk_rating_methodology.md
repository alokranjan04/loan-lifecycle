# Internal Risk Rating Methodology (Illustrative)

Fictional document for prototype. Defines how the Bank assigns an obligor risk grade, maps it to a probability of default (PD), and uses it in pricing and provisioning.

## 1. Rating Scale

### RRM-1.1 Grade definitions
The Bank uses a 10-grade internal scale: Grade 1 (Minimal risk) through Grade 10 (Default). Grades 1–4 are investment-quality. Grades 5–6 are acceptable commercial credit. Grade 7 is watch-list. Grades 8–10 trigger provisioning and workout.

### RRM-1.2 Grade descriptions
Grade 1: AAA-equivalent, sovereign or top-tier multinational. Grade 2: Strong investment grade, consistently excellent ratios. Grade 3: Good credit quality, solid sector position. Grade 4: Adequate, minor weaknesses. Grade 5: Acceptable, some vulnerability to adverse conditions. Grade 6: Marginal, material weaknesses requiring active management. Grade 7: Watch, potential loss if adverse conditions persist. Grade 8: Substandard, well-defined weaknesses, loss possible. Grade 9: Doubtful, collection or liquidation in full is questionable. Grade 10: Loss, uncollectable or of so little value that continuance as a bankable asset is not warranted.

### RRM-1.3 Rating floor
Regardless of financial metrics, a borrower cannot be rated above Grade 5 if: (a) any director or UBO is a PEP with an unresolved EDD; (b) there is an active sanctions alert under adjudication; (c) the business is in a sector rated "Exit" in the risk appetite statement.

## 2. Financial Scorecard

### RRM-2.1 Leverage (weight: 25%)
Total Debt / EBITDA: below 2.0x → score 5; 2.0–3.0x → 4; 3.0–3.5x → 3; 3.5–4.0x → 2; above 4.0x → 1. Score is multiplied by the weight to produce a weighted sub-score.

### RRM-2.2 Debt service coverage (weight: 25%)
Projected DSCR: above 2.0x → score 5; 1.60–2.0x → 4; 1.40–1.60x → 3; 1.25–1.40x → 2; below 1.25x → 1 (automatic policy flag).

### RRM-2.3 Profitability (weight: 15%)
Net profit margin (3-year average): above 15% → 5; 10–15% → 4; 5–10% → 3; 2–5% → 2; below 2% or loss-making → 1.

### RRM-2.4 Liquidity (weight: 10%)
Current ratio: above 2.0x → 5; 1.5–2.0x → 4; 1.25–1.50x → 3; 1.10–1.25x → 2; below 1.10x → 1.

### RRM-2.5 Leverage trend (weight: 10%)
Leverage change over 3 years: improving → 5; stable (±0.2x) → 3; deteriorating → 1.

### RRM-2.6 Revenue reconciliation (weight: 5%)
Bank credits to revenue: above 90% → 5; 80–90% → 4; 70–80% → 3; 60–70% → 2; below 60% → 1.

## 3. Qualitative Factors

### RRM-3.1 Management quality (weight: 10%)
Assessed by the RM: experienced, cohesive, succession-planned team with no recent departures → 5 down to new / untested management → 1.

### RRM-3.2 Industry and sector position
Scored by the analyst based on competitive position, barriers to entry, and demand outlook for the borrower's sector.

## 4. Final Grade Mapping

### RRM-4.1 Total score to grade
Total weighted score (max 100): 85–100 → Grade 2; 70–84 → Grade 3; 55–69 → Grade 4; 40–54 → Grade 5; 25–39 → Grade 6; 10–24 → Grade 7; below 10 → Grade 8.

### RRM-4.2 Override policy
The Credit Committee may override the model-generated grade by up to one notch (up or down) with written justification. A downgrade override requires only the Credit Analyst; an upgrade override requires the Head of Credit Risk.

### RRM-4.3 PD mapping
Grades are mapped to probability of default (PD) ranges used in IFRS 9 staging and RWA calculation. The mapping table is maintained by the Finance team and updated annually using observed default rates.

## 5. Pricing

### RRM-5.1 Risk-adjusted pricing
The interest rate floor is set by: base rate + credit spread (grade-based) + liquidity premium + operating cost. The credit spread schedule is published internally and reviewed quarterly.

### RRM-5.2 Exception pricing
Pricing below the floor requires a Risk-Adjusted Return on Capital (RAROC) analysis demonstrating that the relationship-level return meets the hurdle rate. The analysis is prepared by the RM and approved by the Head of Credit.
