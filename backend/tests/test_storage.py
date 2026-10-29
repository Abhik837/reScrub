import pytest

from rescrub.settings import Settings
from rescrub.storage import S3Storage, parse_range


@pytest.mark.parametrize("header,expected", [
    ("bytes=0-99", (0, 99)), ("bytes=100-", (100, 999)), ("bytes=-10", (990, 999)), ("bytes=900-5000", (900, 999)),
])
def test_parse_range(header, expected):
    assert parse_range(header, 1000) == expected


@pytest.mark.parametrize("header", ["bytes=1000-", "bytes=5-2", "items=0-1", "bytes=0-1,5-6", "bytes=x-"])
def test_parse_range_rejects(header):
    with pytest.raises(ValueError):
        parse_range(header, 1000)


def test_s3_stream_supports_seeking(tmp_path):
    moto = pytest.importorskip("moto")
    with moto.mock_aws():
        s = S3Storage(Settings(s3_bucket="rescrub-test", s3_access_key="k", s3_secret_key="s", s3_region="us-east-1",
                               s3_endpoint_url=""))
        s.client.create_bucket(Bucket="rescrub-test")
        f = tmp_path / "v.mp4"
        f.write_bytes(bytes(range(256)) * 4)
        s.put_file(f, "annotated/x.mp4")
        status, headers, body = s.stream("annotated/x.mp4", None)
        assert status == 200 and headers["Content-Length"] == "1024" and b"".join(body) == f.read_bytes()
        status, headers, body = s.stream("annotated/x.mp4", "bytes=10-19")
        assert status == 206 and headers["Content-Range"] == "bytes 10-19/1024"
        assert b"".join(body) == bytes(range(10, 20))
