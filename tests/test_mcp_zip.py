import io
import json
import zipfile

import httpx
import pytest

import mcp_bridge as bridge


IDS = ['a' * 32, 'b' * 32]


def zip_bytes(names=('one.png', 'two.png')):
    result = io.BytesIO()
    with zipfile.ZipFile(result, 'w') as archive:
        for name in names:
            archive.writestr(name, b'original-file-bytes')
    return result.getvalue()


def configure(monkeypatch, tmp_path, handler):
    monkeypatch.setattr(bridge, 'EXPORT_DIR', tmp_path)
    monkeypatch.setattr(bridge, 'client', lambda: httpx.Client(
        base_url='https://library.example', transport=httpx.MockTransport(handler)))


def test_zip_download_is_one_request_and_only_saves_archive(monkeypatch, tmp_path):
    payload = zip_bytes()
    requests = []

    def respond(request):
        requests.append(request)
        assert request.method == 'POST' and request.url.path == '/api/export'
        assert json.loads(request.content) == {'image_ids': IDS}
        return httpx.Response(200, content=payload)

    configure(monkeypatch, tmp_path, respond)
    result = bridge.export_images_zip(IDS + [IDS[0]])
    assert result['image_count'] == 2 and result['format'] == 'zip'
    assert result['image_content_sent_to_model'] is False
    assert len(requests) == 1
    assert [p.name for p in tmp_path.iterdir()] == [result['filename']]
    assert (tmp_path / result['filename']).read_bytes() == payload


@pytest.mark.parametrize('body,ids', [
    (b'not a zip', IDS),
    (zip_bytes(('one.png',)), IDS),
    (zip_bytes(('../one.png', 'two.png')), IDS),
    (zip_bytes(('one.txt', 'two.png')), IDS),
])
def test_bad_archive_never_leaves_a_saved_file(monkeypatch, tmp_path, body, ids):
    configure(monkeypatch, tmp_path, lambda request: httpx.Response(200, content=body))
    with pytest.raises(ValueError):
        bridge.export_images_zip(ids)
    assert not list(tmp_path.iterdir())


def test_rejected_token_does_not_save_error_page(monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path, lambda request: httpx.Response(401, json={'detail': 'unauthorized'}))
    with pytest.raises(ValueError, match='401'):
        bridge.export_images_zip(IDS)
    assert not list(tmp_path.iterdir())


def test_interrupted_transfer_cleans_partial_download(monkeypatch, tmp_path):
    class Interrupted(httpx.SyncByteStream):
        def __iter__(self):
            yield b'partial download'
            raise httpx.ReadError('connection interrupted')

    configure(monkeypatch, tmp_path, lambda request: httpx.Response(200, stream=Interrupted()))
    with pytest.raises(ValueError):
        bridge.export_images_zip(IDS)
    assert not list(tmp_path.iterdir())


def test_oversized_download_is_stopped(monkeypatch, tmp_path):
    monkeypatch.setattr(bridge, 'MAX_ZIP_DOWNLOAD_BYTES', 10)
    configure(monkeypatch, tmp_path, lambda request: httpx.Response(200, content=zip_bytes()))
    with pytest.raises(ValueError, match='大小'):
        bridge.export_images_zip(IDS)
    assert not list(tmp_path.iterdir())
