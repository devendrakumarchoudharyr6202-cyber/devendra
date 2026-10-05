"""Unit tests for planner (no browser needed)."""

from planner import pick_summary, plan_skills


def test_pick_summary_stable_within_hour():
    variants = ["A", "B", "C", "D"]
    from datetime import datetime, timezone

    t = datetime(2026, 7, 30, 10, 15, tzinfo=timezone.utc)
    assert pick_summary(variants, t) == pick_summary(variants, t.replace(minute=59))


def test_plan_keeps_core_and_rotates():
    plan = plan_skills(
        current=["Python", "SQL", "LangChain"],
        core=["Python", "Machine Learning"],
        rotate=["LangChain", "Docker", "AWS", "Redis"],
        policy={
            "min_total": 4,
            "max_total": 10,
            "add_per_run": 1,
            "remove_per_run": 1,
            "protect_core": True,
        },
    )
    assert "Python" in plan.desired
    assert "Machine Learning" in plan.desired
    assert "Python" not in plan.remove
