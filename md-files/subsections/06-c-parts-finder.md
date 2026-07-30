<!--
  §6 · Use Case C subsection — SOURCE OF TRUTH. Content from sample-unified.docx.
  Replaces "C Parts Finder — Matching & Sourcing Logic" only.
-->

# C Parts Finder — Matching & Sourcing Logic

Prediction is retrieval-augmented. When a technician opens a dispatch, the app finds the most similar past dispatches from a vector database using cosine similarity, then suggests the parts those similar jobs actually used — closer matches count for more. The index updates itself as dispatches close, so suggestions keep improving over time.

Once parts are chosen, the source step works out where each one can be collected across the technician's truck, other warehouses, and the United vendor. The detailed scoring and retrieval mechanics for the AI use cases are documented separately.
