"""Long-session soundscape / 作業用BGM generator for 「世界の雑学王」.

戦略シフト(視聴時間効率)の本体。watch hours = 再生数 × 平均視聴時間。1〜3時間の
環境音は 1 再生あたりの視聴“時間”が短尺雑学の 20〜40 倍、言語の壁がなく evergreen。
収益化の核心:

  * 音源は 100% 自作合成（ffmpeg の anoisesrc ノイズ + sine トーンパッド）。既存曲の
    Content-ID フィンガープリントに一致しようがない＝著作権クレームを構造的に回避。
  * 作業用 / 集中 / リラックス / 睡眠という実需の付加価値があり、毎回ミックスを乱数で
    振るので、YouTube 2025「量産型(mass-produced)」ポリシーの“独自性のない複製”にも
    当たりにくい。
  * ナレーション台本・TTS・30 枚スライドショーは使わない。静止画 1 枚（Stability、失敗
    時は ffmpeg グラデにフォールバック）に超低速ズームをかけた短いクリップを stream-loop
    でコピーし、全尺の合成音をかぶせるだけ＝生成が安価で速い。

アップロードは youtube_upload をそのまま再利用するため、チャンネルガード
(EXPECTED_CHANNEL_TITLE=「世界の雑学王」)が効き、別チャンネルへは絶対に投稿しない。

使い方:
  python3 soundscape.py --theme rain                 # 3h 雨音を生成＋予約投稿
  python3 soundscape.py                               # テーマを自動選定(直近と重複回避)
  python3 soundscape.py --theme brown --seconds 600   # 10 分だけ(動作確認用)
  python3 soundscape.py --theme waves --no-upload     # ビルドのみ(投稿しない)
  python3 soundscape.py --theme fire --publish-now    # 予約せず即時公開
  python3 soundscape.py --check-auth                  # 認証とチャンネル名だけ確認
"""
from __future__ import annotations
import argparse
import json
import os
import random
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

import config
from config import (OUTPUT_DIR, VIDEO_W, VIDEO_H, FPS, SOUNDSCAPE_THEMES,
                    SOUNDSCAPE_CATEGORY_ID, SOUNDSCAPE_PUBLISH_HOUR_JST,
                    SOUNDSCAPE_DEFAULT_SECONDS, SOUNDSCAPE_COMMON_TAGS,
                    SOUNDSCAPE_PLAYLIST_TITLE, STABILITY_ENDPOINT, UPLOAD_PRIVACY)

# 音源が自作(非著作権)であることとAI画像利用を明記する開示文(収益化ポリシー対応)。
_DISCLOSURE = (
    "\n\n──────────\n"
    "※この動画の音は、著作権フリーの楽曲ではなく、当チャンネルがシンセサイザー/ノイズ合成で"
    "一から生成したオリジナルの環境音です（既存曲は一切使用していません）。背景画像の生成に"
    "AIを利用しています。安心して作業・勉強・就寝のお供にお使いください。"
)


class SoundscapePreflightError(RuntimeError):
    """前提条件が欠けていて、作業を始める前に確実に失敗すると分かる状態。"""


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


