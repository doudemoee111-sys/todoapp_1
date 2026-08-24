"""YouTubeチャンネルのブランディング(概要欄・キーワード・バナー画像)を更新する"""

from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from youtube_upload import _get_credentials


def _get_client():
    creds = _get_credentials()
    return build("youtube", "v3", credentials=creds)


def get_channel_id() -> str:
    youtube = _get_client()
    resp = youtube.channels().list(part="id", mine=True).execute()
    items = resp.get("items", [])
    if not items:
        raise SystemExit("エラー: 自分のチャンネルが見つかりませんでした。")
    return items[0]["id"]


def update_description_and_keywords(description: str, keywords: list[str]) -> None:
    youtube = _get_client()
    channel_id = get_channel_id()

    current = youtube.channels().list(part="brandingSettings", id=channel_id).execute()
    branding = current["items"][0]["brandingSettings"]
    branding.setdefault("channel", {})
    branding["channel"]["description"] = description
    branding["channel"]["keywords"] = " ".join(f'"{k}"' if " " in k else k for k in keywords)

    youtube.channels().update(
        part="brandingSettings",
        body={"id": channel_id, "brandingSettings": branding},
    ).execute()
    print("概要欄・キーワードを更新しました。")


def upload_banner(banner_path: Path) -> None:
    youtube = _get_client()
    channel_id = get_channel_id()

    media = MediaFileUpload(str(banner_path), mimetype="image/png")
    resp = youtube.channelBanners().insert(media_body=media).execute()
    banner_url = resp["url"]

    current = youtube.channels().list(part="brandingSettings", id=channel_id).execute()
    branding = current["items"][0]["brandingSettings"]
    branding.setdefault("image", {})
    branding["image"]["bannerExternalUrl"] = banner_url

    youtube.channels().update(
        part="brandingSettings",
        body={"id": channel_id, "brandingSettings": branding},
    ).execute()
    print("バナー画像を更新しました。")
