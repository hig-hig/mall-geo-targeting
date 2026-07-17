# 実データ受け入れディレクトリ

この配下は利用者が手動取得した入力データと、その来歴を記録するmetadataの配置先です。パイプラインやvalidatorは外部API・Webサイトへアクセスしません。

## 命名規則

```text
{mall_slug}__{dataset_type}__{survey_or_retrieved_date}.{extension}
{mall_slug}__{dataset_type}__{survey_or_retrieved_date}.metadata.yaml
```

- `mall_slug`: 半角小文字・数字・ハイフン。例 `tokyo-bay-mall`
- `dataset_type`: `mall-profile`、`estat-population-mesh`、`osm-features`、`commercial-poi`
- 日付: `YYYYMMDD`。統計は調査基準日または調査年、地物は取得日
- 拡張子: e-Statは`.csv`、地物は`.geojson`、モール定義は`.yaml`

例：

```text
estat/tokyo-bay-mall__estat-population-mesh__20201001.csv
estat/tokyo-bay-mall__estat-population-mesh__20201001.metadata.yaml
osm/tokyo-bay-mall__osm-features__20260717.geojson
osm/tokyo-bay-mall__osm-features__20260717.metadata.yaml
```

ファイルを配置したら`config/data_sources.yaml`を更新します。パイプラインの実データパスはこの台帳を参照します。文字コード、列名、タグ分類などは各処理設定へ記録します。データ本体だけを差し替えないでください。

## 共通metadata必須項目

- `dataset_name`
- `source`
- `source_url`
- `license`
- `commercial_use_allowed`
- `attribution_required`
- `retrieved_at`（`YYYY-MM-DD`）
- `coverage_area`（WGS84 bbox: `[西, 南, 東, 北]`）
- `processing`
- `is_sample`

実データでは`is_sample: false`とし、取得時点の利用規約、出典表示、再配布条件を確認します。`is_sample`を書き換えるだけでは実データになりません。

## 用途別要件

### `malls/`

- 対象・競合モールのID、名称、緯度、経度、床面積、魅力度
- 対象モールには`app_value`
- 座標はWGS84、緯度-90〜90、経度-180〜180
- IDは重複不可
- 位置・床面積の確認元と確認日をmetadataへ記録

### `estat/`

- 標準地域メッシュコード、総人口、世帯数、年齢3区分
- 文字コードと列名は`config/analysis.yaml`へ記録
- 秘匿、欠損、対象外、実数ゼロを変更しない
- 対象モールの分析メッシュを十分に覆う地域を取得
- 調査年、統計表ID、取得日、出典、利用条件を記録

### `osm/`

- WGS84（EPSG:4326）のGeoJSON FeatureCollection
- 道路LineString、駅・バス停Point、駐車場Point/Polygon
- 各Featureに一意な`id`を推奨し、実データ検査では必須
- 分析半径に最近接探索用bufferを加えた範囲を取得
- ODbL、`© OpenStreetMap contributors`、取得日、加工内容を記録

### `commercial/`

- WGS84（EPSG:4326）のPoint/Polygon FeatureCollection
- `config/commercial.yaml`で分類できる必須タグ
- 各Featureに一意な`id`を推奨し、実データ検査では必須
- 収録対象カテゴリを`available_categories`へ明記
- 分析半径に最近接探索用bufferを加えた範囲を取得
- データ単位の商用利用可否、出典表示、改変・再配布条件を記録

## 検査

```bash
mall-validate-inputs --project-root .
mall-validate-inputs --project-root . --require-real
```

通常モードは同梱サンプルを検査し、サンプル利用を警告します。`--require-real`はサンプル、範囲不足、Feature ID不足をエラーとして実分析開始を防ぎます。
