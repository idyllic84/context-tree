from types import SimpleNamespace
from .run import example, run


def checks():
    payload = example()
    result = run(payload, SimpleNamespace())["branches"]
    return {"siblings_form_one_branch": len(result) == 1,
            "both_hits_retained": {m["node_id"] for m in result[0]["lit_members"]} == {"t1", "t2"},
            "parent_context_retained": "g1" in {n["id"] for n in result[0]["nodes"]}}


def main():
    from ...common.evaluation_runner import main as evaluate_main
    evaluate_main(default_stages=["branches"])


if __name__ == "__main__":
    main()
