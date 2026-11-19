import copy

import numpy as np
import pytest

from workprint import manifest, planner, revise

STRUCTURE = {
    "duration": 10.0, "music_in": 12.5,
    "sections": [{"name": "quiet", "from": 0.0, "to": 4.0, "energy": 0.2, "every": 4, "move": "push"},
                 {"name": "drop", "from": 4.0, "to": 8.0, "energy": 1.0, "every": 1}],
    "pins": [{"at": 4.0, "shot": "A003-01"}],
    "end_card": {"dur": 2.0, "text": "WORKPRINT"},
}


def test_draft_lays_cuts_on_the_beat_and_inside_shots(project):
    cut = planner.draft(project, copy.deepcopy(STRUCTURE))
    errors, warnings = manifest.validate(cut, project)
    assert not errors and not warnings, (errors, warnings)
    beats = np.array(project.music()["beats"])
    picture = [c for c in cut["cuts"] if "src" in c]
    for entry in picture[1:]:
        assert np.abs(beats - (entry["at"] + 12.5)).min() <= 1 / 24 + 0.015, entry
    assert [c["at"] for c in picture[:2]] == pytest.approx([0.0, 2.0], abs=0.05)
    assert len([c for c in picture if c["at"] >= 3.9]) == 8          # one cut per beat after the drop
    pinned = next(c for c in picture if abs(c["at"] - 4.0) < 0.03)
    assert pinned["shot"] == "A003-01" and "pinned" in pinned["note"]
    assert cut["cuts"][-1]["id"] == "card" and cut["titles"][0]["text"] == "WORKPRINT"
    assert all(c["note"] for c in cut["cuts"])


def test_draft_is_deterministic(project):
    assert planner.draft(project, copy.deepcopy(STRUCTURE)) == planner.draft(project, copy.deepcopy(STRUCTURE))


def test_validation_catches_real_problems(project):
    fmt = project.format
    cut = manifest.new_cut(fmt, 4.0)
    cut["cuts"] = [{"at": 0.0, "src": "A001", "in": 1.5}, {"at": 1.0, "src": "A004", "in": 2.5},
                   {"at": 3.0, "src": "ZZZ", "in": 0.0, "fx": ["sparkle"]}]
    manifest.normalize(cut)
    errors, warnings = manifest.validate(cut, project)
    assert any("crosses a cut inside A001 at 2.00s" in w for w in warnings)
    assert any("past the end of A004" in e for e in errors)
    assert any("unknown source 'ZZZ'" in e for e in errors) and any("unknown fx 'sparkle'" in e for e in errors)
    assert [c["id"] for c in cut["cuts"]] == ["c001", "c002", "c003"]
    late = manifest.new_cut(fmt, 2.0)
    late["cuts"] = [{"at": 0.5, "src": "A003", "in": 0.0}]
    assert any("must start at 0" in e for e in manifest.validate(manifest.normalize(late), project)[0])


def test_chunk_grouping_depends_only_on_slot_lengths():
    cut = manifest.new_cut({"width": 640, "height": 360, "fps": 24.0}, 4.0)
    cut["cuts"] = [{"at": t, "card": {}} for t in (0.0, 1.0, 1.25, 1.5, 2.0, 3.0)]
    plan = manifest.chunk_plan(manifest.normalize(cut))
    assert [c["slots"] for c in plan] == [[0], [1, 2], [3], [4], [5]]
    assert plan[0]["f1"] == 24 and plan[-1]["f1"] == 96


def test_revision_operations(project):
    cut = planner.draft(project, copy.deepcopy(STRUCTURE))
    before = copy.deepcopy(cut)
    revise.replace(cut, project, "c002", shot="A002-03")
    c2 = manifest.find(cut, "cuts", "c002")
    assert c2["src"] == "A002" and c2["at"] == before["cuts"][1]["at"] and 3.0 <= c2["in"] <= 6.0
    revise.slip(cut, "c002", 0.25)
    assert manifest.find(cut, "cuts", "c002")["in"] == pytest.approx(c2["in"])
    old_at, old_in = c2["at"], c2["in"]
    revise.roll(cut, "c002", by=0.5)
    assert c2["at"] == pytest.approx(old_at + 0.5) and c2["in"] == pytest.approx(old_in + 0.5)
    revise.roll(cut, "c002", to=old_at + 0.4, analysis=project.music(), snap=1)   # snaps back onto a beat
    assert abs(((c2["at"] + 12.5 - 0.5) / 0.5) - round((c2["at"] + 12.5 - 0.5) / 0.5)) < 0.06
    with pytest.raises(revise.ReviseError):
        revise.roll(cut, "c002", to=99.0)
    revise.roll(cut, "c002", to=old_at)                                           # put the cut point and the footage back
    revise.slip(cut, "c002", -0.25)
    assert c2["at"] == pytest.approx(old_at) and c2["in"] == pytest.approx(old_in - 0.25)
    a, b = copy.deepcopy(manifest.find(cut, "cuts", "c003")), copy.deepcopy(manifest.find(cut, "cuts", "c004"))
    revise.swap(cut, "c003", "c004")
    assert manifest.find(cut, "cuts", "c003")["src"] == b["src"] and manifest.find(cut, "cuts", "c003")["at"] == a["at"]
    duration = cut["duration"]
    revise.shift(cut, 8.0, 1.0)
    assert cut["duration"] == duration + 1.0 and manifest.find(cut, "cuts", "card")["at"] == pytest.approx(9.0)
    revise.remove(cut, "c005")
    assert all(c["id"] != "c005" for c in cut["cuts"])
    revise.insert(cut, project, at=5.25, shot="A001-03")
    revise.assign(cut, "look", ["preset=steel", "grain=0.03"])
    revise.assign(cut, "c003", ['move={"zoom": [1, 1.08]}', "note="])
    assert cut["look"] == {"preset": "steel", "grain": 0.03} and "note" not in manifest.find(cut, "cuts", "c003")
    revise.add(cut, "sound", ["at=4.0", "kind=impact", "db=-10"])
    assert not manifest.validate(manifest.normalize(cut), project)[0]
    changes = manifest.diff(before, cut)
    assert "c005" in changes["cuts"]["removed"] and "c002" in changes["cuts"]["changed"] and "look" in changes["settings"]


def test_history_and_undo(project):
    first = planner.draft(project, copy.deepcopy(STRUCTURE))
    assert project.save_cut(first, "first assembly") == 1
    second = copy.deepcopy(first)
    revise.slip(second, "c001", 0.2)
    assert project.save_cut(second, "slip c001") == 2
    assert [v["message"] for v in project.history()] == ["first assembly", "slip c001"]
    assert project.load_version(1) == first and project.cut() == second
