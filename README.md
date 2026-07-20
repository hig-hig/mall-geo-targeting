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
mall-geo-targeting --project-root . --data-mode estat --accessibility-mode osm --commercial-mode osm

# 到達性を明示的に使わない
mall-geo-targeting --project-root . --accessibility-mode none --commercial-mode none
```

`outputs/` に次を作成します。

- `mesh_scores.csv`: 全メッシュの入力値・来館可能性・獲得ポテンシャルスコア
- `delivery_zones.geojson`: 全メッシュと配信ゾーン判定（GISへ投入可能）
- `map.html`: Canvas分析レイヤーと背景地図を備えた単一HTML

## テスト

```bash
pytest
```

## 実データ投入前の準備と検査

外部データはパイプライン中に自動取得しません。対象モールを決めた後、利用者が手動で取得・確認したファイルを`data/raw/`へ配置します。命名規則、用途別の必須項目、metadata仕様の詳細は`data/raw/README.md`を参照してください。

### 必要なファイル

```text
data/raw/malls/{mall_slug}__mall-profile__YYYYMMDD.yaml
data/raw/malls/{mall_slug}__mall-profile__YYYYMMDD.metadata.yaml
data/raw/estat/{mall_slug}__estat-population-mesh__YYYYMMDD.csv
data/raw/estat/{mall_slug}__estat-population-mesh__YYYYMMDD.metadata.yaml
data/raw/osm/{mall_slug}__osm-features__YYYYMMDD.geojson
data/raw/osm/{mall_slug}__osm-features__YYYYMMDD.metadata.yaml
data/raw/commercial/{mall_slug}__commercial-poi__YYYYMMDD.geojson
data/raw/commercial/{mall_slug}__commercial-poi__YYYYMMDD.metadata.yaml
```

OSM GeoJSONと商業POIが同一ファイルの場合でも、`config/data_sources.yaml`で利用ファイルとmetadataを明示します。データ本体、metadata、処理別設定、`config/licenses.yaml`を一組として更新してください。

### metadata

各データセットに次の項目が必要です。

```yaml
dataset_name: データセット名
source: 提供者・統計名
source_url: 取得元URL
license: ライセンス・利用規約
commercial_use_allowed: true
attribution_required: true
retrieved_at: YYYY-MM-DD
coverage_area: [西端経度, 南端緯度, 東端経度, 北端緯度]
processing: 抽出・変換・加工内容
is_sample: false
```

`is_sample: false`へ書き換えるだけでは実データになりません。取得元、日付、範囲、ライセンス、実ファイルの内容が一致している必要があります。

### validator

```bash
python -m mall_geo_targeting.validation --project-root .
python -m mall_geo_targeting.validation --project-root . --require-real
```

インストールし直した環境では`mall-validate-inputs`コマンドも利用できます。validatorは次を検査します。

- データ本体とmetadataの存在
- YAML、CSV、JSON、GeoJSONとしての読込
- モール設定、e-Stat列、OSMタグ、商業分類の必須項目
- WGS84座標系と緯度経度範囲
- モールID、標準メッシュコード、GeoJSON Feature IDの重複
- e-Statが対象分析メッシュを覆う割合
- GeoJSONが分析半径＋最近接探索bufferを覆うか
- `retrieved_at`の日付形式
- metadataの商用利用可否・出典表示
- `config/licenses.yaml`の対応記録
- サンプルデータの誤使用

通常検査では同梱サンプルを警告として扱います。実分析前は必ず`--require-real`を使用し、エラー0件を確認してください。パイプラインもサンプルモードまたはサンプルmetadataを検出するとログへ警告します。

### 現在固定している対象モール

- イオンモールむさし村山
- 検証済み中心座標：`35.746390, 139.384750`
- 分析用規模値：総賃貸面積約78,000㎡
- `app_value`: `coupon`
- 初期分析半径：10,000m
- OSM・商業POI取得範囲：中心から11,000m以上

対象モールの中心座標は公式アクセス情報とOSM建物Polygonで検証済みです。競合は、ららぽーと立川立飛、イオンモール日の出、モリタウンの3施設です。`attractiveness=1.0`は全施設について非規模補正を適用しない正式仕様です。競合候補は`data/raw/malls/competitor_candidates.yaml`で管理し、住所、代表座標、分析用規模、情報源、取得日が揃うまで分析設定へ追加しません。

モリタウンの分析用規模59,747㎡は、2025年の昭島ロフト出店発表「モリタウン施設概要」で公表された店舗面積です。厳密な国際的GLAではありませんが、比較可能なGLA相当値としてHuff規模項に使用します。施設範囲はモリタウン本体とし、MOVIX昭島、モリパーク アウトドアヴィレッジ、ニトリ、スポーツデポ等は独立したHuff競合へ登録しません。分析半径は10kmです。

## 設定と算出仕様

### 地図表示と指標の役割

地図の連続値凡例は、現在表示中の有効メッシュを20%刻みの五分位で5区分します。表示フィルターを変更すると区切りも再計算されるため、色は表示中範囲内の相対的な位置を表し、案件間の絶対比較には使用できません。配信閾値は凡例区分とは別に、配信適格メッシュ内の上位20%から算出します。スコアが閾値以上でも必須データ条件を満たさないメッシュは配信ゾーンに含めません。

| 指標 | 役割 | 注意 |
|---|---|---|
| 施設相対選択指数 | 競合施設の中から対象施設が相対的に選ばれやすいかを表す | Huffモデル上の相対値であり、実来館確率ではない |
| accessibility | メッシュ周辺の交通環境と対象施設への近接条件を表す | 道路、駅、バス停、駐車場等の代理特徴で、実経路時間ではない |
| commercial | 地域の商業集積・商業活動環境を表す | OSMタグの登録状況に依存し、完全な店舗網羅ではない |
| 総合スコア | 広告配信候補を比較する複合指標 | 重みは統計推定値ではなく現在の分析シナリオ |
| 将来の交通手段別指数 | 特定の交通手段を仮定した施設選択性を表す | accessibilityと重複させず、当初は独立表示する |
| 地域別交通手段割合 | 買物移動に各交通手段が使われる構成を表す | 手段別指数とは別概念で、総合化するときだけ掛け合わせる |

将来の交通手段シナリオ総合指数は、`P_total = share_car × P_car + share_walk × P_walk + share_bike × P_bike + share_rail × P_rail + share_bus × P_bus`として扱います。初期段階では総合スコアへ自動投入せず、既存Huffとの二重計上を避け、実績検証まではシナリオ値として扱います。今回の実装には交通手段別指数の計算は含みません。

モリタウンの59,747㎡は公表店舗面積であり、厳密な国際的GLAではありません。地図では規模種別を「公表店舗面積」、補足を「現行HuffモデルではGLA相当値として使用」と表示します。他の登録3施設はGLAとして表示します。

### 担当者シナリオ設定

担当者が変更できる仮定値は`config/scenarios.yaml`へ集約します。初期設定はすべて`uncalibrated_scenario`であり、統計的に校正された正解値ではありません。施設座標、e-Stat人口、OSM地物、取得日、検証済み施設規模、分析実行結果は観測事実・入力データであり、このシナリオ設定へ複製して自由入力可能な値にはしません。

既存設定との役割分担は次のとおりです。

- 施設選択の既存Huff beta：`config/analysis.yaml`を正とし、シナリオ設定は参照元だけを記録
- 広告スコア重み・必須条件：`config/feature_weights.yaml`を正とし、シナリオ設定は参照元だけを記録
- 地図凡例：現在は表示中メッシュの五分位。将来UIで変更可能にする意図を記録
- 交通手段割合：別概念として無効・未実装。架空の割合は生成しない

車・徒歩・自転車の到達条件付き選択指数は、施設への直線距離、手段別beta、距離別availabilityを使う表示専用シナリオです。対象施設と競合施設の各効用へavailabilityを掛けて正規化します。車は距離上限なし、徒歩は1kmまで100%・4kmで0%、自転車は3kmまで100%・10kmで0%へ線形減衰する初期仮定です。実経路、実所要時間、道路方向、勾配、待ち時間、実来館率を表さず、総合スコア、配信適格、配信ゾーンには使用しません。

出力フィールドは`car_choice_index`、`walk_choice_index`、`bike_choice_index`と、対象施設に対する各`*_availability`です。地図では「到達条件付き選択指数」と表示し、「確率」とは表示しません。将来、速度、待ち時間、乗換抵抗、地域別交通手段割合を追加するときも、観測事実と未校正シナリオを区別し、method versionを更新します。

- `config/malls.yaml`: 対象・競合モールの位置、床面積、魅力度係数、対象モールの`app_value`
- `config/analysis.yaml`: メッシュ幅、分析半径、Huff距離指数、上位ゾーン閾値
- `config/feature_weights.yaml`: 欠損処理方式、有効特徴量、アプリ価値別の重みプリセット
- `config/osm.yaml`: ローカルOSM GeoJSON、座標系、対象タグ・道路種別
- `config/accessibility_weights.yaml`: 到達性6要素の重みと距離・密度の飽和閾値
- `config/commercial.yaml`: 商業POIファイル、座標系、収録カテゴリ、分類タグ
- `config/commercial_weights.yaml`: 商業集積6要素の重みと密度・距離の飽和閾値
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
- `commercial_concentration_index`: ローカル商業POIの分類別密度と最近接距離から作る初期商業集積指数。明示的なサンプルモードでは旧CSVの架空値も利用可能

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

### 必須特徴量グループゲート

coverageは「利用できた元重みの量」を測りますが、施策上必要な情報の種類までは保証しません。例えばcouponでは、Huff・到達性・商業集積だけでcoverage 0.55に達しても、対象人口が不明な地域を新規顧客獲得の配信候補にはしません。

`required_feature_groups`は特徴量を意味別にまとめ、`require_any`または`require_all`で必須条件を定義します。

```yaml
required_feature_groups:
  demographic:
    require_any:
      - target_age_population_index
      - household_composition_index
  mall_relationship:
    require_all:
      - huff_visit_probability
  context:
    require_any:
      - accessibility_index
      - commercial_concentration_index
