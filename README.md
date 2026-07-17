# モールアプリ獲得ポテンシャル・ジオターゲティング MVP

対象モール周辺を250mメッシュに分割し、人口属性、Huffモデルによる対象モールの来館可能性、新規サービスの獲得ポテンシャルを算出して配信候補ゾーンを出力します。

> 過去のダウンロード実績を学習したモデルではありません。出力値は「DL確率」ではなく、施策優先度を比較するための**獲得ポテンシャルスコア**です。

## セットアップ

Python 3.11以上を用意してください。

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

## 実行

```bash
mall-geo-targeting --project-root .
# または
PYTHONPATH=src python -m mall_geo_targeting --project-root .
```

`outputs/` に次を作成します。

- `mesh_scores.csv`: 全メッシュの入力値・来館可能性・獲得ポテンシャルスコア
- `delivery_zones.geojson`: 全メッシュと配信ゾーン判定（GISへ投入可能）
- `map.html`: 色分けされた確認用Leaflet地図（背景地図の表示にはインターネット接続が必要）

## テスト

```bash
pytest
```

## 設定と算出仕様

- `config/malls.yaml`: 対象・競合モールの位置、床面積、魅力度係数
- `config/analysis.yaml`: メッシュ幅、分析半径、Huff距離指数、上位ゾーン閾値
- `data/sample_population.csv`: 行帯キー（`R_000`等）で結合するサンプル人口・若年成人比率・スマホ親和性。実データでは個別メッシュIDを指定でき、個別値が行帯値より優先されます
- Huff効用: `床面積 × 魅力度 / 距離^距離指数`
- 獲得ポテンシャル: 人口規模35%、若年成人比率25%、スマホ親和性20%、対象モール来館可能性20%の加重スコア（0〜100）
- 配信ゾーン: 欠損のないスコアの上位20%（設定変更可能）

空欄は欠損値として`None`/空セル/GeoJSONの`null`で保持します。数値の`0`は観測されたゼロとして計算に使い、欠損への置換や補完はしません。1項目でも欠損したメッシュの獲得ポテンシャルは欠損とし、配信ゾーンから除外します。

## ディレクトリ

```text
config/  設定YAML
data/    入力データ
outputs/ 生成物
src/     Pythonパッケージ
tests/   pytest
```