# --------------------------------------------------------------------------- #
# 1. 音の合成（ffmpeg フィルタグラフ）                                          #
# --------------------------------------------------------------------------- #
def _audio_filtergraph(theme_key: str, seconds: int, rng: random.Random) -> str:
    """テーマごとに ffmpeg の filter_complex 文字列を組む。

    すべて自作音源。ノイズ(anoisesrc)を帯域整形した「ベッド」に、テーマによっては
    かすかな detuned なトーンパッド(sine×3=和音)を薄く重ね、ゆっくりした揺れ(tremolo)と
    フェードを付ける。カットオフ周波数・パッドの音程・揺れの速さを毎回乱数で振ることで、
    テンプレ複製化を避ける(量産判定対策)。"""
    fade_out_st = max(1, seconds - 6)

    # --- ベッド(ノイズ)のテーマ別パラメータ --------------------------------
    if theme_key == "brown":
        color, hp, lp = "brown", 40, rng.randint(900, 1300)
        trem_f, trem_d = 0.0, 0.0        # 集中用は揺れなしのフラットなブラウンノイズ
        pad = False
    elif theme_key == "rain":
        color, hp, lp = "pink", rng.randint(300, 460), rng.randint(5500, 7500)
        trem_f, trem_d = round(rng.uniform(0.18, 0.28), 3), 0.25
        pad = True
    elif theme_key == "waves":
        color, hp, lp = "brown", 90, rng.randint(1400, 2000)
        trem_f, trem_d = round(rng.uniform(0.07, 0.11), 3), 0.6   # ゆっくりした寄せ波
        pad = True
    elif theme_key == "fire":
        color, hp, lp = "brown", 70, rng.randint(1700, 2400)
        trem_f, trem_d = round(rng.uniform(0.9, 1.6), 3), 0.35     # パチパチに近い細かな揺れ
        pad = True
    elif theme_key == "forest":
        color, hp, lp = "pink", rng.randint(200, 320), rng.randint(3800, 5200)
        trem_f, trem_d = round(rng.uniform(0.12, 0.2), 3), 0.3
        pad = True
    else:  # night ほか
        color, hp, lp = "pink", rng.randint(150, 260), rng.randint(2600, 3600)
        trem_f, trem_d = round(rng.uniform(0.1, 0.16), 3), 0.3
        pad = True

    parts = [
        f"anoisesrc=color={color}:sample_rate=44100:amplitude=0.9,"
        f"highpass=f={hp},lowpass=f={lp},aformat=channel_layouts=stereo[bed]"
    ]

    if pad:
        # ルート音を乱数で選び(G3〜C4)、短三度/五度を重ねた和音パッドをごく小音量で。
        root = rng.choice([196.0, 207.65, 220.0, 233.08, 246.94, 261.63])
        third = root * (6 / 5 if rng.random() < 0.5 else 5 / 4)  # 短三度/長三度
        fifth = root * 3 / 2
        pad_vol = round(rng.uniform(0.05, 0.09), 3)
        parts += [
            f"sine=frequency={root:.2f}:sample_rate=44100[p1]",
            f"sine=frequency={third:.2f}:sample_rate=44100[p2]",
            f"sine=frequency={fifth:.2f}:sample_rate=44100[p3]",
            f"[p1][p2][p3]amix=inputs=3:normalize=1,volume={pad_vol},"
            f"aecho=0.8:0.88:900:0.4,aformat=channel_layouts=stereo[pad]",
        ]
        mix = "[bed][pad]amix=inputs=2:duration=longest:normalize=0"
    else:
        mix = "[bed]anull"

    tail = mix
    if trem_f > 0:
        tail += f",tremolo=f={trem_f}:d={trem_d}"
    tail += (f",afade=t=in:d=4,afade=t=out:st={fade_out_st}:d=6,"
             f"loudnorm=I=-22:TP=-2:LRA=7[out]")
    parts.append(tail)
    return "; ".join(parts)


def synth_audio(theme_key: str, seconds: int, out_path: Path, rng: random.Random) -> Path:
    graph = _audio_filtergraph(theme_key, seconds, rng)
    print(f"  [audio] 合成中… theme={theme_key} 尺={seconds}s ({seconds/3600:.2f}h)")
    _run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
          "-filter_complex", graph, "-map", "[out]",
          "-t", str(seconds), "-ar", "44100", "-ac", "2",
          "-c:a", "pcm_s16le", str(out_path)])
    return out_path


