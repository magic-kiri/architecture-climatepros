<!--
  §5 · Use Case C subsection — SOURCE OF TRUTH. Content from sample-unified.docx.
  Replaces the "C Parts Finder — Find & Allocate" subsection only; A and B keep
  their exported content untouched.

  `#` = this subsection's heading · `##` = sub-subsection · pipe tables, ``` fences ```
  and `> callouts` all get house style · ![Title](figN "caption") = figure plate.
-->

# C Parts Finder — Find & Allocate

For every part the technician needs, the app gathers every place it can be collected and orders them so the closest free stock comes first — the technician's own truck (on hand, zero distance), then other technicians' vans and branch warehouses (own stock, nearest first), and finally the United Refrigeration vendor. The needed quantity is then split greedily down that list: each source contributes what it has until the quantity is met.

![Use Case C — four-source find and greedy allocate](fig7 "Truck → nearby technicians' trucks → branch warehouse → third-party supplier, then greedy allocation down the sorted list. Steps are written out above.")

> **A van is a warehouse.** Per operations, there is no separate "nearby technician" tier — another tech's van is modelled as a warehouse, which keeps the sourcing model to three underlying data tiers (truck / warehouse / vendor) while the technician-facing flow above still reads as four distinct sources.

<!-- -->

> **Vendor lookup fails → drop the tier, not the request.** If the United Refrigeration lookup fails, the vendor tier is dropped rather than failing the whole request — the technician still sees every own-stock option (truck + warehouse). See §11 Onboarding & Fault Tolerance.
