from shared.media_sync import content_hash, sync_media


def test_content_hash_is_deterministic_and_hex():
    h1 = content_hash(b"hello")
    h2 = content_hash(b"hello")
    assert h1 == h2
    assert all(c in "0123456789abcdef" for c in h1)


def test_content_hash_differs_for_different_data():
    assert content_hash(b"a") != content_hash(b"b")


def test_sync_media_uses_cache_when_file_exists(tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / "abc123").write_bytes(b"cached")

    calls = []

    def fake_fetch(url):
        calls.append(url)
        return b"should not be called"

    result = sync_media("http://backend", str(cache_dir), ["abc123"], fetch=fake_fetch)

    assert result == {"abc123": str(cache_dir / "abc123")}
    assert calls == []


def test_sync_media_fetches_missing_file(tmp_path):
    cache_dir = tmp_path / "cache"
    calls = []

    def fake_fetch(url):
        calls.append(url)
        return b"downloaded content"

    result = sync_media("http://backend", str(cache_dir), ["newhash"], fetch=fake_fetch)

    assert calls == ["http://backend/api/media/newhash"]
    assert result == {"newhash": str(cache_dir / "newhash")}
    assert (cache_dir / "newhash").read_bytes() == b"downloaded content"


def test_sync_media_skips_failed_fetch_without_crashing(tmp_path):
    cache_dir = tmp_path / "cache"

    def failing_fetch(url):
        raise OSError("netwerk weg")

    result = sync_media("http://backend", str(cache_dir), ["unreachable"], fetch=failing_fetch)

    assert result == {}