# --------------------------------------------------------------------------- #
# 2. 静止画(Stability、失敗時は ffmpeg グラデにフォールバック)                  #
# --------------------------------------------------------------------------- #
def _stability_still(prompt: str, out_path: Path) -> bool:
    api_key = os.environ.get("STABILITY_API_KEY")
    if not api_key:
        return False
    try:
        from http_retry import request_with_retry
        full = (f"{prompt}. serene, cinematic, high detail, soft depth, calming, "
                "8k, no text, no words, no watermark, no logo")
        resp = request_with_retry(
            "POST", STABILITY_ENDPOINT,
            headers={"Authorization": f"Bearer {api_key}", "Accept": "image/*"},
            files={"none": ""},
            data={"prompt": full, "aspect_ratio": "16:9", "output_format": "png"},
            timeout=120)
        if resp.status_code == 200:
            out_path.write_bytes(resp.content)
            return True
        print(f"  [image] Stability {resp.status_code}: {resp.text[:140]}")
    except Exception as e:  # noqa: BLE001
        print(f"  [image] Stability 失敗、グラデにフォールバック: {e}")
    return False


def _hex(c: str) -> tuple[int, int, int]:
    c = c.removeprefix("#").removeprefix("0x")
    return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16))


def _vgradient(size: tuple[int, int], top: str, bottom: str):
    """縦方向の2色グラデを PIL で描く(テーマ別配色。ffmpeg の gradients に依存しない)。"""
    from PIL import Image
    w, h = size
    r0, g0, b0 = _hex(top)
    r1, g1, b1 = _hex(bottom)
    img = Image.new("RGB", (w, h))
    px = img.load()
    row = []
    for y in range(h):
        t = y / max(1, h - 1)
        row.append((round(r0 + (r1 - r0) * t),
                    round(g0 + (g1 - g0) * t),
                    round(b0 + (b1 - b0) * t)))
    for y in range(h):
        c = row[y]
        for x in range(w):
            px[x, y] = c
    return img


def _gradient_still(theme: dict, out_path: Path) -> None:
    """テーマ別配色の2色グラデ静止画(動画の背景。テキストは載せない=長時間視聴で邪魔に
    ならない)。Stability残高切れでもテーマごとに色が変わる。"""
    top, bottom = theme.get("bg", ("#0b1a2a", "#244b6b"))
    _vgradient((VIDEO_W, VIDEO_H), top, bottom).save(out_path)


def make_still(theme: dict, out_path: Path, rng: random.Random) -> Path:
    if not _stability_still(theme["image_prompt"], out_path):
        _gradient_still(theme, out_path)
    return out_path


_THUMB_FONTS = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/ipafont-gothic/ipagp.ttf",
]


def _font(size: int):
    from PIL import ImageFont
    for p in _THUMB_FONTS:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:  # noqa: BLE001
                continue
    return ImageFont.load_default()


def make_thumbnail(theme: dict, seconds: int, out_path: Path, bg_still: Path | None = None) -> Path:
    """クリックされるサムネ(1280x720)。テーマ別配色＋日本語テキスト(テーマ語/尺/作業用BGM)＋
    チャンネル識別。Stability があればその写真を暗転して下敷きに、無ければテーマ別グラデ。
    これで『画像が毎回同じ』を解消し、一覧でテーマが一目で分かる。"""
    from PIL import Image, ImageDraw
    W, H = 1280, 720
    top, bottom = theme.get("bg", ("#0b1a2a", "#244b6b"))
    if bg_still and bg_still.exists():
        try:
            base = Image.open(bg_still).convert("RGB").resize((W, H), Image.LANCZOS)
            base = Image.blend(base, Image.new("RGB", (W, H), (0, 0, 0)), 0.45)
        except Exception:  # noqa: BLE001
            base = _vgradient((W, H), top, bottom)
    else:
        base = _vgradient((W, H), top, bottom)
    d = ImageDraw.Draw(base)

    accent = _hex(theme.get("accent", "#ffffff"))
    dur = _hours_label(seconds)
    word = theme.get("word", theme.get("label", ""))

    def _centered(text, font, y, fill, stroke=6):
        bb = d.textbbox((0, 0), text, font=font, stroke_width=stroke)
        d.text(((W - (bb[2] - bb[0])) / 2 - bb[0], y), text, font=font, fill=fill,
               stroke_width=stroke, stroke_fill=(0, 0, 0))

    # 尺バッジ(上部・差し色)
    _centered(f"— {dur} —", _font(60), 70, accent, stroke=5)
    # テーマ語(中央・特大・白)
    _centered(word, _font(150), 250, (255, 255, 255), stroke=8)
    # 用途サブ(下)
    _centered("作業用BGM・環境音", _font(66), 500, (235, 235, 235), stroke=6)
    # チャンネル識別(最下部・差し色)
    _centered("世界の雑学王", _font(40), 628, accent, stroke=4)

    base.save(out_path)
    return out_path


