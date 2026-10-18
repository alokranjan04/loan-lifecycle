# Enhanced Due Diligence and PEP Procedure (Illustrative)

Fictional document for prototype. Defines the additional checks and sign-off chain required when a politically exposed person (PEP) or high-risk customer is identified during screening.

## 1. Definitions

### EDD-1.1 Politically Exposed Person
A PEP is an individual who is or has been entrusted with a prominent public function: heads of state, senior politicians and government ministers, senior executives of state-owned enterprises, high-ranking military or judicial officers, and senior officials of international organisations. The designation extends to close family members (spouse, children, parents, siblings) and known close associates.

### EDD-1.2 Former PEP
An individual who has ceased to hold a prominent public function within the last 12 months is treated as a current PEP for the purposes of this procedure. After 12 months, the residual risk is assessed on a case-by-case basis.

### EDD-1.3 Close associate
A close associate is a natural person known to have a joint beneficial interest in assets, close business relations, or a fiduciary relationship with a PEP. Screening matches flagged as close associates trigger EDD unless the business relationship with the PEP is adequately explained.

## 2. Screening Triggers

### EDD-2.1 Mandatory screening scope
All directors, ultimate beneficial owners, guarantors, and the borrower entity itself must be screened against: (a) global PEP databases, (b) consolidated sanctions lists (UN, OFAC, EU, HMT), and (c) adverse media databases. Screening must be conducted at onboarding and refreshed at each periodic review.

### EDD-2.2 Match score threshold
A screening hit with a match score of 80% or above is treated as a confirmed match and triggers the EDD workflow automatically. Hits between 60% and 79% are referred to the AML Analyst for manual adjudication within 2 business days.

### EDD-2.3 Sanctions match — automatic decline
A confirmed match against any active sanctions list (not merely a PEP match) results in an automatic decline. No credit approval authority may override a confirmed sanctions decline.

## 3. EDD Workflow

### EDD-3.1 Compliance Officer assignment
On a confirmed PEP or high-risk match, the loan origination system assigns the case to a Compliance Officer automatically and places a hold on the credit approval gate. Credit approval may not proceed until the Compliance Officer renders a decision.

### EDD-3.2 Source of wealth verification
The Compliance Officer must obtain and document evidence of the PEP's source of wealth (e.g., salary statements, business valuations, inheritance records) and assess whether the proposed facility is consistent with the identified wealth.

### EDD-3.3 Source of funds verification
For the specific transaction, the Compliance Officer must verify that the funds flowing into the borrower's accounts during the credit period can be attributed to legitimate business activities and are consistent with the customer's risk profile.

### EDD-3.4 Senior management approval
Establishing or continuing a business relationship with a PEP requires written approval from a Senior Manager at the rank of Head of Compliance or above. This approval is recorded in the audit log and the customer file.

### EDD-3.5 EDD decision timeline
The Compliance Officer must render a decision — EDD Cleared or EDD Not Cleared — within 10 business days of the case being assigned. An extension of up to 5 business days may be granted by the Head of Compliance in writing.

## 4. Outcomes

### EDD-4.1 EDD Cleared
If the Compliance Officer is satisfied that the source of wealth and funds are legitimate and the risk is within appetite, the EDD is recorded as Cleared. The credit approval gate is released and the normal credit approval chain applies.

### EDD-4.2 EDD Not Cleared
If the Compliance Officer is not satisfied, the EDD is recorded as Not Cleared and the facility is declined. A referral to the MLRO is made within 24 hours to assess whether a SAR filing is required.

### EDD-4.3 Conditional clearance
The Compliance Officer may impose specific monitoring conditions (e.g., quarterly source-of-funds review, restricted account activity) as part of a Cleared decision. Conditions are recorded as facility covenants and monitored by the AML team.

## 5. Record-keeping

### EDD-5.1 File retention
All EDD documentation — screening reports, source of wealth evidence, source of funds analysis, and the Compliance Officer's decision rationale — must be retained for 7 years from the date of the decision.

### EDD-5.2 Audit trail
Each step of the EDD workflow, including assignment, queries raised, documents received, and the final decision, is time-stamped and recorded in the hash-chained audit log.
