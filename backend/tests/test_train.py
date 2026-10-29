"""training/train.py: fine-tuning start point and install-only-if-better, with a fake Ultralytics."""

import sys
import types

import pytest

from training import train


@pytest.mark.parametrize("policy,new,old,has,expected", [
    ("never", 0.9, 0.1, True, False),
    ("always", 0.1, 0.9, True, True),
    ("if-better", 0.1, None, False, True),   # nothing installed yet
    ("if-better", 0.6, 0.5, True, True),
    ("if-better", 0.5, 0.5, True, False),    # a tie keeps the installed model
    ("if-better", 0.4, 0.5, True, False),
    ("if-better", None, 0.5, True, False),   # the new model could not be scored
    ("if-better", 0.4, None, True, True),    # the installed model could not be scored (e.g. old classes)
])
def test_should_install(policy, new, old, has, expected):
    assert train.should_install(policy, new, old, has) is expected


class FakeYOLO:
    """Records how it was built and trained; val() scores come from SCORES by weights path."""

    SCORES: dict[str, float] = {}
    built: list[str] = []
    trained: list[dict] = []
    val_splits: list[tuple[str, str]] = []

    def __init__(self, weights):
        self.weights = str(weights)
        FakeYOLO.built.append(self.weights)

    def train(self, **kw):
        FakeYOLO.trained.append(kw)
        best = kw["_best"]
        best.write_text("new weights")
        self.trainer = types.SimpleNamespace(best=str(best))

    def val(self, **kw):
        FakeYOLO.val_splits.append((self.weights, kw["split"]))
        return types.SimpleNamespace(results_dict={train.METRIC["seg"]: FakeYOLO.SCORES.get(self.weights)})


@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "ultralytics", types.SimpleNamespace(YOLO=FakeYOLO))
    monkeypatch.setenv("MODELS_DIR", str(tmp_path / "models"))
    train.get_settings.cache_clear()
    FakeYOLO.built, FakeYOLO.trained, FakeYOLO.SCORES, FakeYOLO.val_splits = [], [], {}, []
    best = tmp_path / "runs" / "best.pt"
    best.parent.mkdir()
    installed = tmp_path / "models" / "trained" / "rescrub-or-seg.pt"
    data = tmp_path / "dataset.yaml"
    data.write_text(f"path: {tmp_path}\ntrain: images/train\nval: images/val\ntest: images/test\n")
    (tmp_path / "images" / "test").mkdir(parents=True)
    (tmp_path / "images" / "test" / "a.jpg").write_text("")
    real_train = FakeYOLO.train

    def train_with_best(self, **kw):
        return real_train(self, _best=best, **kw)

    monkeypatch.setattr(FakeYOLO, "train", train_with_best)

    def go(*extra):
        monkeypatch.setattr(sys, "argv", ["train", "seg", "--data", str(data), *extra])
        train.main()

    yield go, best, installed
    train.get_settings.cache_clear()


def test_fine_tune_starts_from_installed_model_with_gentle_settings(run):
    go, best, installed = run
    installed.parent.mkdir(parents=True)
    installed.write_text("old weights")
    FakeYOLO.SCORES = {str(best): 0.5, str(installed): 0.4}
    go("--from-installed")
    assert FakeYOLO.built[0] == str(installed)
    kw = FakeYOLO.trained[0]
    assert kw["optimizer"] == "AdamW" and kw["lr0"] == train.FINETUNE_LR0 and kw["epochs"] == 40
    assert installed.read_text() == "new weights"
    assert [p.read_text() for p in (installed.parent / "backup").iterdir()] == ["old weights"]


def test_worse_model_is_not_installed(run, capsys):
    go, best, installed = run
    installed.parent.mkdir(parents=True)
    installed.write_text("old weights")
    FakeYOLO.SCORES = {str(best): 0.3, str(installed): 0.4}
    go()
    assert FakeYOLO.built[0] == "yolo26m-seg.pt"  # without --from-installed: released weights
    assert installed.read_text() == "old weights"
    assert not (installed.parent / "backup").exists()
    assert "installed model kept" in capsys.readouterr().out


def test_first_model_is_installed(run):
    go, best, installed = run
    FakeYOLO.SCORES = {str(best): 0.2}
    go("--from-installed")  # nothing installed yet: falls back to released weights
    assert FakeYOLO.built[0] == "yolo26m-seg.pt"
    assert installed.read_text() == "new weights"


def test_install_decision_uses_val_and_test_is_only_reported(run):
    go, best, installed = run
    installed.parent.mkdir(parents=True)
    installed.write_text("old weights")
    FakeYOLO.SCORES = {str(best): 0.5, str(installed): 0.4}
    go()
    assert (str(installed), "val") in FakeYOLO.val_splits and (str(best), "val") in FakeYOLO.val_splits
    assert (str(installed), "test") not in FakeYOLO.val_splits  # the installed model is never scored on test
    assert (str(best), "test") in FakeYOLO.val_splits            # the new one is reported on test


def test_resume_continues_the_run_and_still_installs_only_if_better(run, tmp_path):
    go, best, installed = run
    installed.parent.mkdir(parents=True)
    installed.write_text("old weights")
    run_dir = tmp_path / "runs" / "seg-2"
    (run_dir / "weights").mkdir(parents=True)
    FakeYOLO.SCORES = {str(best): 0.5, str(installed): 0.4}
    go("--resume", str(run_dir))
    assert FakeYOLO.built[0] == str(run_dir / "weights" / "last.pt")
    assert FakeYOLO.trained[0]["resume"] is True
    assert installed.read_text() == "new weights"
