"""Entity resolution — merge new entities with existing graph nodes."""

import context_tree.common.llm as copilot_api
import context_tree.common.store as store
# Thresholds
AUTO_MERGE = 0.85      # cosine > this → auto merge without LLM
LLM_DISAMBIG = 0.5     # cosine > this → ask LLM to decide
# Types where cross-session merge is rarely meaningful (each instance is task-specific
# context, not a shared concept). Skip LLM disambig for these — accept slug-exact-match
# auto-merge only.
SKIP_DISAMBIG_TYPES = {"agent_content", "constraint", "term", "lesson", "context"}
# Below 0.5 → always create new node

DISAMBIG_PROMPT = "Determine if these two entities refer to the same concept. Reply ONLY 'yes' or 'no'."
CONTRADICTION_PROMPT = """Determine if Decision B truly SUPERSEDES Decision A as a long-term strategy.

Both must be COMMITMENTS / STRATEGIES / DECISIONS to qualify. Reply 'yes' ONLY when:
- Same topic/concern
- B represents a NEW LONG-TERM choice that replaces A's
- A is no longer the project's direction

Reply 'no' when:
- Either is a temporary order ("暂时不要", "先停一下", "wait", "skip for now")
- Either is a one-off task ("修一下 X", "查看 Y")
- Different topics
- B clarifies/refines A but doesn't replace it
- B is shorter/vaguer than A (likely just an instruction)

Reply ONLY 'yes' or 'no'."""


def resolve(conn, entities: list[dict], verbose: int = 1) -> tuple[list[dict], list[tuple[str, list[float]]]]:
    """Resolve entities against existing graph.

    Path-based entities (type='file' or 'directory') bypass embedding/disambig
    entirely — they have stable per-device path-based ids and dedup at SQL
    upsert level.

    Returns:
        (resolved_entities, pending_embeddings) where pending_embeddings
        are (node_id, embedding) pairs to store after write.
    """
    if not entities:
        return [], []

    # Split path-based vs semantic entities
    PATH_TYPES = {"file", "directory"}
    file_entities = [e for e in entities if e.get("type") in PATH_TYPES]
    sem_entities = [e for e in entities if e.get("type") not in PATH_TYPES]

    if not sem_entities:
        if verbose >= 1 and file_entities:
            print(f"   {len(file_entities)} path entities (bypass disambig)")
        return file_entities, []

    # Skip embedding for low-confidence entities (conf < 0.45). They get inserted
    # into the graph for completeness (point-in-time queries, structural traversal)
    # but won't participate in vector retrieval. Saves ~30% embedding cost on
    # B-revised pipelines that emit unclaimed_proposal_small / clarify_open / etc.
    EMBED_MIN_CONF = 0.45
    embed_entities = [e for e in sem_entities if (e.get("confidence") or 0.5) >= EMBED_MIN_CONF]
    skip_entities = [e for e in sem_entities if (e.get("confidence") or 0.5) < EMBED_MIN_CONF]

    # Generate embeddings only for high-conf semantic entities
    if embed_entities:
        texts = [f"{e['title']}: {e.get('content','')}" for e in embed_entities]
        if verbose >= 1:
            print(f"   Generating {len(texts)} embeddings ({len(skip_entities)} low-conf skipped)...",
                  end=" ", flush=True)
        embs = copilot_api.embeddings(texts)
        if verbose >= 1:
            print(f"✓ dim={len(embs[0]) if embs else 0}")
    else:
        embs = []

    resolved = list(file_entities) + list(skip_entities)  # files + low-conf pass through unchanged
    pending = []

    for i, entity in enumerate(embed_entities):
        emb = embs[i] if i < len(embs) else None
        resolved_id = None

        # Find best matching existing node
        if emb and not entity.get("id"):
            candidates = store.search_by_embedding(conn, emb, top_k=1, min_score=LLM_DISAMBIG)
            # Type-gate: only consider candidates of the same entity type
            candidates = [(n, s) for (n, s) in candidates if n.get("type") == entity.get("type")]
            if candidates:
                existing, score = candidates[0]

                if score > AUTO_MERGE:
                    # Auto merge
                    resolved_id = existing["id"]
                    if verbose >= 1:
                        print(f"   [{i+1}/{len(embed_entities)}] ✓ auto-merge: {entity['title'][:30]} → {existing['title'][:30]} ({score:.2f})")
                elif score > LLM_DISAMBIG:
                    # Skip LLM disambig for types where cross-session merge is rarely correct.
                    # Each instance is bound to a specific task context; treat as distinct.
                    if entity.get("type") in SKIP_DISAMBIG_TYPES:
                        pass  # leave resolved_id as None → treat as new entity
                    else:
                        if verbose >= 1:
                            print(f"   [{i+1}/{len(embed_entities)}] ? LLM disambig: {entity['title'][:30]} vs {existing['title'][:30]} ({score:.2f})...", end=" ", flush=True)
                        try:
                            answer = copilot_api.chat_cheap(
                                DISAMBIG_PROMPT,
                                f"Entity A: {entity['title']} — {entity.get('content','')[:100]}\n"
                                f"Entity B: {existing['title']} — {existing.get('content','')[:100]}",
                                stage="resolve"
                            )
                            is_same = "yes" in answer.lower()
                            if verbose >= 1:
                                print("same" if is_same else "different")
                            if is_same:
                                resolved_id = existing["id"]
                                # Contradiction check for constraints
                                if entity.get("type") == "constraint" and existing.get("type") == "constraint":
                                    _check_contradiction(conn, entity, existing, verbose)
                        except Exception as e:
                            if verbose >= 1:
                                print(f"✗ {e}")

        if resolved_id:
            # Merge content into existing
            _merge_into_existing(conn, resolved_id, entity)
            resolved.append({**entity, "title": existing["title"]})
        else:
            resolved.append(entity)

        # Collect embedding
        if emb:
            nid = resolved_id or entity.get("id") or store.slugify(entity["title"])
            pending.append((nid, emb))

    if verbose >= 1:
        merged_count = len(embed_entities) - len(set(e.get('title') for e in resolved
                                                       if e.get('type') not in ('file', 'directory')
                                                       and (e.get('confidence') or 0.5) >= EMBED_MIN_CONF))
        print(f"   Entity resolution: {len(entities)} → {len(resolved)} "
              f"({merged_count} merged, {len(file_entities)} path bypassed, "
              f"{len(skip_entities)} low-conf passed through)")

    return resolved, pending


