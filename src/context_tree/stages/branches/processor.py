"""Form task-topology branches and expand their observed evidence."""
from ...common.vectors import _cosine, _load_emb
from ..recall.processor import _fetch_task_evidence, _walk_shared_file_tasks

def _natural_branches(lit_nodes: list[dict], all_sessions: dict, conn=None) -> list[dict]:
    """Group lit nodes into branches by structural overlap. Includes temporal
    metadata (first_at/last_at) per node so LLM can assess staleness.

    Returns list[branch], each:
      {
        branch_id, session_id, anchor_id, anchor_kind,
        anchor_name, breadcrumb, status, last_at,
        lit_members: [{node_id, name, sim, kind, last_at}, ...],
        nodes: [{id, name, kind, status, last_at, role, is_lit}, ...],
        lit_count, max_sim,
        _flat, _parent_map, _breadcrumb_map,
        _expanded, _expanded_data,
      }
    """
    # Load time map from task_index + goal_index
    time_map: dict[tuple[str, str], tuple[str, str]] = {}  # (sid, nid) → (first_at, last_at)
    if conn is not None:
        try:
            for sid in sorted({n["session_id"] for n in lit_nodes}):
                for table, key in (("task_index", "task_id"), ("goal_index", "goal_id")):
                    for r in conn.execute(
                            f"SELECT {key}, first_at, last_at FROM {table} WHERE session_id=?", (sid,)):
                        time_map[(sid, r[0])] = (r[1] or "", r[2] or "")
        except Exception:
            pass

    branches = []
    by_session: dict[str, list[dict]] = {}
    for n in lit_nodes:
        by_session.setdefault(n["session_id"], []).append(n)

    for sid, sess_lits in by_session.items():
        sess_tree = all_sessions.get(sid)
        if not sess_tree: continue

        flat: dict[str, dict] = {}
        parent_map: dict[str, str | None] = {}
        breadcrumb_map: dict[str, list[str]] = {}
        def walk(node, parent_id, crumb):
            flat[node["id"]] = node
            parent_map[node["id"]] = parent_id
            breadcrumb_map[node["id"]] = crumb
            for c in node.get("subtasks", []) + node.get("tasks", []):
                walk(c, node["id"], crumb + [node.get("name") or node.get("intent", "")])
        for g in sess_tree.get("goals", []):
            walk(g, None, [])

        sess_lits = [lit for lit in sess_lits if lit["node_id"] in flat]
        lit_id_set = {l["node_id"] for l in sess_lits}
        used = set()
        groups: list[set[str]] = []
        for lit in sess_lits:
            if lit["node_id"] in used: continue
            grp = {lit["node_id"]}
            my_p = parent_map.get(lit["node_id"])
            for other in sess_lits:
                oid = other["node_id"]
                if oid in used or oid == lit["node_id"]: continue
                op = parent_map.get(oid)
                if my_p and op == my_p: grp.add(oid)
                elif oid == my_p: grp.add(oid)
                elif op == lit["node_id"]: grp.add(oid)
            used |= grp
            groups.append(grp)

        for grp in groups:
            members = [l for l in sess_lits if l["node_id"] in grp]
            ancestor_lit = next((l for l in members
                                  if any(parent_map.get(o["node_id"]) == l["node_id"] for o in members)),
                                 None)
            anchor = ancestor_lit or max(members, key=lambda m: m["sim"])
            anchor_id = anchor["node_id"]

            branch_node_ids = set(grp)
            for nid in grp:
                p = parent_map.get(nid)
                if p: branch_node_ids.add(p)
                if p:
                    for other_nid, other_p in parent_map.items():
                        if other_p == p and other_nid != nid:
                            branch_node_ids.add(other_nid)
                node = flat.get(nid, {})
                for c in node.get("subtasks", []) + node.get("tasks", []):
                    branch_node_ids.add(c["id"])

            def role_of(nid: str) -> str:
                if nid == anchor_id: return "anchor"
                if nid in grp: return "lit"
                if nid in {parent_map.get(g) for g in grp}: return "parent"
                for g in grp:
                    if parent_map.get(nid) == g: return "child"
                return "sibling"

            nodes_view = []
            for nid in sorted(branch_node_ids):
                if nid not in flat: continue
                n = flat[nid]
                kind = "goal" if "intent" in n else "task"
                name = n.get("name") or n.get("intent", "")
                first_at, last_at = time_map.get((sid, nid), ("", ""))
                nodes_view.append({
                    "id": nid, "name": name, "kind": kind,
                    "status": n.get("status", ""),
                    "last_at": last_at,
                    "role": role_of(nid),
                    "is_lit": nid in lit_id_set,
                })

            sib_nodes = [n for n in nodes_view if n["role"] == "sibling"]
            if len(sib_nodes) > 6:
                # Trim siblings by time (keep most recent ±3 around anchor time)
                anchor_last = time_map.get((sid, anchor_id), ("", ""))[1]
                if anchor_last:
                    sib_nodes.sort(key=lambda n: abs((n["last_at"] or "9999") < anchor_last))
                keep = set(n["id"] for n in sib_nodes[:6])
                nodes_view = [n for n in nodes_view if n["role"] != "sibling" or n["id"] in keep]

            anchor_first, anchor_last = time_map.get((sid, anchor_id), ("", ""))
            branch = {
                "branch_id": f"{sid}/{anchor_id}",
                "session_id": sid,
                "anchor_id": anchor_id,
                "anchor_kind": "goal" if "intent" in flat[anchor_id] else "task",
                "anchor_name": flat[anchor_id].get("name") or flat[anchor_id].get("intent", ""),
                "breadcrumb": breadcrumb_map.get(anchor_id, []),
                "status": flat[anchor_id].get("status", ""),
                "first_at": anchor_first,
                "last_at": anchor_last,
                "lit_members": [{"node_id": m["node_id"], "name": m["text"],
                                  "sim": m["sim"], "kind": m["kind"],
                                  "last_at": time_map.get((sid, m["node_id"]), ("", ""))[1]}
                                 for m in members],
                "nodes": nodes_view,
                "lit_count": len(members),
                "max_sim": max(m["sim"] for m in members),
                "_flat": flat,
                "_parent_map": parent_map,
                "_breadcrumb_map": breadcrumb_map,
                "_expanded": {},
                "_expanded_data": {},
            }
            branches.append(branch)

    # Sort: recent lit_count weighted by max_sim
    branches.sort(key=lambda b: (-b["lit_count"], -b["max_sim"]))
    return branches


