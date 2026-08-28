from shared.media_sync import (
    content_hash,
    is_content_hash,
    sync_media,
    fetch_scare_video_audio,
    _read_with_size_cap,
    _FETCH_MAX_SIZE,
)


def test_is_content_hash_accepts_a_real_hash():
    assert is_content_hash(content_hash(b"hello")) is True


def test_is_content_hash_rejects_path_traversal_and_wrong_length():
    assert is_content_hash("../../etc/passwd") is False
    assert is_content_hash("a" * 63) is False
    assert is_content_hash("a" * 65) is False
    assert is_content_hash("A" * 64) is False  # alleen lowercase hex


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
    expected_content = b"downloaded content"
    valid_hash = content_hash(expected_content)  # Hash must match the content
    calls = []

    def fake_fetch(url):
        calls.append(url)
        return expected_content

    result = sync_media("http://backend", str(cache_dir), [valid_hash], fetch=fake_fetch)

    assert calls == [f"http://backend/api/media/{valid_hash}"]
    assert result == {valid_hash: str(cache_dir / valid_hash)}
    assert (cache_dir / valid_hash).read_bytes() == expected_content


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
    expected_content = b"test data"

    def fake_fetch(url):
        calls.append(url)
        return expected_content

    # Create a valid hash by using content_hash
    valid_hash = content_hash(expected_content)  # Should be 64-char lowercase hex
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
    assert (cache_dir / valid_hash).read_bytes() == expected_content


def test_sync_media_rejects_content_mismatch(tmp_path):
    """Fetched content that doesn't hash to the requested hash should be skipped, not cached."""
    cache_dir = tmp_path / "cache"
    valid_hash = "d" * 64  # Valid 64-char lowercase hex hash

    def fake_fetch(url):
        # Return data that does NOT match the requested hash
        return b"wrong content"

    result = sync_media("http://backend", str(cache_dir), [valid_hash], fetch=fake_fetch)

    # Hash should be excluded from result (content verification failed)
    assert result == {}

    # No file should be written to disk
    assert list(cache_dir.glob("*")) == []


def test_sync_media_verifies_content_with_real_hash(tmp_path):
    """Fetched content matching the correct hash should be cached."""
    cache_dir = tmp_path / "cache"
    expected_content = b"correct overlay data"
    valid_hash = content_hash(expected_content)  # Create hash of actual content

    def fake_fetch(url):
        return expected_content

    result = sync_media("http://backend", str(cache_dir), [valid_hash], fetch=fake_fetch)

    # Hash should be in result (content verification passed)
    assert result == {valid_hash: str(cache_dir / valid_hash)}

    # File should be written with correct content
    assert (cache_dir / valid_hash).read_bytes() == expected_content


def test_read_with_size_cap_accepts_small_data():
    """Data under size cap should be read successfully."""
    class FakeResp:
        def __init__(self, data):
            self.data = data
            self.pos = 0

        def read(self, size):
            chunk = self.data[self.pos:self.pos+size]
            self.pos += size
            return chunk

    small_data = b"x" * 1000
    resp = FakeResp(small_data)
    result = _read_with_size_cap(resp, max_size=10000)

    assert result == small_data


def test_read_with_size_cap_rejects_oversized_data():
    """Data exceeding size cap should raise ValueError."""
    class FakeResp:
        def __init__(self, data):
            self.data = data
            self.pos = 0

        def read(self, size):
            chunk = self.data[self.pos:self.pos+size]
            self.pos += size
            return chunk

    # Create data that exceeds 1000 byte cap
    oversized_data = b"x" * 2000
    resp = FakeResp(oversized_data)

    try:
        _read_with_size_cap(resp, max_size=1000)
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "exceeds" in str(e)


def test_sync_media_handles_oversized_fetch_error(tmp_path):
    """When fetch raises due to size cap, hash should be excluded from result."""
    cache_dir = tmp_path / "cache"
    valid_hash = "e" * 64

    def oversized_fetch(url):
        # Simulate size cap error
        raise ValueError("Response exceeds 50 MB bytes")

    result = sync_media("http://backend", str(cache_dir), [valid_hash], fetch=oversized_fetch)

    # Hash should be excluded (fetch failed with size cap error)
    assert result == {}

    # No file should be written
    assert list(cache_dir.glob("*")) == []


def test_fetch_scare_video_audio_uses_cache_when_file_exists(tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    video_hash = "a" * 64
    (cache_dir / f"{video_hash}.audio").write_bytes(b"cached-audio")
    calls = []

    def fake_fetch(url):
        calls.append(url)
        return b"should not be called"

    result = fetch_scare_video_audio("http://backend", str(cache_dir), video_hash, fetch=fake_fetch)

    assert result == str(cache_dir / f"{video_hash}.audio")
    assert calls == []


def test_fetch_scare_video_audio_fetches_missing_file(tmp_path):
    cache_dir = tmp_path / "cache"
    video_hash = "b" * 64
    calls = []

    def fake_fetch(url):
        calls.append(url)
        return b"fresh-audio-bytes"

    result = fetch_scare_video_audio("http://backend", str(cache_dir), video_hash, fetch=fake_fetch)

    assert calls == [f"http://backend/api/media/{video_hash}/audio"]
    assert result == str(cache_dir / f"{video_hash}.audio")
    assert (cache_dir / f"{video_hash}.audio").read_bytes() == b"fresh-audio-bytes"


def test_fetch_scare_video_audio_returns_none_on_fetch_failure(tmp_path):
    cache_dir = tmp_path / "cache"
    video_hash = "c" * 64

    def failing_fetch(url):
        raise OSError("404")

    result = fetch_scare_video_audio("http://backend", str(cache_dir), video_hash, fetch=failing_fetch)

    assert result is None


def test_fetch_scare_video_audio_rejects_malformed_hash(tmp_path):
    cache_dir = tmp_path / "cache"

    result = fetch_scare_video_audio(
        "http://backend", str(cache_dir), "not-a-hash", fetch=lambda url: b"x"
    )

    assert result is None
