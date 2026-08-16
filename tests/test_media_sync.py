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
    valid_hash = "a" * 64  # Valid 64-char lowercase hex hash
    (cache_dir / valid_hash).write_bytes(b"cached")

    calls = []

    def fake_fetch(url):
        calls.append(url)
        return b"should not be called"

    result = sync_media("http://backend", str(cache_dir), [valid_hash], fetch=fake_fetch)

    assert result == {valid_hash: str(cache_dir / valid_hash)}
    assert calls == []


def test_sync_media_fetches_missing_file(tmp_path):
    cache_dir = tmp_path / "cache"
    valid_hash = "b" * 64  # Valid 64-char lowercase hex hash
    calls = []

    def fake_fetch(url):
        calls.append(url)
        return b"downloaded content"

    result = sync_media("http://backend", str(cache_dir), [valid_hash], fetch=fake_fetch)

    assert calls == [f"http://backend/api/media/{valid_hash}"]
    assert result == {valid_hash: str(cache_dir / valid_hash)}
    assert (cache_dir / valid_hash).read_bytes() == b"downloaded content"


def test_sync_media_skips_failed_fetch_without_crashing(tmp_path):
    cache_dir = tmp_path / "cache"
    valid_hash = "c" * 64  # Valid 64-char lowercase hex hash

    def failing_fetch(url):
        raise OSError("netwerk weg")

    result = sync_media("http://backend", str(cache_dir), [valid_hash], fetch=failing_fetch)

    assert result == {}


def test_sync_media_rejects_path_traversal_hashes(tmp_path):
    """Path traversal attempts in hash names should be silently skipped, no fetch attempted."""
    cache_dir = tmp_path / "cache"
    calls = []

    def fake_fetch(url):
        calls.append(url)
        return b"malicious data"

    # Attempt various path traversal attacks
    malicious_hashes = [
        "../../etc/passwd",
        "../../../evil",
        "..\\..\\windows\\system32",
        "a" * 63,  # too short (63 chars, not 64)
        "g" * 64,  # invalid hex (g is not 0-9a-f)
        "Z" * 64,  # uppercase (should be lowercase)
        "abc123",  # too short, wrong format
    ]

    result = sync_media("http://backend", str(cache_dir), malicious_hashes, fetch=fake_fetch)

    # No hashes should be in result (all rejected)
    assert result == {}

    # No fetch should have been attempted for any of them
    assert calls == []

    # Nothing should be written to disk for these invalid hashes
    assert list(cache_dir.glob("*")) == []


def test_sync_media_accepts_only_valid_sha256_hashes(tmp_path):
    """Only 64-char lowercase hex strings should be accepted."""
    cache_dir = tmp_path / "cache"
    calls = []

    def fake_fetch(url):
        calls.append(url)
        return b"valid content"

    # Create a valid hash by using content_hash
    valid_hash = content_hash(b"test data")  # Should be 64-char lowercase hex
    assert len(valid_hash) == 64
    assert all(c in "0123456789abcdef" for c in valid_hash)

    # Mix valid and invalid hashes
    result = sync_media(
        "http://backend",
        str(cache_dir),
        [valid_hash, "invalid", "../../evil", "Z" * 64],
        fetch=fake_fetch,
    )

    # Only the valid hash should be attempted
    assert calls == [f"http://backend/api/media/{valid_hash}"]
    assert result == {valid_hash: str(cache_dir / valid_hash)}
    assert (cache_dir / valid_hash).read_bytes() == b"valid content"
