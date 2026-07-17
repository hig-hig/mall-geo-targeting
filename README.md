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

既定値は、従来どおり架空の行帯人口を使うサンプルモードです。

```bash
mall-geo-targeting --project-root . --data-mode sample
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
- `config/licenses.yaml`: データの出典、URL、利用条件、商用利用可否、取得日、加工内容
- `data/sample_population.csv`: 行帯キー（`R_000`等）で結合するサンプル人口・若年成人比率・スマホ親和性。実データでは個別メッシュIDを指定でき、個別値が行帯値より優先されます
- Huff効用: `床面積 × 魅力度 / 距離^距離指数`
- 獲得ポテンシャル: 人口規模35%、若年成人比率25%、スマホ親和性20%、対象モール来館可能性20%の加重スコア（0〜100）
- 配信ゾーン: 欠損のないスコアの上位20%（設定変更可能）

空欄は欠損値として`None`/空セル/GeoJSONの`null`で保持します。数値の`0`は観測されたゼロとして計算に使い、欠損への置換や補完はしません。1項目でも欠損したメッシュの獲得ポテンシャルは欠損とし、配信ゾーンから除外します。

## e-Stat実データモード

外部サイトの自動スクレイピングや自動ダウンロードは行いません。利用者がe-StatからCSVを手動取得し、内容と利用条件を確認して配置します。

### 1. 取得する統計

e-Statの「地図で見る統計（統計GIS）／地域メッシュ統計」から、対象地域を含む次のCSVを取得してください。

- 統計調査：国勢調査
- 集計：人口等基本集計に相当する地域メッシュ統計
- 必須項目：総人口、世帯数、0～14歳人口、15～64歳人口、65歳以上人口
- 地域メッシュ階層：3次メッシュ（8桁、約1km）、2分の1地域メッシュ（9桁、約500m）、または4分の1地域メッシュ（10桁、約250m）
- 調査年：施策で採用する年（設定の`survey_year`と一致させる）

統計表ID、調査年、取得日、利用規約はダウンロード時に控えてください。e-Statの画面・提供ファイルによって列名が異なる場合がありますが、列名は設定で対応できます。複数行ヘッダーや注記行を含むファイルは、統計値や欠損記号を変更せず、1行ヘッダーのCSVとして保存してください。

### 2. ファイル配置

CSVを`data/raw/estat/`へ置きます。同梱の`sample_estat_population.csv`は形式確認用の模擬値で、政府統計の実データではありません。

```text
data/raw/estat/your_estat_population.csv
```

### 3. 設定

`config/analysis.yaml`の`estat`を取得ファイルに合わせます。

```yaml
data_mode: estat
estat:
  path: data/raw/estat/your_estat_population.csv
  encoding: cp932       # utf-8-sig、cp932など
  delimiter: ","
  survey_year: 2020
  table_id: "取得した統計表ID"
  columns:
    standard_mesh_code: 地域メッシュコード
    total_population: 総人口
    households: 世帯数
    age_0_14: 0～14歳人口
    age_15_64: 15～64歳人口
    age_65_plus: 65歳以上人口
  markers:
    missing: ["", "NA"]
    suppressed: ["X", "秘匿"]
    not_applicable: ["-", "対象外"]
```

`config/licenses.yaml`も、実際の出典URL、ライセンス、商用利用可否、取得日、加工内容へ更新してください。商用利用の最終判断は、取得時点の利用規約と組織の法務・データガバナンス方針に従います。

### 4. 実行

設定を書き換えず一時的に実データモードを選ぶこともできます。

```bash
mall-geo-targeting --project-root . --data-mode estat
```

独自の配信分析メッシュID（`M_...`）と標準地域メッシュコードは別フィールドです。

- `mesh_id`: 対象モールを基準に作った独自250m正方形の識別子
- `standard_mesh_code`: 独自メッシュ中心点の10桁標準地域メッシュコード
- `source_standard_mesh_code`: 実際に結合したe-Stat行の8～10桁コード
- `source_survey_year`、`source_table_id`: 元統計の調査年と統計表ID

値の状態は`*_status`列に`observed`、`missing`、`suppressed`、`not_applicable`として出力します。`observed`かつ値が`0`の場合だけ実数ゼロです。他の状態は値を`null`のまま保持し、ゼロ補完しません。

必須の人口統計だけではスマホ親和性を得られないため、実データモードでは`smartphone_affinity`を欠損のまま保持し、現段階の獲得ポテンシャルスコアは算出しません。15～64歳人口比率は既存出力との互換用属性として計算しますが、厳密な「若年成人比率」ではありません。今後、適法な追加データまたは明示的なスコア仕様を決めてから利用します。

## ディレクトリ

```text
config/  設定YAML
data/    架空サンプルと手動配置したe-Stat入力データ
outputs/ 生成物
src/     Pythonパッケージ
tests/   pytest
```
