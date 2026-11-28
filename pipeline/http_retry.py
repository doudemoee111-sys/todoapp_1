"""一時的なAPI障害をリトライするHTTPヘルパー。

長尺パイプラインは外部APIを requests で直接叩く(Google TTS=音声 / Stability=画像・
サムネ)。どれも一時的な 5xx・429 を返したり、数秒だけ接続が切れたりする(実際に
ショート側では Stability の ReadTimeout(60秒) で1本落ちた)。特にTTSは1チャンクの失敗
が動画全体の失敗に直結するため、POSTを短い指数バックオフでリトライして、瞬間的な
不調を「数秒の待ち」に変える。
"""

import time

import requests

# リトライする価値のあるステータス(レート制限とゲートウェイ/バックエンドの一時不調)。
TRANSIENT_STATUSES = frozenset({429, 500, 502, 503, 504})


def request_with_retry(
    method: str,
    url: str,
    *,
    max_attempts: int = 4,
    base_delay: float = 2.0,
    transient_statuses=TRANSIENT_STATUSES,
    **kwargs,
) -> requests.Response:
    """HTTPリクエストを送り、一時的な失敗を指数バックオフでリトライする。

    接続/タイムアウト系の例外と、一時的なHTTPステータス(429/500/502/503/504)を
    リトライ対象とし、試行の間に base_delay * 2**attempt 秒(2, 4, 8…)だけ待つ。
    呼び出し側が既存のステータス判定/raise_for_status をそのまま使えるよう、最終的な
    Response を返す(一時的でないステータスは即座に返す)。全試行で応答が得られなければ
    最後に発生したネットワーク例外を再送出する。
    """
    last_exc: Exception | None = None
    resp: requests.Response | None = None
    for attempt in range(max_attempts):
        try:
            resp = requests.request(method, url, **kwargs)
        except requests.exceptions.RequestException as exc:
            last_exc = exc
            if attempt == max_attempts - 1:
                raise
            time.sleep(base_delay * (2 ** attempt))
            continue
        if resp.status_code in transient_statuses and attempt < max_attempts - 1:
            time.sleep(base_delay * (2 ** attempt))
            continue
        return resp
    if resp is not None:
        return resp
    assert last_exc is not None
    raise last_exc
