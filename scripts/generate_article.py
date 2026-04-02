#!/usr/bin/env python3
"""
記事生成スクリプト
Usage: python scripts/generate_article.py --push
"""

import sys
import os
import re
import json
import subprocess
from datetime import datetime
import anthropic


SESSION_TOKEN_FILE = "/home/claude/.claude/remote/.session_ingress_token"
HISTORY_FILE = "data/article_history.json"
DRAFTS_DIR = "drafts"

INVESTMENT_THEMES = [
    "移動平均線の使い方",
    "RSIで売買タイミングを掴む",
    "MACDの基本と活用法",
    "ボリンジャーバンドで相場を読む",
    "ローソク足チャートの読み方",
    "出来高分析の基礎",
    "サポートとレジスタンスライン",
    "フィボナッチリトレースメント入門",
    "一目均衡表の基礎",
    "ストキャスティクスの見方",
    "ATRでボラティリティを測る",
    "パラボリックSARの使い方",
    "ダブルトップ・ダブルボトムの見つけ方",
    "ヘッドアンドショルダーパターン",
    "三角保ち合いのブレイクアウト",
    "トレンドラインの引き方",
    "相対力指数（RSI）のダイバージェンス",
    "ゴールデンクロスとデッドクロス",
    "ピボットポイントの活用",
    "エンベロープの使い方",
    "チャネルラインでの順張り",
    "出来高プロフィールとは",
    "分足チャートと日足チャートの使い分け",
    "平均足チャートの読み方",
    "ランダムウォーク理論とテクニカル分析",
]


def get_auth_client():
    """認証済みのAnthropicクライアントを返す。"""
    if os.path.exists(SESSION_TOKEN_FILE):
        with open(SESSION_TOKEN_FILE) as f:
            token = f.read().strip()
        return anthropic.Anthropic(auth_token=token)
    return anthropic.Anthropic()


