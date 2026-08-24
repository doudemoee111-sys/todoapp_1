"""チャンネルの概要欄・キーワード・バナーを実際に適用する(一回限りの実行用)"""

from pathlib import Path

from youtube_branding import update_description_and_keywords, upload_banner

DESCRIPTION = """\
🌍 Daily Trivia Shorts | 毎日の雑学ショート

Quick, fascinating facts from around the world — animals, history, science, \
culture, and everyday mysteries, explained in under 60 seconds.

世界中の面白い雑学を毎日お届け。動物・歴史・科学・文化など、知って得する豆知識を \
ショート動画でサクッと紹介します。

📅 New videos every day, multiple languages
🔔 Subscribe for your daily dose of curiosity

#Shorts #Trivia #FunFacts #雑学 #豆知識
"""

KEYWORDS = [
    "trivia",
    "fun facts",
    "shorts",
    "did you know",
    "curiosity",
    "education",
    "knowledge",
    "雑学",
    "豆知識",
    "ショート動画",
]

if __name__ == "__main__":
    update_description_and_keywords(DESCRIPTION, KEYWORDS)
    upload_banner(Path(__file__).parent / "branding" / "banner_final.png")