# --------------------------------------------------------------------------- #
# 3. 短い超低速ズームのクリップ → stream-loop で全尺に                          #
# --------------------------------------------------------------------------- #
def _kenburns_clip(still: Path, out: Path, clip_sec: int = 20) -> None:
    frames = FPS * clip_sec
    vf = (f"scale={VIDEO_W*2}:{VIDEO_H*2}:force_original_aspect_ratio=increase,"
          f"crop={VIDEO_W*2}:{VIDEO_H*2},"
          f"zoompan=z='min(zoom+0.0004,1.12)':d={frames}:"
          f"x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2':s={VIDEO_W}x{VIDEO_H}:fps={FPS},"
          f"setsar=1,format=yuv420p")
    # CRF 28: 近似静止のアンビエントでは画質劣化が体感できず、ループ全体の
    # ファイルサイズ(=クリップbytes×ループ回数)をほぼ半減できる。視聴時間が目的で
    # 視聴者は「聴く」ので、映像ビットレートは絞ってアップロードを軽くする。
    _run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-loop", "1",
          "-i", str(still), "-t", str(clip_sec), "-vf", vf,
          "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
          "-r", str(FPS), str(out)])


def render_video(still: Path, audio: Path, seconds: int, out_path: Path) -> Path:
    """静止画の短いズームクリップを stream-loop(コピー)で全尺に伸ばし、全尺の合成音を
    かぶせる。-t で出力長を音に合わせて明示的に打ち切る(-shortest は stream_loop と
    組み合わせると停止しないことがあるため使わない)。動画は再エンコードしない＝安価。"""
    clip = out_path.with_name("_loop_clip.mp4")
    print("  [video] 低速ズームのループ素材を作成…")
    _kenburns_clip(still, clip)
    print(f"  [video] stream-loop で {seconds}s に伸ばして音声をミックス…")
    _run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
          "-stream_loop", "-1", "-i", str(clip), "-i", str(audio),
          "-map", "0:v", "-map", "1:a", "-c:v", "copy",
          "-c:a", "aac", "-b:a", "160k", "-ar", "44100",
          "-t", str(seconds), "-movflags", "+faststart", str(out_path)])
    clip.unlink(missing_ok=True)
    return out_path


# --------------------------------------------------------------------------- #
# 4. メタデータ                                                                 #
# --------------------------------------------------------------------------- #
def _hours_label(seconds: int) -> str:
    h = seconds / 3600
    if abs(h - round(h)) < 0.05 and h >= 1:
        return f"{round(h)}時間"
    m = round(seconds / 60)
    return f"{m}分" if m >= 1 else f"{seconds}秒"