def _merge_into_existing(conn, node_id: str, entity: dict):
    """Merge new entity content into existing node."""
    existing = store.get_node(conn, node_id)
    if not existing:
        return
    old_content = existing.get("content", "") or ""
    new_content = entity.get("content", "") or ""
    if new_content and new_content not in old_content:
        merged = f"{old_content}\n---\n{new_content}" if old_content else new_content
        conn.execute("UPDATE nodes SET content = ?, updated_at = datetime('now') WHERE id = ?",
                     (merged, node_id))


def _check_contradiction(conn, new_entity: dict, existing: dict, verbose: bool):
    """Check if new constraint contradicts existing one. Bi-temporal invalidate (no UPDATE).

    Per spec §5: never mutate the old node's content. Set invalid_from + expired_at
    to now via store.invalidate_node, then add superseded_by edge.
    """
    old_content = existing.get("content", "")
    new_content = new_entity.get("content", "")
    if not old_content or not new_content:
        return

    # Pre-filter: contradiction check only meaningful for substantive decisions
    if len(new_entity.get("title", "")) < 12 or len(existing.get("title", "")) < 12:
        return
    TEMP_MARKERS = ("先不要", "暂时", "先停", "等一下", "等等", "不急", "先别", "回头再",
                     "wait", "skip for now", "hold on")
    new_title = new_entity.get("title", "").lower()
    if any(m in new_title for m in TEMP_MARKERS):
        return

    try:
        answer = copilot_api.chat_cheap(
            CONTRADICTION_PROMPT,
            f"Decision A: {existing['title']} — {old_content[:200]}\n"
            f"Decision B: {new_entity['title']} — {new_content[:200]}",
            stage="resolve"
        )
        if "yes" in answer.lower():
            if verbose >= 1:
                print(f"     ⚠ Contradiction: {existing['title'][:30]} superseded by {new_entity['title'][:30]}")
            store.invalidate_node(conn, existing["id"])
            new_id = store.slugify(new_entity["title"])
            store.upsert_edge(conn, source_id=existing["id"], target_id=new_id,
                             relation="superseded_by", explanation="LLM detected contradiction")
    except Exception:
        pass
