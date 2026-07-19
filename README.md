# 连点成线

静态演示版发布目录。

这个目录只包含上线需要的文件：

- `index.html`
- `logo-a.png`
- `cards.json` / `cards-data.js`
- `map-data.js`：1648—1814前史阶段沿用1815底图作参照，1815、1880、1900、1914、1920、1930、1938与1945世界边界、1914—1918一战欧洲占领与新政治实体阶段，以及1938—1945二战欧洲阶段数据；1861意大利、1867奥匈、1871德意志帝国为页面基于1880轮廓制作并明确标注的局部近似层
- `ww1-map-SOURCE.md`：一战阶段图来源、地图编号和“正式国界/占领区/新政治实体”的精度说明
- `ww2-map-SOURCE.md`：二战欧洲阶段数据来源与精度说明
- `map-timeline-SOURCES.md`：地图时间轴总来源、关键日期和局部轮廓近似说明
- `map-world-1960-reference.geojson`：仅供1947印巴分治与1949中东停战线的轮廓近似使用
- `maplibre-gl.js` / `maplibre-gl.css`：地图渲染组件
- `historical-basemaps-LICENSE.txt` / `maplibre-LICENSE.txt`：第三方许可证

GitHub Pages 发布时选择从当前分支的根目录发布即可。

## 卡片数据编辑流程

`cards.json` 是卡片内容的唯一权威来源，`cards-data.js` 是供静态页面加载的自动生成文件。不要手工编辑 `cards-data.js`，也不要从它反向恢复或合并数据。

修改卡片时按以下顺序操作：

1. 只编辑 `cards.json`，并保留已有卡片 ID；修改标题或关系时同步维护双向关系。
2. 运行 `python3 tools/cards.py check`，完成结构、枚举、镜像字段、标签和全量关系检查。
3. 运行 `python3 tools/cards.py build`，从权威 JSON 确定性生成 `cards-data.js`。
4. 运行 `python3 tools/cards.py verify`，确认权威源合法且生成物没有漂移。
5. 审查两份文件的 diff 后再提交；不要只提交其中一份。

`python3 tools/cards.py` 默认执行只读的 `verify`。任何校验失败都会以非零状态退出；`build` 仅在 `cards.json` 完整通过校验后写入生成物，并使用同目录临时文件原子替换。
