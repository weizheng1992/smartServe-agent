# Implementation Plan - Highly Optimizing Triage Node for Peak Performance

To significantly improve the speed and responsiveness of the Triage execution stage, we will:

1. **Optimize Anchor Pre-Caching (31x HTTP Request Reduction)**:
   - Refactor `getAnchorVectors()` to batch-embed all 31 anchor phrases in a single LangChain API call using `embedModel.embedDocuments(allTexts)` instead of 31 parallel `embedQuery()` calls. This completely eliminates HTTP request pool blockages and connection establishment latencies.

2. **Establish a Global User Embedding Cache (Semantic Re-use)**:
   - Create a global `Map<string, number[]>` in-memory cache inside `packages/engine/src/graph/nodes/triage.node.ts`.
   - Introduce a wrapper `getEmbeddingWithCache(text: string): Promise<number[]>` to perform lookups and persist newly calculated embeddings.

3. **Eliminate Redundant Embedding Calls (3x ➔ 1x Reduction)**:
   - In the **Duplicate提问拦截 (Semantic Duplicate Shield)** block:
     - Fetch current input's vector via `getEmbeddingWithCache(input)`.
     - Fetch last user message's vector via `getEmbeddingWithCache(lastUserMsg.content)`. Since the previous user message was processed just prior, its embedding is already cached—resulting in a **100% cache hit** (0 extra network calls).
   - In **Step 2 (Embedding Classifier)**:
     - Fetch the user input's vector via `getEmbeddingWithCache(input)`—resulting in a **100% cache hit** (0 extra network calls).
   - This changes the network embedding request pattern from:
     - New queries: **3 network calls ➔ 1 network call**
     - Repeated/Similar queries: **2 network calls ➔ 0 network calls**

## Verification Checklist

- [ ] Modify `packages/engine/src/graph/nodes/triage.node.ts` to implement the caching and batching improvements.
- [ ] Ensure full compilation and verify logic.
