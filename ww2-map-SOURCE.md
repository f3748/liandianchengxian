# 二战欧洲边界数据来源

数据来自 Stanford Spatial History Lab 为 Holocaust Geographies Project 制作并通过 ArcGIS FeatureServer 公开提供的 `WWII_Borders_April_1938` 至 `WWII_Borders_April_1945` 图层。

- 服务目录：https://services6.arcgis.com/HvbabY0grzgZwGW1/ArcGIS/rest/services
- 研究说明：Michael De Groot, *Building the New Order: 1938-1945*
- 支持机构：Stanford Spatial History Lab、United States Holocaust Memorial Museum、Center for Advanced Holocaust Studies
- 本地获取日期：2026-07-13

使用限制与解释：

- 原数据按月记录欧洲正式吞并和政治实体变化，并附有结盟、占领与中立状态。
- 它不是逐日军事前线数据，不能表示每一支军队的实时推进位置。
- 网站试验版使用每年4月快照，并在波兰战役等关键节点采用阶段切换；页面必须明确称为“阶段图”或“边界与占领状态”，不能声称逐日精确。
- 本地请求时使用 `outSR=4326`、`maxAllowableOffset=0.03` 和 `geometryPrecision=4` 进行网页显示所需的简化。
