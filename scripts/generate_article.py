#!/usr/bin/env python3
"""
記事生成スクリプト
Usage: python scripts/generate_article.py <トピック>
例:   python scripts/generate_article.py "Pythonで始める機械学習"
"""

import sys
import os
import re
import json
from datetime import datetime
import anthropic


def slugify(text: str) -> str:
    """タイトルからURLフレンドリーなスラグを生成する。"""
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"[-\s]+", "-", text)
    return text.strip("-")[:60]


def generate_article(topic: str) -> tuple[str, str, list[str]]:
    """
    Claude API でトピックに関する記事を生成する。
    Returns: (title, content, tags)
    """
    client = anthropic.Anthropic()

    prompt = f"""以下のトピックについて、note.com向けの記事を日本語で書いてください。

トピック: {topic}

必ず以下のJSON形式だけで返してください（前後に余分なテキストは不要）:
{{
  "title": "記事タイトル（魅力的で30字以内）",
  "tags": ["タグ1", "タグ2", "タグ3"],
  "content": "記事本文（マークダウン形式、1000〜2000字程度）"
}}

記事の要件:
- note.comの読者に向けた親しみやすい口調
- 実践的で価値ある情報を含む
- 適切なh2/h3見出しで構造化する
- 導入→本文→まとめの流れを守る"""

    with client.messages.stream(
        model="claude-opus-4-6",
        max_tokens=4096,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        response = stream.get_final_message()

    text = next(b.text for b in response.content if b.type == "text")

    # JSONを抽出
    json_match = re.search(r"\{.*\}", text, re.DOTALL)
    if not json_match:
        raise ValueError(f"レスポンスからJSONを抽出できませんでした:\n{text}")

    data = json.loads(json_match.group())
    return data["title"], data["content"], data.get("tags", [])


def save_article(title: str, content: str, tags: list[str]) -> str:
    """
    記事をmarkdownファイルとして保存する。
    Returns: 保存したファイルパス
    """
    os.makedirs("articles", exist_ok=True)

    date_str = datetime.now().strftime("%Y-%m-%d")
    slug = slugify(title)
    filename = f"articles/{date_str}-{slug}.md"

    # 同名ファイルが存在する場合は連番を付ける
    if os.path.exists(filename):
        base = filename[:-3]
        i = 2
        while os.path.exists(f"{base}-{i}.md"):
            i += 1
        filename = f"{base}-{i}.md"

    tags_json = json.dumps(tags, ensure_ascii=False)
    frontmatter = f'---\ntitle: "{title}"\ntags: {tags_json}\ndate: {date_str}\n---\n\n'

    with open(filename, "w", encoding="utf-8") as f:
        f.write(frontmatter + content + "\n")

    return filename


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/generate_article.py <トピック>")
        print('例:   python scripts/generate_article.py "Pythonで始める機械学習"')
        sys.exit(1)

    topic = " ".join(sys.argv[1:])
    print(f"記事を生成中: {topic}")

    try:
        title, content, tags = generate_article(topic)
        filepath = save_article(title, content, tags)
        print(f"\n✓ 記事を保存しました: {filepath}")
        print(f"  タイトル: {title}")
        print(f"  タグ: {', '.join(tags)}")
        print(f"\n次のステップ: git add {filepath} && git commit -m 'Add article' && git push")
    except Exception as e:
        print(f"✗ エラー: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