```

初期coupon設定では次をすべて満たす必要があります。

- `demographic`: 対象年代人口または世帯構成の少なくとも一方
- `mall_relationship`: Huff来館可能性
- `context`: 到達性または商業集積の少なくとも一方

最終的な配信適格条件は次のとおりです。

```text
score_coverage >= minimum_score_coverage
AND required_feature_gate_passed == true
AND 獲得ポテンシャルスコアが算出済み
```

必須グループを満たさない場合もスコアは削除せず、監査・分析用に保持します。配信ゾーン閾値の分位点はcoverageと必須グループの両方を満たすメッシュだけから算出します。

アプリ価値別の変更は`required_feature_group_overrides`で行います。`replace: true`なら共通グループを一式置換し、`false`なら同名グループだけ上書きします。初期設定には、将来parkingアプリで人口要件を緩和できる構造例として、demographicを含まない置換設定があります。実運用では施策リスクと説明責任を確認して変更してください。

出力には次の監査情報を含めます。

- `used_features`: 実際に使用した特徴量
- `missing_features`: 有効だが欠損していた特徴量
- `used_weights`: 欠損処理後、実際に適用した正規化済み重み
- `score_method`: スコア方式、`app_value`、欠損処理方式
- `score_coverage`: 元重みに基づく利用可能情報の割合
- `score_quality_tier`: coverageに基づくA～Dの品質ランク
- `feature_count_used`: 実際に使用した特徴量数
- `feature_count_enabled`: 設定上有効な特徴量数
- `eligible_for_delivery`: minimum coverageと必須特徴量ゲートを満たし、配信候補評価に利用可能か
- `required_groups_passed`: 条件を満たした必須特徴量グループ
- `required_groups_missing`: 不足している必須特徴量グループ
- `required_feature_gate_passed`: 全必須グループを満たしたか

`eligible_for_delivery`はminimum coverageと必須特徴量ゲートの両方を反映します。

### smartphone_affinityの非推奨化

地域単位のスマホ利用親和性を直接示し、商用利用条件も確認済みの信頼できるデータを用意できていないため、`smartphone_affinity`はスコア構成と必須項目から除外しました。旧CSVを読み込む後方互換性と旧出力列だけは維持しますが、値はスコアへ一切影響しません。人口や年代から架空のスマホ利用率を生成することもありません。

同様に、`data/sample_population.csv`内の`accessibility_index`は後方互換用の架空サンプルとして非推奨です。`accessibility_mode=sample`を明示した場合だけ利用し、`osm`ではローカルGeoJSON由来値が必ず優先され、`none`では欠損に戻します。

`commercial_concentration_index`も旧CSV内の架空値は非推奨です。`commercial_mode=sample`の場合だけ利用し、`osm`または`file`ではローカルGeoJSON由来値が必ず優先され、`none`では欠損に戻します。

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

## 商業POIモード

商業POIもパイプライン実行中には外部APIやWebサイトから取得しません。利用者が手動取得したWGS84 GeoJSONを使います。

### 1. データ源と配置

初期版の主入力はOpenStreetMapのPOIです。次の2方式を選べます。

- `commercial_mode=osm`: `config/osm.yaml`と同じGeoJSONから道路・交通と商業POIを同時抽出
- `commercial_mode=file`: `config/commercial.yaml`の別GeoJSONを利用

別ファイルは次へ配置します。

```text
data/raw/commercial/your_commercial_poi.geojson
```

PointとPolygonに対応します。分類タグは`config/commercial.yaml`で変更でき、最低限、小売、スーパー、コンビニ、飲食店、カフェ、娯楽、サービス、オフィス、ホテル、学校、保育施設を分類します。`available_categories`には、そのファイルが収録対象としているカテゴリだけを明記してください。

- 収録対象カテゴリでメッシュ内に地物がない：観測された0件
- 収録対象外カテゴリ：欠損

抽出範囲不足を0件と誤認しないよう、分析範囲と最近接距離の評価範囲を十分に覆うファイルを用意してください。架空の店舗や施設は生成しません。

### 2. Polygonと空間集計

Pointは所属メッシュへ集計します。Polygonは重心だけでは判定せず、Polygon頂点のメッシュ包含、メッシュ角のPolygon包含、境界線交差を確認し、空間的に重なる全メッシュへ1件ずつ集計します。最近接距離もローカルメートル投影上でPolygon内部または境界まで計算します。経度・緯度の単純差は使用しません。

出力する主な監査値は次のとおりです。

- `retail_count`、`supermarket_count`、`convenience_store_count`
- `restaurant_count`、`cafe_count`
- `entertainment_count`、`service_count`、`office_count`、`hotel_count`
- `commercial_poi_total`、`commercial_poi_density`
- `nearest_commercial_poi_distance_m`
- `commercial_concentration_index`
- `commercial_coverage`、`commercial_used_components`

### 3. 商業集積指数

`config/commercial_weights.yaml`で次の6要素を管理します。

- 小売密度
- 飲食密度
- サービス密度
- 娯楽施設密度
- オフィス密度
- 商業POIへの近さ

欠損要素はゼロ補完せず、利用可能な元重みだけで再正規化します。`commercial_coverage`は利用できた元重みの割合です。

この指数はPOIの件数、密度、近さを表す初期特徴量です。店舗の規模、売上、来店客数、購買力、営業状況、データの完全性を保証せず、DL確率でもありません。

### 4. ライセンスと将来拡張

OSMを使う場合はODbLに従い、`© OpenStreetMap contributors`を表示し、加工データベースの共有・提供条件を確認します。別ファイルの場合はデータセットごとに商用利用可否、出典表示、改変、再配布条件を`config/licenses.yaml`へ記録してください。

将来、経済センサス、国土数値情報、自治体オープンデータなどを追加する場合は、各データを共通の分類済みPOIモデルへ変換するアダプターを追加します。人口、到達性、スコア計算を変更せず、`commercial_mode`の入力バックエンドだけを差し替える疎結合方針です。

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

e-Statモードでは取得できた人口・世帯・年齢階級だけを保持します。OSM・商業モードを同時指定しなければ到達性と商業集積は欠損です。既定の`renormalize`では取得できた特徴量とHuffだけで再正規化して獲得ポテンシャルを算出します。人口統計が結合できないメッシュでは、他のモードも無効ならHuffだけの監査用スコアになります。全特徴量を要求する場合は`strict`へ変更してください。15～64歳人口比率は既存出力との互換用属性として計算しますが、厳密な「若年成人比率」ではありません。

## ディレクトリ

```text
config/  設定YAML
data/    架空サンプルと手動配置したe-Stat・OSM・商業POI入力データ
outputs/ 生成物
src/     Pythonパッケージ
tests/   pytest
```

## Vercel静的公開

VercelではPython分析を実行せず、ローカルで生成・検証した地図だけを`public/index.html`として公開します。`outputs/`、CSV、GeoJSON、`data/`は公開ディレクトリに含めません。`public/index.html`は手編集する原稿ではなく、次の手順で作る生成物です。

```bash
.venv/bin/mall-geo-targeting \
  --project-root . \
  --data-mode estat \
  --accessibility-mode osm \
  --commercial-mode osm
.venv/bin/python scripts/prepare_vercel.py
```

公開準備スクリプトは、対象施設、Canvas版識別子、実データモードを検査し、サンプルまたは旧Leaflet版を検出するとコピー前に失敗します。VercelのOutput Directoryは`public`です。

公開物は、URLを知っている人がそのまま閲覧できる静的デモです。`robots.txt`と`noindex`メタタグで検索結果への掲載を抑止しますが、これはアクセス制御や機密保護ではありません。URLが第三者へ共有されれば閲覧でき、HTMLに埋め込まれたメッシュ、スコア、施設情報も抽出できます。

CSV、GeoJSON、rawデータは`public/`へ配置せず、直接公開しません。地図内のe-Stat、© OpenStreetMap contributors、ODbL 1.0、CARTOの帰属表示は削除しないでください。

## 保留中の機能

Google広告向け円形ゾーン生成は、実データを投入した地図、coverage、必須特徴量ゲート、配信候補の妥当性を確認した後に再検討します。現時点ではGoogle広告への接続やゾーン生成を実装していません。
