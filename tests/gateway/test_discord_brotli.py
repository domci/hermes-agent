"""Exercise the Brotli decoder used by Discord attachment downloads.

CVE-2026-111497 requires patched native Brotli, not a change to the
attachment reader. These cover its streaming API and the patched decoder's
fail-closed handling of bytes after a complete compressed stream.
"""

import pytest


def test_attachment_brotli_rejects_trailing_bytes():
    brotlicffi = pytest.importorskip("brotlicffi")
    from aiohttp.compression_utils import BrotliDecompressor

    compressed = brotlicffi.compress(b"attachment text")
    decoder = BrotliDecompressor()
    with pytest.raises(brotlicffi.error):
        decoder.decompress_sync(compressed + b"unexpected trailing bytes")


def test_attachment_brotli_streaming_round_trip():
    brotlicffi = pytest.importorskip("brotlicffi")
    from aiohttp.compression_utils import BrotliDecompressor

    content = (b"Discord attachment: UTF-8 text\n" * 1024) + bytes(range(256))
    compressed = brotlicffi.compress(content)
    decoder = BrotliDecompressor()
    decoded = b"".join(
        decoder.decompress_sync(compressed[offset:offset + 7])
        for offset in range(0, len(compressed), 7)
    )
    assert decoded + decoder.flush() == content
