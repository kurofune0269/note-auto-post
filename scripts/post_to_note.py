#!/usr/bin/env python3
"""
note.com 投稿スクリプト
Usage:
  # 特定ファイルを投稿
  python scripts/post_to_note.py articles/2024-01-01-my-article.md

  # git diff で自動検出（GitHub Actions から呼び出す場合）
  python scripts/post_to_note.py

環境変数:
  NOTE_EMAIL    - note.com のメールアドレス
  NOTE_PASSWORD - note.com のパスワード
"""

import sys
import os
import json
import subprocess
import requests

NOTE_API_BASE = "https://note.com/api"

# セッションのUser-Agent
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (compatible; note-auto-post/1.0)",
}


def login(email: str, password: str) -> requests.Session:
    """
    note.com にログインしてセッションを返す。

    note.com は Cookie ベースの認証を使用する。
    レスポンスに token が含まれる場合は Authorization ヘッダーも設定する。
    """
    session = requests.Session()
    session.headers.update(HEADERS)

    resp = session.post(
        f"{NOTE_API_BASE}/v1/sessions",
        json={"login": email, "password": password},
        timeout=30,
    )

    if resp.status_code == 401:
        raise RuntimeError("ログイン失敗: メールアドレスまたはパスワードが正しくありません")
    if resp.status_code == 422:
        raise RuntimeError(f"ログイン失敗 (422): {resp.text}")
    resp.raise_for_status()

    data = resp.json()

    # token が返ってくる場合は Authorization ヘッダーに設定
    token = (data.get("data") or {}).get("token")
    if token:
        session.headers.update({"Authorization": f"Bearer {token}"})

    return session


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """
    Markdown のフロントマターを解析する。
    Returns: (meta_dict, body_text)
    """
    if not text.startswith("---"):
        return {}, text

    end_idx = text.find("---", 3)
    if end_idx == -1:
        return {}, text

    fm_text = text[3:end_idx].strip()
    body = text[end_idx + 3:].strip()

    meta: dict = {}
    for line in fm_text.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if key == "title":
            meta["title"] = value.strip('"').strip("'")
        elif key == "tags":
            try:
                meta["tags"] = json.loads(value)
            except json.JSONDecodeError:
                meta["tags"] = []
        elif key == "date":
            meta["date"] = value

    return meta, body


def post_article(session: requests.Session, title: str, body: str) -> str:
    """
    note.com に記事を投稿する。
    Returns: 投稿した記事の URL
    """
    resp = session.post(
        f"{NOTE_API_BASE}/v2/text_notes",
        json={
            "name": title,
            "body": body,
            "status": "published",  # "draft" にすると下書きとして保存
        },
        timeout=30,
    )

    if resp.status_code == 401:
        raise RuntimeError("投稿失敗: 認証エラー（セッションが切れた可能性があります）")
    if resp.status_code == 422:
        raise RuntimeError(f"投稿失敗 (422 バリデーションエラー): {resp.text}")
    resp.raise_for_status()

    data = resp.json().get("data", {})

    # note.com の記事URLを構築
    # レスポンスに noteUrl や key が含まれる
    if "noteUrl" in data:
        return data["noteUrl"]

    note_key = data.get("key", "")
    user_urlname = (data.get("user") or {}).get("urlname", "")
    if user_urlname and note_key:
        return f"https://note.com/{user_urlname}/n/{note_key}"
    if note_key:
        return f"https://note.com/n/{note_key}"

    return "https://note.com (URLの取得に失敗しました)"


def get_new_files_from_git() -> list[str]:
    """
    git diff で今回のコミットで追加された articles/*.md を返す。
    GitHub Actions の push イベントを想定。
    """
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=A", "HEAD~1", "HEAD", "--", "articles/*.md"],
            capture_output=True,
            text=True,
            check=True,
        )
        files = [f.strip() for f in result.stdout.strip().splitlines() if f.strip()]
        return files
    except subprocess.CalledProcessError:
        # HEAD~1 が存在しない（最初のコミット）場合
        result = subprocess.run(
            ["git", "diff-tree", "--no-commit-id", "-r", "--name-only", "--diff-filter=A", "HEAD", "--", "articles/*.md"],
            capture_output=True,
            text=True,
        )
        return [f.strip() for f in result.stdout.strip().splitlines() if f.strip()]


def main():
    email = os.environ.get("NOTE_EMAIL")
    password = os.environ.get("NOTE_PASSWORD")

    if not email or not password:
        print("Error: 環境変数 NOTE_EMAIL と NOTE_PASSWORD を設定してください", file=sys.stderr)
        sys.exit(1)

    # CLI 引数からファイルパスを取得、なければ git diff で自動検出
    if len(sys.argv) > 1:
        files = [f for f in sys.argv[1:] if f.endswith(".md")]
    else:
        print("git diff で新規記事を検出中...")
        files = get_new_files_from_git()

    if not files:
        print("投稿する記事が見つかりませんでした。")
        return

    print(f"{len(files)} 件の記事を投稿します\n")

    # ログイン
    print("note.com にログイン中...")
    try:
        session = login(email, password)
    except Exception as e:
        print(f"✗ ログイン失敗: {e}", file=sys.stderr)
        sys.exit(1)
    print("✓ ログイン成功\n")

    # 各記事を投稿
    success_count = 0
    for filepath in files:
        if not os.path.exists(filepath):
            print(f"⚠ ファイルが見つかりません（スキップ）: {filepath}")
            continue

        with open(filepath, encoding="utf-8") as f:
            content = f.read()

        meta, body = parse_frontmatter(content)
        title = meta.get("title") or os.path.splitext(os.path.basename(filepath))[0]

        print(f"投稿中: {title}")
        try:
            url = post_article(session, title, body)
            print(f"✓ 投稿完了: {url}\n")
            success_count += 1
        except requests.HTTPError as e:
            print(f"✗ 投稿失敗: {e}")
            print(f"  レスポンス: {e.response.text}\n", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"✗ 投稿失敗: {e}\n", file=sys.stderr)
            sys.exit(1)

    print(f"完了: {success_count}/{len(files)} 件を投稿しました")


if __name__ == "__main__":
    main()
