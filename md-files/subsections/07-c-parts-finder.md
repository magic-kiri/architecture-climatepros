<!--
  §7 · Use Case C subsection — SOURCE OF TRUTH. Content from sample-unified.docx.
  Replaces "C Parts Finder — Data Model" only.
-->

# C Parts Finder — Data Model

Two stores cooperate. The existing SQL Server system of record (FieldJetX) owns the business data the Parts Finder reads — dispatches, the inventory catalogue, and stock by location — and the AI service only ever reads it, never writes to it. A separate vector index holds the semantic search index used for prediction, and the AI service's own MongoDB holds the data it writes: the parts a technician commits, acceptance signals, and indexing bookkeeping.

> **The relational database stays the single source of truth.** Nothing in the existing business tables changes, and the vector index is derived and rebuildable.
