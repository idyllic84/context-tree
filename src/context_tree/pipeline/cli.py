#!/usr/bin/env python3
"""Stage-configurable aligned-turn sync, task-tree retrieval and literal identifier indexing."""
import argparse
import json
import os
import sys
import hashlib


import context_tree.stages.ingest.processor as claude_adapter
import context_tree.stages.resolve.processor as entity_resolver
import context_tree.common.store as store
import context_tree.common.models as models
from context_tree.stages.tree.state import TreeStateMachine
from context_tree.stages.index import processor as indexing
import context_tree.stages.extract.processor as extract_units
import context_tree.stages.tree.processor as build_tree
import context_tree.stages.review.processor as tree_review
import context_tree.stages.reflexion.processor as reflexion
import context_tree.stages.framing.processor as framing_pass
import context_tree.stages.emit.processor as tree_to_entities
from . import retrieval
def cmd_sync(args):
    verbose = 1 if args.quiet else 2
    print("🔍 Discovering sessions...")
    sessions = claude_adapter.discover_sessions()
    print(f"   Found {len(sessions)} sessions")

    conn = store.connect()

    to_process = []
    for s in sessions:
        state = store.get_processing_state(conn, s.session_id)
        if args.session and not s.session_id.startswith(args.session):
            continue
        if state and state["schema_version"] != store.CACHE_VERSION:
            raise ValueError("Legacy knowledge base: use --db with a new path for the aligned-turn pipeline")
        if state is None or state["message_count"] != s.file_count:
            to_process.append(s)

    if args.session:
        to_process = [s for s in to_process if s.session_id.startswith(args.session)]

    limit = args.limit or len(to_process)
    to_process = to_process[:limit]

    if not to_process:
        print("   ✅ All sessions up to date"); return

    print(f"   Processing {len(to_process)} sessions...\n")
    to_process.sort(key=lambda s: (0 if s.parent_session_id is None else 1, s.parent_session_id or ""))

    total_entities = 0
    for si, session in enumerate(to_process):
        print(f"── [{si+1}/{len(to_process)}] {session.display_name} ({session.project_path.split('/')[-1]})")
        if session.parent_session_id:
            print(f"   chain parent: {session.parent_session_id[:8]}")

        all_turns, project_path = claude_adapter.parse_turns(session.file_path)
        print(f"   {len(all_turns)} dialogue turns total")
        if not all_turns:
            with conn:
                store.mark_processed(conn, session.session_id, session.file_count, session.file_path,
                                     schema_version=store.CACHE_VERSION)
            print("   (skipped)\n"); continue

        state = store.get_processing_state(conn, session.session_id)
        initial_session = (models.Session.from_dict(json.loads(state["task_tree_json"]))
                           if state and state["task_tree_json"] else None)
        cached_turns = initial_session.turns if initial_session else []
        cached_by_uuid = {t.source_uuid: t for t in cached_turns}
        source_fields = ("human_raw", "agent_raw", "tool_inputs", "tool_outputs", "tool_modifies")
        for turn in all_turns:
            previous = cached_by_uuid.get(turn.source_uuid)
            if previous and any(getattr(previous, field) != getattr(turn, field) for field in source_fields):
                raise ValueError("A finalized source turn changed; rebuild this session in a separate database")
        visible_uuids = {t.source_uuid for t in all_turns}
        if not set(cached_by_uuid).issubset(visible_uuids):
            raise ValueError("Source history removed finalized turns; separate rebuild required")
        pending_turns = [t for t in all_turns if not t.complete]
        new_turns = [t for t in all_turns if t.complete and t.source_uuid not in cached_by_uuid]
        if not new_turns:
            saved = initial_session or models.Session(session.session_id, project_path, session.display_name)
            saved.pending_turns = pending_turns
            with conn:
                store.mark_processed(conn, session.session_id, session.file_count, session.file_path,
                                     tree_json=json.dumps(saved.to_dict(), ensure_ascii=False),
                                     schema_version=store.CACHE_VERSION)
            print(f"   no completed new turns ({len(pending_turns)} pending)")
            continue
        print(f"   processing {len(new_turns)} new turns ({len(cached_turns)} cached)")
        sm = TreeStateMachine(initial_session=initial_session)
        prior_units = [u for t in cached_turns for u in t.units]
        all_units, _ = extract_units.extract_session(
            new_turns, model=None, verbose=0 if verbose < 2 else 1, prior_units=prior_units)
        # L2: independent batching — sized by unit count, not L1 turn batches.
        # L2 input is much more compact than L1 (units vs raw dialogue) so
        # L2 packs more items per call without LLM output budget concern.
        all_muts = []
        l2_batches = build_tree.batch_units_for_l2(new_turns)
        for batch_units, batch_turns in l2_batches:
            muts = build_tree.build_tree_for_batch(
                sm, batch_units, model=None, verbose=0 if verbose < 2 else 1,
                batch_turns=batch_turns)
            all_muts.extend(muts)
        muts = all_muts
        units = all_units

        # Tree review (post-extraction H²R-style refinement)
        if not args.no_review:
            if verbose >= 2: print("   [REVIEW] tree refinement pass ...")
            tree_review.review_and_refine(sm, model=None, verbose=verbose)

        # Combine cached + new for downstream
        combined = cached_turns + new_turns

        # Link units to tasks (framing_pass walks task.linked_unit_ids).
        # State machine already linked units referenced by mutations (affirm/reject/soft_complete).
        # Here we cover the GAP: agent units NOT referenced by any mutation
        # (unclaimed propose/explain/clarify/report) — link them to the task that's
        # active at their turn. Walk turns in order, track active_task by mutations
        # applied for that turn's units.
        from context_tree.stages.tree.state import _flatten_tasks as _ft
        all_tasks_by_id = {t.id: t for g in sm.goals for t in _ft(g)}
        active_task_id: str | None = None
        for turn in combined:
            turn_tasks = {u.for_task_id for u in turn.units
                          if u.speaker == "human" and u.act == "instruct" and u.for_task_id in all_tasks_by_id}
            if len(turn_tasks) == 1:
                active_task_id = next(iter(turn_tasks))
            elif len(turn_tasks) > 1:
                active_task_id = None
            for u in turn.units:
                if u.for_task_id in all_tasks_by_id:
                    if u.speaker == "agent":
                        active_task_id = u.for_task_id
                elif u.target and u.target in sm._unit_by_id:
                    target_task = sm._unit_by_id[u.target].for_task_id
                    if target_task in all_tasks_by_id:
                        u.for_task_id = target_task
                elif u.speaker == "agent" and active_task_id:
                    u.for_task_id = active_task_id
                if u.for_task_id in all_tasks_by_id:
                    task = all_tasks_by_id[u.for_task_id]
                    if u.id not in task.linked_unit_ids:
                        task.linked_unit_ids.append(u.id)

        # Snapshot tree as Session for framing/emit
        v_session = sm.to_session(
            session_id=session.session_id, project_path=project_path,
            display_name=session.display_name, turns=combined,
        )

        v_session.pending_turns = pending_turns
        from context_tree.stages.tree.state import _flatten_tasks
        n_goals = len(v_session.goals)
        n_tasks = sum(len(_flatten_tasks(g)) for g in v_session.goals)
        print(f"   → {n_goals} goal(s), {n_tasks} task(s), {len(muts)} mutations applied "
              f"({len(sm.warnings)} warnings)")

        # Reflexion (optional)
        if not args.no_reflexion:
            if verbose >= 2: print("   Tier 4 reflexion ...")
            reflexion.review_session(v_session, verbose=verbose)

        # Framing pass
        if not args.no_framing:
            if verbose >= 2: print("   Tier 3.5 framing pass ...")
            framing_pass.frame_session(v_session, verbose=verbose)

        # Emit entities + edges
        date = combined[0].timestamp[:10] if combined else "unknown"
        entities, edges = tree_to_entities.convert_session(v_session, date=date)
        n_ac = sum(1 for e in entities if e.get("type") == "agent_content")
        n_files = sum(1 for e in entities if e.get("type") == "file")
        n_dirs = sum(1 for e in entities if e.get("type") == "directory")
        print(f"   → {len(entities)} entities ({n_ac} agent_content, {n_files} files, {n_dirs} dirs), {len(edges)} edges")

        entity_ids_by_title = {}
        for entity in entities:
            if entity["type"] not in ("file", "directory") and not entity.get("id"):
                source = entity.get("source_unit_id") or ""
                discriminator = (source if entity["type"] == "agent_content" else
                                 source + ":" + entity["title"])
                digest = hashlib.sha256(discriminator.encode()).hexdigest()[:20]
                entity["id"] = f"{session.session_id}:{entity['type']}:{digest}"
            entity_ids_by_title.setdefault(entity["title"], []).append(entity["id"])
        with conn:
            old_ids = [row[0] for row in conn.execute(
                "SELECT id FROM nodes WHERE json_extract(metadata,'$.session')=? "
                "AND type NOT IN ('file','directory')", (session.session_id,))]
            conn.execute("DELETE FROM edges WHERE session_id=?", (session.session_id,))
            for node_id in old_ids:
                conn.execute("DELETE FROM edges WHERE source_id=? OR target_id=?", (node_id, node_id))
                conn.execute("DELETE FROM nodes WHERE id=?", (node_id,))

            if entities:
                resolved, pending_embs = entity_resolver.resolve(conn, entities, verbose=verbose)
                for e in resolved:
                    node_id = e.get("id") or store.slugify(e["title"])
                    metadata = {"project": e.get("project",""), "session": e.get("session",""), "date": e.get("date","")}
                    if extra := e.get("metadata_extra"):
                        metadata.update(extra)
                    store.upsert_node(conn, id=node_id, type=e["type"], title=e["title"],
                        content=e.get("content"), metadata=metadata, valid_from=e.get("date"),
                        confidence=e.get("confidence"), source_unit_id=e.get("source_unit_id"))
                for nid, emb in pending_embs:
                    store.store_embedding(conn, nid, emb)
                total_entities += len(resolved)

                for edge in edges:
                    source_ids = ([edge["source_id"]] if edge.get("source_id") else
                                  entity_ids_by_title.get(edge.get("source_title"), []))
                    target_ids = ([edge["target_id"]] if edge.get("target_id") else
                                  entity_ids_by_title.get(edge.get("target_title"), []))
                    if len(source_ids) != 1 or len(target_ids) != 1:
                        continue
                    store.upsert_edge(conn, source_id=source_ids[0], target_id=target_ids[0],
                        relation=edge["relation"], explanation=edge.get("explanation"),
                        session_id=session.session_id)

            n_g, n_t = indexing.index_session(conn, session.session_id, v_session.goals, combined)
            n_identifiers = indexing.index_identifiers(conn, v_session)
            store.mark_processed(conn, session.session_id, session.file_count, session.file_path,
                                 last_processed_uuid=combined[-1].source_uuid if combined else "",
                                 tree_json=json.dumps(v_session.to_dict(), ensure_ascii=False),
                                 schema_version=store.CACHE_VERSION)
        store.save_cached_turns(session.session_id, [t.to_dict() for t in combined])
        if verbose >= 1:
            print(f"   indexed {n_g} goals + {n_t} tasks + {n_identifiers} identifier occurrences")
        print(f"   ✅ Done\n")

    n_nodes = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    n_emb = conn.execute("SELECT COUNT(*) FROM nodes WHERE embedding IS NOT NULL").fetchone()[0]
    n_edges = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    print(f"═══ Sync complete: {len(to_process)} sessions, {total_entities} entities ═══")
    print(f"    Graph: {n_nodes} nodes ({n_emb} embedded), {n_edges} edges")