def load_history() -> dict:
    os.makedirs("data", exist_ok=True)
    if not os.path.exists(HISTORY_FILE):
        return {"articles": []}
    with open(HISTORY_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_history(history: dict):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def pick_theme(history: dict) -> str:
    used = {a.get("theme", "") for a in history.get("articles", [])}
    for theme in INVESTMENT_THEMES:
        if theme not in used:
            return theme
    # 全テーマ使用済みの場合は最古を再利用
    return INVESTMENT_THEMES[len(history["articles"]) % len(INVESTMENT_THEMES)]


def generate_article(client, theme: str) -> tuple[str, str, list[str]]:
    """Claude API で記事を生成する。Returns: (title, content, tags)"""
    prompt = f"""あなたは投資初心者向けにテクニカル分析を解説するライターです。
以下のテーマで note.com 向け記事を書いてください。

テーマ: {theme}

必ず以下の形式だけで返してください（前後に余分なテキスト不要）:

TITLE: 記事タイトル（魅力的で30字以内）
TAGS: テクニカル分析,投資初心者,株式投資
---CONTENT---
記事本文（マークダウン形式、1500〜2000字）
---END---

記事の要件:
- 投資初心者が理解できる平易な言葉で説明
- 具体的な数値や例を交えて実践的に
- 適切な h2/h3 見出しで構造化
- 導入→解説→まとめの流れ
- 本文は必ず 1500 字以上 2000 字以内"""

    with client.messages.stream(
        model="claude-opus-4-6",
        max_tokens=8192,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        response = stream.get_final_message()

    text = next(b.text for b in response.content if b.type == "text")

    title_match = re.search(r"^TITLE:\s*(.+)$", text, re.MULTILINE)
    tags_match = re.search(r"^TAGS:\s*(.+)$", text, re.MULTILINE)
    content_match = re.search(r"---CONTENT---\s*(.*?)\s*---END---", text, re.DOTALL)

    if not title_match or not content_match:
        raise ValueError(f"レスポンスをパースできませんでした:\n{text}")

    title = title_match.group(1).strip()
    tags = [t.strip() for t in tags_match.group(1).split(",")] if tags_match else ["テクニカル分析", "投資初心者", "株式投資"]
    content = content_match.group(1).strip()
    return title, content, tags


def checker_agent(client, theme: str, title: str, content: str) -> tuple[bool, str]:
    """記事をレビューして (passed, feedback) を返す。"""
    char_count = len(content)
    prompt = f"""あなたは投資記事の品質チェッカーです。以下の記事をレビューしてください。

テーマ: {theme}
タイトル: {title}
文字数: {char_count}字

--- 記事本文 ---
{content}
---

以下の基準で評価し、JSON形式で返してください:
{{
  "result": "PASS" または "FAIL",
  "feedback": "改善点または合格理由（200字以内）"
}}

評価基準:
- 文字数が1500〜2000字の範囲にあること
- 投資初心者向けに平易な説明がされていること
- テーマに沿った内容であること
- 構造（見出し・導入・まとめ）が整っていること"""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    text = message.content[0].text
    block_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    json_match = block_match or re.search(r"\{.*\}", text, re.DOTALL)
    if not json_match:
        return False, "レビュー結果のパースに失敗"
    raw = block_match.group(1) if block_match else json_match.group()
    data = json.loads(raw)
    return data.get("result") == "PASS", data.get("feedback", "")


def save_draft(title: str, content: str, tags: list[str], theme: str) -> str:
    os.makedirs(DRAFTS_DIR, exist_ok=True)
    date_str = datetime.now().strftime("%Y%m%d")
    safe_title = re.sub(r'[\\/:*?"<>|]', "", title)[:40]
    filename = f"{DRAFTS_DIR}/{date_str}_{safe_title}.md"

    if os.path.exists(filename):
        base = filename[:-3]
        i = 2
        while os.path.exists(f"{base}_{i}.md"):
            i += 1
        filename = f"{base}_{i}.md"

    date_iso = datetime.now().strftime("%Y-%m-%d")
    tags_json = json.dumps(tags, ensure_ascii=False)
    frontmatter = f'---\ntitle: "{title}"\ntags: {tags_json}\ntheme: "{theme}"\ndate: {date_iso}\n---\n\n'
    with open(filename, "w", encoding="utf-8") as f:
        f.write(frontmatter + content + "\n")
    return filename


def git_push(filepath: str, title: str):
    """ファイルをステージング・コミット・プッシュする。"""
    subprocess.run(["git", "add", filepath, HISTORY_FILE], check=True)
    msg = f"add: {datetime.now().strftime('%Y%m%d')} {title}"
    subprocess.run(["git", "commit", "-m", msg], check=True)
    for attempt in range(4):
        result = subprocess.run(
            ["git", "push", "-u", "origin", "HEAD:main"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            print("✓ git push 成功")
            return
        wait = 2 ** (attempt + 1)
        print(f"  push 失敗（試行 {attempt+1}/4）, {wait}秒後に再試行...")
        import time; time.sleep(wait)
    raise RuntimeError(f"git push が失敗しました:\n{result.stderr}")


def main():
    if "--push" not in sys.argv:
        print("Usage: python scripts/generate_article.py --push")
        sys.exit(1)

    client = get_auth_client()
    history = load_history()
    theme = pick_theme(history)
    print(f"テーマ選定: {theme}")

    title = content = tags = None
    for attempt in range(3):
        print(f"\n記事生成中... (試行 {attempt+1}/3)")
        title, content, tags = generate_article(client, theme)
        print(f"  タイトル: {title}  文字数: {len(content)}字")

        print("  checker_agent レビュー中...")
        passed, feedback = checker_agent(client, theme, title, content)
        print(f"  結果: {'PASS' if passed else 'FAIL'}  — {feedback}")

        if passed:
            break
        if attempt < 2:
            print("  再生成します...")
    else:
        print("警告: 最大試行回数に達しました。最後の記事を使用します。")

    filepath = save_draft(title, content, tags, theme)
    print(f"\n✓ 下書き保存: {filepath}")

    history["articles"].append({
        "theme": theme,
        "title": title,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "file": filepath,
    })
    save_history(history)
    print("✓ article_history.json 更新")

    print("\ngit commit & push 中...")
    git_push(filepath, title)
    print(f"\n完了: {filepath}")


if __name__ == "__main__":
    main()
