"""Project scoping against persisted session identity."""

def _project_session_filter(conn, project_path: str | None) -> set[str] | None:
    if not project_path:
        return None
    # Project identity is in the persisted Session, not the JSONL source path.
    # Legacy payloads without project identity fail closed when scoped.
    rows = conn.execute("""SELECT session_id FROM processing_state
        WHERE CASE WHEN json_valid(task_tree_json)
          THEN json_extract(task_tree_json, '$.project_path') END = ?""",
        (project_path,)).fetchall()
    return {r[0] for r in rows}
