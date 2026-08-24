"""雑学ショート動画 自動生成パイプライン CLI

使い方:
    python main.py "猫の意外な雑学"   トピックを指定して生成
    python main.py --auto            トピックもAIにおまかせ
"""

import argparse
import datetime
import json
import re
import sys
from pathlib import Path

import config
import script_gen
import stability_images
import tts
from assemble import assemble_video


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|]', "", name)
    return name.strip()[:50] or "untitled"


def _render_video(script: dict, image_paths: list[Path], language_code: str = "ja") -> Path:
    """台本+画像から1本の動画ファイルを組み立てる(音声合成+字幕+合成+JSON保存)"""
    print(f"  [{language_code}] ナレーション音声を生成中...")
    narration_text = "\n".join(script["lines"])
    audio_path = config.TMP_DIR / f"narration_{language_code}.mp3"
    tts.synthesize(narration_text, audio_path)

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_title = sanitize_filename(script["title"])
    output_path = config.OUTPUT_DIR / f"{safe_title}_{language_code}_{timestamp}.mp4"
    font_path = config.font_for_language(language_code)
    assemble_video(script["lines"], audio_path, output_path, image_paths, font_path=font_path)

    # 台本データを併せて保存(あとで背景だけ作り直す等に使える)
    output_path.with_suffix(".json").write_text(
        json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"  [{language_code}] 完成しました: {output_path}")
    return output_path


def generate_video(
    topic: str | None = None,
    avoid_titles: list[str] | None = None,
    avoid_texts: list[str] | None = None,
) -> tuple[Path, dict]:
    """1本のショート動画(日本語)を生成する。(出力先パス, 台本データ) を返す。

    avoid_titles: 既出タイトル一覧(YouTube直近+その日の既出)。
    avoid_texts: その日の既出台本の全文一覧(タイトル+シナリオ)。似た内容を避けるために使う。
    """
    print("① 台本を生成中...")
    script = script_gen.generate_script(topic, avoid_titles=avoid_titles, avoid_texts=avoid_texts)
    print(f"  タイトル: {script['title']}")
    for line in script["lines"]:
        print(f"    - {line}")

    print("② 背景画像を生成中...")
    image_paths = stability_images.generate_images(script["image_prompts"], config.TMP_DIR / "images")

    print("③ ナレーション・字幕・動画を合成中...")
    output_path = _render_video(script, image_paths, "ja")
    return output_path, script


def generate_multilang_videos(
    topic: str | None = None,
    avoid_titles: list[str] | None = None,
    languages: list[str] | None = None,
) -> list[tuple[Path, dict, str]]:
    """1つのトピックについて複数言語分の動画をまとめて生成する。
    背景画像はトピック単位で1回だけ生成し、全言語で共有する。
    戻り値は [(出力先パス, 台本データ, 言語コード), ...]"""
    languages = languages or list(config.LANGUAGES.keys())

    print("① 台本を生成中(日本語)...")
    base_script = script_gen.generate_script(topic, avoid_titles=avoid_titles)
    print(f"  タイトル: {base_script['title']}")
    for line in base_script["lines"]:
        print(f"    - {line}")

    print("② 背景画像を生成中(全言語で共有)...")
    image_paths = stability_images.generate_images(
        base_script["image_prompts"], config.TMP_DIR / "images"
    )

    results = []
    for lang_code in languages:
        if lang_code == "ja":
            lang_script = base_script
        else:
            print(f"  [{lang_code}] {config.LANGUAGES[lang_code]}に翻訳中...")
            lang_script = script_gen.translate_script(base_script, config.LANGUAGES[lang_code])
            print(f"    タイトル: {lang_script['title']}")

        output_path = _render_video(lang_script, image_paths, lang_code)
        results.append((output_path, lang_script, lang_code))

    return results


def main():
    parser = argparse.ArgumentParser(description="雑学ショート動画を自動生成する")
    parser.add_argument("topic", nargs="?", default=None, help="動画のテーマ(省略時はAIが自動で決める)")
    parser.add_argument("--auto", action="store_true", help="テーマもAIにおまかせする")
    args = parser.parse_args()

    topic = None if args.auto else args.topic
    generate_video(topic)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\n中断しました。")
