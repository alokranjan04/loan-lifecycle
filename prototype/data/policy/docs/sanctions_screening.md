# Sanctions Screening Procedure (Illustrative)

Fictional document for prototype. Defines mandatory screening checks, the lists that must be queried, and the escalation chain for any hit.

## 1. Purpose and Scope

### SAN-1.1 Purpose
The Bank must not facilitate transactions for, or extend credit to, any person or entity subject to financial sanctions. This procedure ensures that every customer, director, and beneficial owner is screened before credit is committed and on an ongoing basis.

### SAN-1.2 Sanctions lists
The Bank's screening service must be configured to query, at minimum: (a) UN Security Council Consolidated List; (b) OFAC SDN and Sectoral Sanctions Identifications (SSI) Lists; (c) EU Consolidated Financial Sanctions List; (d) HM Treasury Financial Sanctions Targets; (e) the Bank's jurisdiction's domestic sanctions register. Additional lists may be added by the Sanctions Officer without requiring a policy revision.

### SAN-1.3 Screening service access
Access to the screening service is restricted to authorised personnel. API keys and credentials are stored in the secrets management vault and rotated at least every 90 days. The Sanctions Officer maintains the approved-users register.

## 2. When Screening Is Required

### SAN-2.1 Pre-origination screening
All parties (borrower entity, directors, UBOs, guarantors) must be screened before a credit application is submitted for approval. A screening report dated within 30 days of the credit decision must be on file.

### SAN-2.2 Periodic refresh
Existing customers are re-screened at least monthly by the automated screening feed. Any new hit generated between periodic reviews triggers an immediate manual review.

### SAN-2.3 Change-triggered screening
A new screening run is required within 1 business day of: a change of director, a new beneficial owner exceeding the 25% threshold, a merger or acquisition involving the borrower, or a sanctions list update that the Sanctions Officer identifies as material.

## 3. Hit Adjudication

### SAN-3.1 True match — automatic decline
A screening hit confirmed as a true match against any active sanctions designation results in an immediate decline of the credit facility and a freeze of any existing account relationship. No exception or waiver is permitted.

### SAN-3.2 False positive process
A potential match that, after manual review, is determined to be a false positive (different person, same name) must be documented with the evidence supporting the determination. The AML Analyst and Sanctions Officer both sign the false-positive record.

### SAN-3.3 Insufficient information
Where the screening hit cannot be confirmed or excluded due to insufficient customer information, the Bank must request the missing information from the customer. If not received within 5 business days, the application is placed on hold and the Sanctions Officer is notified.

## 4. Escalation

### SAN-4.1 Immediate notification
On any unresolved or confirmed sanctions hit, the AML Analyst must notify the Sanctions Officer within 1 hour of the hit appearing.

### SAN-4.2 MLRO referral
The Sanctions Officer must refer confirmed true matches to the MLRO within 4 hours for assessment of reporting obligations. The MLRO determines whether a report to the relevant financial intelligence unit is required.

### SAN-4.3 Regulatory notification
Where applicable law requires the Bank to notify a regulator or financial intelligence unit of a sanctions match, the MLRO initiates that notification within the legally required timeframe.

## 5. Screening Service Configuration

### SAN-5.1 Watchlist format
The Bank maintains a local screening watchlist (`data/screening_watchlist.json`) that is used by the prototype pipeline. Each entry includes: `name`, `aliases`, `type` (PEP / Sanctions / Adverse Media), `reason`, and `detail`. Match scoring uses fuzzy name matching with a configurable threshold (default 80%).

### SAN-5.2 System change control
Any change to the screening service configuration, list subscriptions, or match threshold requires approval from the Sanctions Officer and is version-controlled. Changes are logged in the change management system.

### SAN-5.3 Downtime contingency
If the screening service is unavailable, new credit applications are queued and not approved until screening is completed. The maximum permissible outage before escalation to the Head of Compliance is 4 hours.
