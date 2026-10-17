# ADR 0004: Integrate with the bank's loan origination system, don't replace it

**Status:** proposed, to confirm in discovery · **Date:** 2026-10-16

## Context
Every bank already has a loan origination system (nCino, Finastra, FIS, Temenos or in-house), which is the system of record for applications, limits and approvals. Rebuilding case management would duplicate it, compete with it and fail procurement.

## Decision
- The agents sit beside the LOS. They read applications and documents through its APIs or document store, and write back only drafts (checklist, extracted spread, memo draft, condition list) into fields or attachments the LOS already has.
- The POC is read-only. Write-back starts in the pilot, behind the same human gates.
- The reviewer workbench in `workbench/` exists to demonstrate the review experience. In production it becomes either a panel inside the LOS UI or a thin app that deep-links to the LOS case.
- System access goes through typed tools (MCP servers or API adapters) with scoped service identities per agent.

## Consequences
- Lower change-management and procurement friction; credit staff keep their system.
- The integration surface is the main delivery risk, so week 1 of discovery confirms which LOS, which APIs exist, and what the sandbox looks like (`docs/first_two_weeks.md`).
- Some workbench features (inline citations, blocked-attempt display) may need LOS customisation or the deep-link pattern.