def _walk_ancestor_constraints(branch: dict, target_node_id: str) -> list[dict]:
    """Collect constraints from target node and all ancestors up to root.
    Returns ordered list (most-specific first):
      [{text, scope_id, scope_name, scope_kind, soft}, ...]
    Inheritance: constraint at task X applies to all descendants of X.
    Same scope can have multiple coexisting constraints; later ones may
    semantically override earlier (LLM resolves at use time).
    """
    out: list[dict] = []
    cur = target_node_id
    visited: set[str] = set()
    parent_map = branch.get("_parent_map", {})
    flat = branch.get("_flat", {})
    while cur and cur not in visited:
        visited.add(cur)
        node = flat.get(cur)
        if node:
            scope_kind = "goal" if "intent" in node else "task"
            scope_name = node.get("intent") or node.get("name") or ""
            for c in node.get("constraints", []) or []:
                out.append({"text": c, "scope_id": cur, "scope_kind": scope_kind,
                             "scope_name": scope_name[:50], "soft": False})
            for c in node.get("soft_constraints", []) or []:
                out.append({"text": c, "scope_id": cur, "scope_kind": scope_kind,
                             "scope_name": scope_name[:50], "soft": True})
        cur = parent_map.get(cur)
    return out


def _branch_expand_node(branch: dict, target_node_id: str, exp_type: str, conn,
                        allowed_sessions: set[str] | None = None) -> str:
    """Lazily expand a scoped tree node. Returns status message."""
    sid = branch["session_id"]
    if allowed_sessions is not None and sid not in allowed_sessions:
        return "session outside project scope"
    flat = branch["_flat"]
    # Normalize target: strip "task "/"goal " prefix, strip session prefix
    raw = (target_node_id or "").strip()
    if "/" in raw:
        raw = raw.split("/")[-1]
    for prefix in ("task ", "goal ", "task:", "goal:"):
        if raw.startswith(prefix):
            raw = raw[len(prefix):].strip()
    target_node_id = raw
    if target_node_id not in flat:
        return f"node {target_node_id} not in branch"
    target = flat[target_node_id]

    if branch["_expanded"].get(target_node_id, set()) and exp_type in branch["_expanded"][target_node_id]:
        return f"already expanded: {exp_type} on {target_node_id}"
    branch["_expanded"].setdefault(target_node_id, set()).add(exp_type)
    branch["_expanded_data"].setdefault(target_node_id, {})

    if exp_type == "evidence":
        ev = _fetch_task_evidence(conn, sid, target_node_id, include_agent_content=True, include_files=False)
        branch["_expanded_data"][target_node_id]["evidence"] = ev["agent_content"]
        return f"evidence ({len(ev['agent_content'])} items)"
    if exp_type == "files":
        ev = _fetch_task_evidence(conn, sid, target_node_id, include_agent_content=False, include_files=True)
        branch["_expanded_data"][target_node_id]["files"] = ev["files"]
        # Auto walk-back (Option C): when files are returned, also surface OTHER tasks
        # (any session) whose ac touches the same files. Cheap SQL, broadens context
        # without an extra LLM round-trip. LLM filters in next iteration.
        if ev["files"]:
            file_ids = [f["file_id"] for f in ev["files"]]
            shared = _walk_shared_file_tasks(conn, file_ids,
                                              exclude_task_ids={(sid, target_node_id)}, limit=5,
                                              allowed_sessions=allowed_sessions)
            if shared:
                branch["_expanded_data"][target_node_id]["shared_file_tasks"] = shared
                return f"files ({len(ev['files'])}) + {len(shared)} tasks via shared file"
        return f"files ({len(ev['files'])})"
    if exp_type == "abandoned":
        branch["_expanded_data"][target_node_id]["abandoned"] = target.get("abandoned_alternatives") or []
        # Constraints walk ancestors — inheritance via tree position.
        branch["_expanded_data"][target_node_id]["constraints"] = _walk_ancestor_constraints(branch, target_node_id)
        return f"abandoned ({len(branch['_expanded_data'][target_node_id]['abandoned'])}) + constraints (incl. ancestor)"
    if exp_type == "subtree":
        full = []
        def walk(t, depth):
            full.append({"id": t["id"], "name": t.get("name", ""),
                         "status": t.get("status", ""), "depth": depth,
                         "outcome": t.get("outcome", "")})
            for s in t.get("subtasks", []): walk(s, depth + 1)
        if "intent" in target:
            for t in target.get("tasks", []): walk(t, 0)
        else:
            for s in target.get("subtasks", []): walk(s, 0)
        branch["_expanded_data"][target_node_id]["subtree"] = full
        return f"subtree ({len(full)} descendants)"
    if exp_type == "see_also":
        emb_row = conn.execute(
            "SELECT embedding FROM task_index WHERE session_id=? AND task_id=?",
            (sid, target_node_id)
        ).fetchone()
        if not emb_row or not emb_row[0]:
            branch["_expanded_data"][target_node_id]["see_also"] = []
            return "no embedding"
        seed = _load_emb(emb_row[0])
        rows = conn.execute(
            "SELECT session_id, task_id, name, embedding FROM task_index"
        ).fetchall()
        sims = []
        for r in rows:
            if allowed_sessions is not None and r[0] not in allowed_sessions: continue
            if r[0] == sid: continue
            if not r[3]: continue
            s = _cosine(seed, _load_emb(r[3]))
            if s >= 0.55: sims.append({"session_id": r[0], "task_id": r[1], "name": r[2], "sim": s})
        sims.sort(key=lambda x: -x["sim"])
        branch["_expanded_data"][target_node_id]["see_also"] = sims[:5]
        return f"see_also ({len(sims[:5])})"
    return f"unknown type: {exp_type}"
