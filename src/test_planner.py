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


def test_plan_adds_missing_core_skills():
    plan = plan_skills(
        current=["Python"],
        core=["Python", "Machine Learning", "Angular"],
        rotate=[],
        policy={"add_per_run": 1, "min_total": 1, "max_total": 10},
    )

    assert plan.add == ["Machine Learning"]
    assert "Machine Learning" in plan.desired
    assert "Angular" not in plan.desired


def test_plan_does_not_remove_unconfigured_skills():
    plan = plan_skills(
        current=["Python", "Legacy Framework"],
        core=["Python"],
        rotate=[],
        policy={"remove_per_run": 1, "min_total": 1, "max_total": 10},
    )

    assert plan.remove == []
    assert "Legacy Framework" in plan.desired


def test_plan_removes_only_configured_rotate_skills():
    plan = plan_skills(
        current=["Python", "Legacy Framework", "Rotating Skill"],
        core=["Python"],
        rotate=["Rotating Skill"],
        policy={
            "add_per_run": 0,
            "remove_per_run": 1,
            "min_total": 1,
            "max_total": 10,
        },
    )

    assert plan.remove == ["Rotating Skill"]
    assert "Legacy Framework" in plan.desired


def test_plan_removes_multiple_configured_rotate_skills():
    plan = plan_skills(
        current=["Python", "SQL", "Excel", "Power BI"],
        core=["Python"],
        rotate=["SQL", "Excel", "Power BI"],
        policy={
            "add_per_run": 0,
            "remove_per_run": 3,
            "min_total": 1,
            "max_total": 10,
        },
    )

    assert len(plan.remove) == 3
    assert set(plan.remove) == {"SQL", "Excel", "Power BI"}
