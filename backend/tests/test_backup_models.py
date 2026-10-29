"""training/backup_models.py: trained weights round-trip through the private bucket."""

import pytest

from rescrub.settings import Settings
from rescrub.storage import S3Storage
from training import backup_models as bm


def test_push_list_pull_keeps_the_installed_copy(tmp_path):
    moto = pytest.importorskip("moto")
    with moto.mock_aws():
        store = S3Storage(Settings(s3_bucket="rescrub-test", s3_access_key="k", s3_secret_key="s",
                                   s3_region="us-east-1", s3_endpoint_url=""))
        store.client.create_bucket(Bucket="rescrub-test")
        trained = tmp_path / "trained"
        trained.mkdir()
        (trained / "rescrub-or-seg.pt").write_bytes(b"seg v1")
        (trained / "breach_params.json").write_text("{}")
        (trained / "notes.txt").write_text("not a model")

        assert bm.push(store, "full-1", trained) == ["breach_params.json", "rescrub-or-seg.pt"]
        assert sorted(bm.names(store)["full-1"]) == ["breach_params.json", "rescrub-or-seg.pt"]

        (trained / "rescrub-or-seg.pt").write_bytes(b"seg v2")
        bm.pull(store, "full-1", trained)
        assert (trained / "rescrub-or-seg.pt").read_bytes() == b"seg v1"
        assert [p.read_bytes() for p in (trained / "backup").glob("rescrub-or-seg-*.pt")] == [b"seg v2"]

        with pytest.raises(SystemExit):
            bm.pull(store, "missing", trained)