def cmd_retrieve(args):
    """Branch-based retrieval — N candidate contexts, one per relevant branch."""
    conn = store.connect()
    result = retrieval.retrieve_branched(
        conn, args.query,
        current_session_id=args.current_session,
        project_path=args.project,
        top_n_recall=args.top_n,
        max_iterations=args.max_iter,
        model=None,
        mode=args.mode,
    )
    print(retrieval.format_branched_result(result, verbose=args.verbose))


def cmd_stats(_):
    conn = store.connect()
    print("Node counts by type:")
    for row in conn.execute("SELECT type, COUNT(*) FROM nodes GROUP BY type ORDER BY 2 DESC"):
        print(f"  {row[0]:20} {row[1]}")
    print("\nAgent_content by subtype:")
    for row in conn.execute("SELECT json_extract(metadata,'$.subtype'), COUNT(*) FROM nodes WHERE type='agent_content' GROUP BY 1 ORDER BY 2 DESC"):
        print(f"  {(row[0] or '?'):28} {row[1]}")
    print("\nEdges by relation:")
    for row in conn.execute("SELECT relation, COUNT(*) FROM edges GROUP BY relation ORDER BY 2 DESC"):
        print(f"  {row[0]:20} {row[1]}")


def main():
    p = argparse.ArgumentParser(description="Context Tree — task-structured history and selective context")
    p.add_argument("-q", "--quiet", action="store_true")
    p.add_argument("--db", help="Explicit database path; uses a separate sibling cache")
    p.add_argument("--cache-dir", help="Explicit turn cache directory")
    p.add_argument("--sessions-dir", help="Explicit source-session JSONL directory")
    p.add_argument("--allow-network", action="store_true", help="Allow model/API requests after reviewing privacy implications")
    p.add_argument("--request-limit", type=int, help="Maximum actual model/embedding requests")
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("sync")
    sp.add_argument("--limit", type=int)
    sp.add_argument("--session")
    sp.add_argument("--model", default=None, help="Override every LLM stage")
    sp.add_argument("--stage-model", action="append", default=[], metavar="STAGE=MODEL")
    sp.add_argument("--stage-effort", action="append", default=[], metavar="STAGE=EFFORT")
    sp.add_argument("--no-reflexion", action="store_true")
    sp.add_argument("--no-framing", action="store_true")
    sp.add_argument("--no-review", action="store_true",
                    help="skip post-extraction tree refinement pass")
    sub.add_parser("stats")
    ep = sub.add_parser("export-obsidian", help="Export tree to Obsidian vault")
    ep.add_argument("--out", required=True, help="output vault directory")
    ep.add_argument("--similarity", type=float, default=0.55,
                    help="cross-session 'see also' link cosine threshold")
    rp = sub.add_parser("retrieve", help="Branch-based retrieval (N candidate contexts)")
    rp.add_argument("query")
    rp.add_argument("--top-n", type=int, default=15, help="lit nodes recall pool size")
    rp.add_argument("--max-iter", type=int, default=4, help="max LLM rounds")
    rp.add_argument("--model", default=None)
    rp.add_argument("--stage-model", action="append", default=[], metavar="STAGE=MODEL")
    rp.add_argument("--stage-effort", action="append", default=[], metavar="STAGE=EFFORT")
    rp.add_argument("--current-session", default=None)
    rp.add_argument("--project", default=None,
                    help="restrict to the exact persisted project path")
    rp.add_argument("--mode", choices=["user", "agent"], default="user",
                    help="output style: user=conversational answer, agent=tagged facts for context injection")
    rp.add_argument("--verbose", action="store_true",
                    help="include branch details + action history")
    sub.add_parser("models", help="List account-accessible Copilot models")
    ip = sub.add_parser("index-identifiers", help="Backfill literal identifiers without LLM calls")
    ip.add_argument("--project")
    args = p.parse_args()
    if args.cmd in ("sync", "retrieve", "models") and not args.allow_network:
        p.error("This command requires --allow-network; it may send dialogue to the configured model provider")
    store.configure_paths(args.db, args.cache_dir)
    if args.sessions_dir:
        from pathlib import Path
        claude_adapter.CLAUDE_PROJECTS = Path(args.sessions_dir).expanduser().resolve()
    import context_tree.common.llm as copilot_api
    copilot_api.REQUEST_LIMIT = args.request_limit
    copilot_api.configure_stages(getattr(args, "model", None),
                                 getattr(args, "stage_model", []),
                                 getattr(args, "stage_effort", []))
    if args.cmd == "models":
        for model in copilot_api.list_models():
            print(model["id"], model.get("supported_endpoints", []))
    elif args.cmd == "index-identifiers":
        with store.connect() as conn:
            count = indexing.backfill_identifiers(conn, project_path=args.project)
        print(f"Indexed {count} identifier occurrences")
    elif args.cmd == "sync": cmd_sync(args)
    elif args.cmd == "stats": cmd_stats(args)
    elif args.cmd == "retrieve": cmd_retrieve(args)
    elif args.cmd == "export-obsidian":
        from pathlib import Path as _P
        from context_tree.tools.export_obsidian import export as _export
        _export(_P(args.out), similarity_threshold=args.similarity)


if __name__ == "__main__":
    main()
