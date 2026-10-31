"""Optional local Chromium/CDP integration check using only synthetic data.

Run after starting dedicated Chromium on 9347 and the synthetic viewer on 8937.
Requires developer-only requests and websocket-client; never accesses Xiaomi.
"""
import base64
import json
from pathlib import Path
import time

import requests
import websocket

from mihome_cloud import build_map_snapshot
from mihome_cloud.map_view import write_map_view


def main():
    endpoint = 'http://127.0.0.1:9347'
    origin = 'http://127.0.0.1:8937'
    root = Path('/tmp/mihome-browser-fixture')
    fixture = json.loads(Path('/tmp/mihome-browser-fixture.json').read_text())
    tab = requests.put(endpoint + '/json/new?about:blank', timeout=5).json()
    ws = websocket.create_connection(tab['webSocketDebuggerUrl'], suppress_origin=True, timeout=10)
    seq, errors, external = 0, [], []

    def send(method, params=None):
        nonlocal seq
        seq += 1
        ws.send(json.dumps({'id': seq, 'method': method, 'params': params or {}}))
        while True:
            value = json.loads(ws.recv())
            if value.get('method') == 'Runtime.exceptionThrown':
                errors.append('JavaScript exception')
            if value.get('method') == 'Network.requestWillBeSent':
                if not value['params']['request']['url'].startswith(origin + '/'):
                    external.append('Unexpected non-local request')
            if value.get('id') == seq:
                if 'error' in value:
                    raise AssertionError(value['error'])
                return value.get('result', {})

    def evaluate(expression):
        result = send('Runtime.evaluate', {'expression': expression, 'awaitPromise': True, 'returnByValue': True})
        assert 'exceptionDetails' not in result, 'Evaluation failed'
        return result['result'].get('value')

    def wait_ready():
        for _ in range(100):
            if evaluate("document.querySelector('#map')?.dataset.ready === 'true'"):
                return
            time.sleep(.1)
        raise AssertionError('Viewer did not become ready')

    checks = 0
    try:
        send('Page.enable')
        send('Runtime.enable')
        # CSP restricts viewer resources to self; watch actual requested origins.
        send('Network.enable')
        send('Emulation.setDeviceMetricsOverride', {'width': 1060, 'height': 1000, 'deviceScaleFactor': 1, 'mobile': False})
        send('Page.navigate', {'url': origin + '/index.html'})
        wait_ready()
        assert evaluate("document.querySelector('#title').textContent") == 'Syntetisk testkort'
        assert evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
        assert evaluate("document.querySelector('#status').textContent") == 'Gemt snapshot'
        checks += 3
        evaluate("window.originalPixels=canvas.toDataURL(); byId('transport').click()")
        assert evaluate('canvas.toDataURL() !== window.originalPixels')
        evaluate("window.routePixels=canvas.toDataURL(); byId('labels').click()")
        assert evaluate('canvas.toDataURL() !== window.routePixels')
        evaluate("byId('transport').click(); byId('labels').click()")
        checks += 2
        evaluate('window.originalRaster=raster; window.oldOverlay=snapshot.overlay_revision')
        fixture['position']['x'] += 150
        fixture['paths']['points'].append({'x': fixture['position']['x'], 'y': 2700, 'type': 0})
        write_map_view(build_map_snapshot(fixture, name='Syntetisk testkort'), root)
        evaluate('refresh()')
        assert evaluate('raster === window.originalRaster && snapshot.overlay_revision !== window.oldOverlay')
        checks += 1
        # Atomic floor change also changes raster; names remain plain text.
        fixture['map_id'] = 8
        fixture['origin_x'] = -50
        fixture['width'], fixture['height'] = fixture['height'], fixture['width']
        write_map_view(build_map_snapshot(fixture, name='<img src=x onerror=alert(1)>'), root)
        evaluate('refresh()')
        assert evaluate('snapshot.map.id === 8 && raster !== window.originalRaster')
        assert evaluate("byId('title').querySelector('img') === null")
        checks += 2
        # A corrupt/missing response retains the previous rendered floor.
        (root / 'snapshot.json').write_text('{invalid json')
        evaluate('refresh()')
        assert evaluate("snapshot.map.id === 8 && byId('error').textContent.length > 0")
        checks += 1
        fixture = json.loads(Path('/tmp/mihome-browser-fixture.json').read_text())
        write_map_view(build_map_snapshot(fixture, name='Syntetisk testkort'), root)
        evaluate('refresh()')
        assert evaluate("byId('error').textContent === '' && snapshot.map.id === 7")
        checks += 1
        image = send('Page.captureScreenshot', {'format': 'png'})
        Path('/tmp/mihome-view-desktop.png').write_bytes(base64.b64decode(image['data']))
        send('Emulation.setDeviceMetricsOverride', {'width': 390, 'height': 844, 'deviceScaleFactor': 1, 'mobile': True})
        evaluate('draw()')
        assert evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
        assert evaluate('canvas.width > 0 && canvas.height > 0')
        checks += 2
        image = send('Page.captureScreenshot', {'format': 'png'})
        Path('/tmp/mihome-view-mobile.png').write_bytes(base64.b64decode(image['data']))
        assert not errors, errors
        assert not external, external
        print(f'{checks} browser checks passed; desktop/mobile screenshots saved; synthetic data only.')
    finally:
        ws.close()
        requests.get(endpoint + '/json/close/' + tab['id'], timeout=5)


if __name__ == '__main__':
    main()