def build_metadata(theme_key: str, theme: dict, seconds: int) -> dict:
    dur = _hours_label(seconds)
    core = theme["title_core"]
    # 用途違いのサブコピーを乱数で振ってタイトルの重複(量産判定)を避ける。
    uses = random.choice([
        "勉強・作業・集中に", "リラックス・安眠に", "集中力アップ・作業用に",
        "癒し・睡眠導入に", "在宅ワーク・読書のお供に"])
    title = f"【{dur}】{core}｜{uses}（オリジナル環境音）"
    desc = (
        f"{core}の{dur}の環境音です。{uses}どうぞ。\n\n"
        "再生しっぱなしでお使いいただけるよう、途切れのない1本の長尺にしています。"
        "作業・勉強・在宅ワーク・就寝前のリラックスに。\n"
        + _DISCLOSURE +
        "\n\nチャンネル登録しておくと、新しい環境音をすぐに見つけられます。"
    )
    tags = list(dict.fromkeys((theme.get("tags") or []) + SOUNDSCAPE_COMMON_TAGS))[:30]
    return {"title": title[:100], "description": desc, "tags": tags}


# --------------------------------------------------------------------------- #
# 5. オーケストレーション                                                       #
# --------------------------------------------------------------------------- #
def _preflight(do_upload: bool) -> None:
    problems: list[str] = []
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            problems.append(f"{tool} が PATH にない → `bash pipeline/setup.sh` を先に実行")
    if do_upload:
        for k in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN"):
            if not os.environ.get(k):
                problems.append(f"{k} 未設定 → YouTube アップロードに必須")
    # STABILITY は任意(無ければグラデ静止画にフォールバックするのでブロックしない)。
    if problems:
        raise SoundscapePreflightError(
            "事前チェックに失敗しました。以下を解消してから再実行してください:\n  - "
            + "\n  - ".join(problems))


def _pick_theme(avoid_titles: list[str]) -> str:
    """直近の投稿タイトルに含まれていないテーマを優先的に選ぶ(連日同じ音を避ける)。"""
    keys = list(SOUNDSCAPE_THEMES.keys())
    random.shuffle(keys)
    for k in keys:
        core = SOUNDSCAPE_THEMES[k]["title_core"]
        if not any(core[:3] in t for t in avoid_titles):
            return k
    return keys[0]


