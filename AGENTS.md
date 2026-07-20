# Codex operating rules

## 実行環境

このリポジトリでは、Codexは次の条件で起動される。

* Sandbox: `workspace-write`または`read-only`
* Approval policy: `never`
* Network access: disabled
* Writable root: このリポジトリ内のみ

権限不足、ネットワーク不足、またはサンドボックス境界外の操作が必要になった場合は、回避や権限昇格を試みず停止し、必要な操作を報告すること。

## Codexが担当する作業

Codexが実行してよい作業は、依頼範囲内の次の操作に限定する。

* プロジェクト内ファイルの読み取り
* 明示された範囲のファイル編集
* 既存の`.venv`を使用したPython実行
* プロジェクト既存のテスト
* lintおよび静的検査
* validator
* `git status`
* `git diff`
* `git diff --check`

## Codexが担当しない作業

次の操作はCodexでは行わない。

* `git add`
* `git commit`
* `git push`
* `git pull`
* `git fetch`
* `git merge`
* `git rebase`
* `git cherry-pick`
* `git stash`
* branchやtagの作成・削除
* remoteの変更
* `.git`内部への直接書き込み
* 外部ネットワーク通信
* パッケージの追加または更新
* プロジェクト外への書き込み

これらはユーザーが通常のターミナルから実行する。

## 絶対禁止

以下を実行しない。

* `codex --dangerously-bypass-approvals-and-sandbox`
* `codex --yolo`
* `sudo`
* `git reset --hard`
* `git clean`
* force push
* 既存の未コミット変更の削除
* ユーザー変更の上書き
* サンドボックス制限の回避
* ネットワーク制限の回避
* シェル、OSその他のグローバル設定変更
* 認証情報や秘密鍵の読み取り
* `~/.ssh`、`~/.aws`、`~/.config`等の認証情報領域の読み取り
* APIキーや環境変数の不必要な読み取り
* 無関係なリファクタリング
* 依頼されていない機能追加
* `shapely`、`pyproj`その他の依存関係の無断追加

## 作業開始時

最初に次を実行し、現在地を確認する。

```bash
pwd
git status --short
git status --branch --short
git diff --stat
```

想定外の既存差分がある場合は、編集、削除、stash、stage、commitを行わず、差分内容を報告して停止する。

## 作業手順

作業は原則として次の順番で進める。

1. 現象と現在地を確認する
2. 原因候補を絞る
3. 既存差分を保護する
4. 依頼範囲内で最小限の修正を行う
5. 差分を確認する
6. 必要なテスト、lint、validatorを実行する
7. 実画面または出力結果を確認する
8. Git状態と残件を報告する

一度に複数の独立した問題を修正しない。無関係なファイルやコードには触れない。

## 修正時の原則

* 原因を確認してから修正する
* 差分は必要最小限にする
* 既存の設計、命名、書式に合わせる
* テスト、validator、assertionを削除または弱体化しない
* デバッグコードや一時ファイルを残さない
* 秘密情報や認証情報をコード、ログ、報告に含めない
* 未実行の検証を実行済みとして扱わない
* 完了条件を満たしていない場合は完了と報告しない

## 修正後の確認

作業後に次を実行する。

```bash
git status --short
git diff --stat
git diff --check
git diff
```

次を確認する。

* 意図したファイルだけが変更されている
* 無関係な変更がない
* 既存のユーザー変更を壊していない
* 秘密情報が含まれていない
* デバッグコードが残っていない
* 不要な生成物が追加されていない

## 最終報告

最後に次を分けて報告する。

* 原因
* 実施内容
* 変更ファイル
* 検証結果
* Git状態
* 未解決事項
* 今回対象外とした事項

各検証結果は「成功」「失敗」「未実行」を明確に区別する。
