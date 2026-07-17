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

人口データと到達性データは独立して選択できます。

```bash
# e-Stat人口＋ローカルOSM GeoJSON
mall-geo-targeting --project-root . --data-mode estat --accessibility-mode osm

# 到達性を明示的に使わない
mall-geo-targeting --project-root . --accessibility-mode none
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

- `config/malls.yaml`: 対象・競合モールの位置、床面積、魅力度係数、対象モールの`app_value`
- `config/analysis.yaml`: メッシュ幅、分析半径、Huff距離指数、上位ゾーン閾値
- `config/feature_weights.yaml`: 欠損処理方式、有効特徴量、アプリ価値別の重みプリセット
- `config/osm.yaml`: ローカルOSM GeoJSON、座標系、対象タグ・道路種別
- `config/accessibility_weights.yaml`: 到達性6要素の重みと距離・密度の飽和閾値
- `config/licenses.yaml`: データの出典、URL、利用条件、商用利用可否、取得日、加工内容
- `data/sample_population.csv`: 行帯キー（`R_000`等）で結合する架空の人口、対象年代比率、世帯数、到達性、商業集積。実データでは個別メッシュIDを指定でき、個別値が行帯値より優先されます
- Huff効用: `床面積 × 魅力度 / 距離^距離指数`
- 獲得ポテンシャル: 地域特徴量の重み付きスコア（0〜100）。過去DL実績に基づく確率ではありません
- 配信ゾーン: coverage基準を満たすスコアの上位20%（設定変更可能）

空欄は欠損値として`None`/空セル/GeoJSONの`null`で保持します。数値の`0`は観測されたゼロとして計算に使い、欠損への置換や補完はしません。

## 獲得ポテンシャルスコア

初期スコアは次の5特徴量で構成します。

- `target_age_population_index`: `総人口 × 対象年代比率`を分析範囲内の最大値で割った対象年代人口指数
- `household_composition_index`: 世帯数÷総人口。世帯構成を示す初期代理指標で、総人口ゼロまたはいずれかが欠損なら欠損
- `huff_visit_probability`: 対象・競合モールの床面積、魅力度、距離から算出するHuff来館可能性
- `accessibility_index`: ローカルOSM由来の道路・公共交通・駐車場とモール直線距離から作る初期到達性指数。明示的なサンプルモードでは旧CSVの架空値も利用可能
- `commercial_concentration_index`: 店舗・事業所などから将来作る商業集積指数。現在はサンプルCSVの架空値だけ

各指数は0〜1で、重み付き合計を0〜100へ変換します。対象年代は現在のe-Stat模擬データでは15～64歳ですが、施策の実ターゲットに合わせた年齢階級へ今後変更する必要があります。

### アプリ価値と重み

対象モールの`app_value`に応じ、`config/feature_weights.yaml`のプリセットを選びます。

- `coupon`: クーポン訴求
- `parking`: 駐車場・アクセス支援
- `event`: イベント集客
- `crm`: 会員・継続接点
- `tenant_info`: テナント情報探索

重みは初期仮説であり、DL確率を表す学習済み係数ではありません。施策目的、対象年代、検証結果に応じてレビューしてください。

### 欠損処理

`config/feature_weights.yaml`の`missing_policy`で切り替えます。

- `renormalize`: 値が取得できた有効特徴量の重みだけを合計1へ再正規化してスコアを算出。Huffだけでも監査用スコアは残ります
- `strict`: 有効特徴量が1つでも欠ければスコアを欠損にし、配信ゾーンから除外

未実装または使わない特徴量は`enabled_features`を`false`にできます。無効化はゼロ値として扱うこととは異なり、スコア構成から除外されます。`renormalize`では同じ点数でもメッシュごとに構成と情報量が異なり得るため、点数だけを比較せずcoverage、品質ランク、使用特徴量を必ず確認してください。

### スコアcoverageと品質ランク

`score_coverage`は、設定上有効な特徴量の元重み合計に対し、メッシュで実際に利用できた特徴量の元重み合計が占める割合です。再正規化後の重みではなく、選択中の`app_value`プリセットの元重みから計算します。

```text
score_coverage = 利用できた特徴量の元重み合計 / 有効特徴量の元重み合計
```

品質ランクは次の固定基準です。

- A: coverage 0.80以上
- B: coverage 0.60以上、0.80未満
- C: coverage 0.40以上、0.60未満
- D: coverage 0.40未満

例えばcouponプリセットでは、対象年代人口0.30、世帯構成0.15、Huff 0.20が利用できるメッシュはcoverage `0.65`でランクBです。Huffだけならcoverage `0.20`でランクDです。

`minimum_score_coverage`の初期値は`0.40`です。基準未満でも獲得ポテンシャルスコアは監査用に保持しますが、`eligible_for_delivery=false`となり、点数が高くても配信ゾーンには入りません。スコア閾値の分位点も配信適格メッシュだけから算出します。

```yaml
missing_policy: renormalize
minimum_score_coverage: 0.40
```

出力には次の監査情報を含めます。

- `used_features`: 実際に使用した特徴量
- `missing_features`: 有効だが欠損していた特徴量
- `used_weights`: 欠損処理後、実際に適用した正規化済み重み
- `score_method`: スコア方式、`app_value`、欠損処理方式
- `score_coverage`: 元重みに基づく利用可能情報の割合
- `score_quality_tier`: coverageに基づくA～Dの品質ランク
- `feature_count_used`: 実際に使用した特徴量数
- `feature_count_enabled`: 設定上有効な特徴量数
- `eligible_for_delivery`: minimum coverage以上で配信候補評価に利用可能か

### smartphone_affinityの非推奨化

地域単位のスマホ利用親和性を直接示し、商用利用条件も確認済みの信頼できるデータを用意できていないため、`smartphone_affinity`はスコア構成と必須項目から除外しました。旧CSVを読み込む後方互換性と旧出力列だけは維持しますが、値はスコアへ一切影響しません。人口や年代から架空のスマホ利用率を生成することもありません。

同様に、`data/sample_population.csv`内の`accessibility_index`は後方互換用の架空サンプルとして非推奨です。`accessibility_mode=sample`を明示した場合だけ利用し、`osm`ではローカルGeoJSON由来値が必ず優先され、`none`では欠損に戻します。

## OpenStreetMap到達性モード

パイプライン実行中に外部API、Overpass API、OpenStreetMapサイトを呼び出しません。対象モール周辺を十分に含むGeoJSONを利用者が手動取得し、`data/raw/osm/`へ配置します。同梱の`sample_osm.geojson`は処理確認用の模擬形状・模擬タグで、OpenStreetMapの実データではありません。

### 1. 取得・配置

任意の適法なOSMエクスポート手段を使い、分析半径より余裕を持った範囲から次の地物をGeoJSONで取得してください。

- 道路：`LineString`、`highway=*`
- 駅：`Point`、`railway=station|halt`または`public_transport=station`
- バス停：`Point`、`highway=bus_stop`または`public_transport=platform`
- 駐車場：`Point`または`Polygon`、`amenity=parking`

```text
data/raw/osm/your_mall_area.geojson
```

初期アダプターが受け付ける座標系はWGS84（`EPSG:4326`）です。`config/osm.yaml`の`path`を変更し、実ファイルのタグ体系に合わせて`tags`のキー、対象値、幹線道路・歩行可能道路の分類を調整します。

ファイルの抽出範囲が分析範囲全体を覆っていることを確認してください。カテゴリがGeoJSON内に1件もなければ欠損として扱います。一方、そのカテゴリがファイルに存在し、特定メッシュ内に地物がなければ、道路延長や駐車場数は観測されたゼロです。抽出範囲不足を実数ゼロと誤認しないことが利用者の責任になります。

### 2. 初期到達性指数

GeoJSONの経緯度は、対象モールを原点とするローカル正距円筒投影でメートル座標へ変換してから、距離・道路延長・密度を計算します。道路は各分析メッシュ境界でクリッピングしてメッシュ内延長を求めます。経度・緯度の単純差を距離として使用しません。

出力する元特徴量は次のとおりです。

- `road_length_m`
- `major_road_length_m`
- `walkable_road_length_m`
- `nearest_station_distance_m`
- `nearest_bus_stop_distance_m`
- `parking_count`
- `straight_line_distance_to_mall_m`

`accessibility_index`は次の6要素を0〜1へ変換し、`config/accessibility_weights.yaml`の重みで合成します。

- モールへの近さ
- 幹線道路密度
- 歩行可能道路密度
- 駅への近さ
- バス停への近さ
- 駐車場数

欠損要素をゼロにはせず、利用可能要素の重みだけを再正規化します。`accessibility_coverage`は利用可能だった元重みの割合、`accessibility_used_components`は実際に使用した要素です。

この指数は、直線距離と地物密度による説明可能な初期指標です。車・徒歩の経路、道路方向、横断可否、渋滞、ダイヤ、実所要時間を評価しておらず、実移動時間や来館確率ではありません。

### 3. ODbLと出典表示

OpenStreetMap実データはOpen Database License（ODbL）に従います。商用利用は可能ですが、`© OpenStreetMap contributors`の適切な出典表示が必要です。派生・加工データベースを公開または提供する場合は、ODbLの共有条件や提供方法を確認してください。取得日、抽出元、加工内容も`config/licenses.yaml`へ記録します。最終的な利用判断は取得時点の規約と組織の法務・データガバナンス方針に従ってください。

### 4. 将来のルーティング拡張

現在は`osm.py`がGeoJSON読込と特徴量計算を担当し、パイプラインには最終的な`accessibility_index`と監査値を渡します。将来OSRM、Valhalla、GraphHopperなどを導入する場合は、事前構築したローカルルーティング結果を読む別アダプターを追加し、`accessibility_mode`で選択します。人口/e-Stat処理や獲得ポテンシャル計算を変更せず、到達性バックエンドだけを差し替える方針です。

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

e-Statモードでは取得できた人口・世帯・年齢階級だけを保持し、商業集積は欠損のままです。OSMモードを同時指定しなければ到達性も欠損です。既定の`renormalize`では取得できた特徴量とHuffだけで再正規化して獲得ポテンシャルを算出します。人口統計が結合できないメッシュではHuffだけの監査用スコアになりますが、初期coverage基準では配信不適格です。全特徴量を要求する場合は`strict`へ変更してください。15～64歳人口比率は既存出力との互換用属性として計算しますが、厳密な「若年成人比率」ではありません。

## ディレクトリ

```text
config/  設定YAML
data/    架空サンプルと手動配置したe-Stat・OSM入力データ
outputs/ 生成物
src/     Pythonパッケージ
tests/   pytest
```