def run(theme_key: str | None, seconds: int, do_upload: bool,
        publish_now: bool = False) -> dict:
    rng = random.Random()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    avoid = []
    if do_upload:
        try:
            from youtube_upload import fetch_recent_titles
            avoid = fetch_recent_titles()
        except Exception as e:  # noqa: BLE001
            print(f"  [dedup] 直近タイトル取得に失敗(重複回避スキップ): {e}")
    if not theme_key:
        theme_key = _pick_theme(avoid)
    if theme_key not in SOUNDSCAPE_THEMES:
        raise SystemExit(f"未知のテーマ「{theme_key}」(利用可能: {', '.join(SOUNDSCAPE_THEMES)})")
    theme = SOUNDSCAPE_THEMES[theme_key]

    work = OUTPUT_DIR / f"soundscape_{theme_key}_{stamp}"
    work.mkdir(parents=True, exist_ok=True)
    print(f"== 作業用BGM/環境音: {theme['label']} == work: {work}")

    audio = synth_audio(theme_key, seconds, work / "audio.wav", rng)
    still = make_still(theme, work / "still.png", rng)
    thumb = make_thumbnail(theme, seconds, work / "thumbnail.png", bg_still=still)
    print(f"  [thumb] テーマ別サムネ生成: {thumb.name}")
    video = render_video(still, audio, seconds, work / "video.mp4")
    audio.unlink(missing_ok=True)  # 大きい中間ファイルは即削除(ディスク節約)
    size_mb = video.stat().st_size / 1e6
    print(f"  [video] 完成: {video} ({size_mb:.0f} MB)")

    meta = build_metadata(theme_key, theme, seconds)
    print(f"  [meta] title: {meta['title']}")

    result = {"theme": theme_key, "seconds": seconds, "work_dir": str(work),
              "video": str(video), "title": meta["title"], "size_mb": round(size_mb)}

    if do_upload:
        from youtube_upload import (upload_video, next_publish_at,
                                    ensure_playlist, add_to_playlist)
        if publish_now:
            vid = upload_video(video, meta["title"], meta["description"], meta["tags"],
                               SOUNDSCAPE_CATEGORY_ID, None, str(thumb), "public")
            result["video_id"] = vid
            result["published"] = "public (即時公開)"
            print(f"  published NOW  https://youtu.be/{vid}")
        else:
            pub = next_publish_at(SOUNDSCAPE_PUBLISH_HOUR_JST)
            vid = upload_video(video, meta["title"], meta["description"], meta["tags"],
                               SOUNDSCAPE_CATEGORY_ID, pub, str(thumb), UPLOAD_PRIVACY)
            result["video_id"] = vid
            result["publish_at_jst"] = pub.isoformat()
            print(f"  scheduled: {pub.isoformat()} (JST)  https://youtu.be/{vid}")
        try:
            pl = ensure_playlist(SOUNDSCAPE_PLAYLIST_TITLE,
                                 "作業・勉強・睡眠に。オリジナル環境音の長尺まとめ。")
            if pl and add_to_playlist(vid, pl):
                result["playlist"] = SOUNDSCAPE_PLAYLIST_TITLE
        except Exception as e:  # noqa: BLE001
            print(f"  [playlist] スキップ: {e}")

    (work / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--theme", default=None,
                    help=f"テーマ ({', '.join(SOUNDSCAPE_THEMES)})。省略で自動選定")
    ap.add_argument("--seconds", type=int, default=SOUNDSCAPE_DEFAULT_SECONDS,
                    help="尺(秒)。既定は config の 3h。動作確認は 300〜600 を推奨")
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--publish-now", action="store_true",
                    help="予約せず即時 public で公開(evergreen を早く稼働させる場合)")
    ap.add_argument("--check-auth", action="store_true")
    ap.add_argument("--rethumb", default=None,
                    help="既存動画のサムネだけ差し替える（新規動画は作らない）。"
                         "書式: 'VIDEOID:theme,VIDEOID:theme'（例 O9EroeX-SsE:waves,JymAdr2dcmc:forest）")
    args = ap.parse_args()

    if args.check_auth:
        from youtube_upload import check_auth
        print(f"[check-auth] OK — 投稿先チャンネル: 「{check_auth()}」")
        return

    if args.rethumb:
        from youtube_upload import set_thumbnail, check_auth
        print(f"[rethumb] 認証チャンネル確認: 「{check_auth()}」（世界の雑学王でなければ上で停止済み）")
        done, failed = [], []
        for item in [x.strip() for x in args.rethumb.split(",") if x.strip()]:
            try:
                vid, theme_key = item.split(":")
            except ValueError:
                print(f"[rethumb] 書式エラー: '{item}'（VIDEOID:theme 形式で）"); failed.append(item); continue
            theme = SOUNDSCAPE_THEMES.get(theme_key.strip())
            if not theme:
                print(f"[rethumb] 未知テーマ: {theme_key}"); failed.append(item); continue
            thumb = make_thumbnail(theme, args.seconds, OUTPUT_DIR / f"_rethumb_{vid.strip()}.png")
            try:
                set_thumbnail(vid.strip(), thumb)
                print(f"[rethumb] ✅ {vid.strip()} ← {theme_key}（{theme.get('label')}）")
                done.append(f"{vid.strip()}({theme_key})")
            except Exception as e:  # noqa: BLE001
                print(f"[rethumb] ❌ {vid.strip()}: {e}"); failed.append(item)
        print(f"\n[rethumb] 完了: 成功 {len(done)}（{', '.join(done)}） / 失敗 {len(failed)}（{', '.join(failed)}）")
        return

    do_upload = not args.no_upload
    _preflight(do_upload)
    t0 = time.time()
    result = run(args.theme, args.seconds, do_upload=do_upload, publish_now=args.publish_now)
    print(f"\nDONE in {time.time()-t0:.0f}s -> {result.get('video_id', '(not uploaded)')}")


if __name__ == "__main__":
    main()
