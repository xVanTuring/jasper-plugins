# joplin-theme

让 [Jasper](https://github.com/jasper-note/jasper) 看起来像原生 Joplin 的主题插件。
纯 CSS，**不申请任何权限**，包内只有 `manifest.toml` + 两份 `.css`。

一个插件贡献两个主题：

| 主题 id | 名称 | base | 说明 |
|---|---|---|---|
| `joplin-light` | Joplin 浅色 | light | 白底内容区 + 浅灰侧栏 + Joplin 品牌蓝 |
| `joplin-dark`  | Joplin 深色 | dark  | `#1D2024` 内容区 + `#181A1D` 侧栏 + `#2D3136` 顶栏 |

配色 **逐令牌取自 Joplin 官方主题源码**
（`joplin/packages/lib/themes/light.ts` 与 `dark.ts`），CSS 注释里标注了每个令牌
对应的 Joplin 字段（`backgroundColor` / `headerBackgroundColor` /
`colorFaded` …），方便日后对着上游同步。

## 一个机制上的取舍

Joplin **浅色**主题的侧边栏是「深蓝灰底 + 白字」(`backgroundColor2 #313640`)，
但 Jasper 的侧栏与内容区共用同一个 `--text` 语义令牌，没有独立的侧栏文字色，
无法复刻这种反差侧栏。因此浅色版做成「通体浅色」：内容区忠实还原（白底深字），
侧栏改用 Joplin 的 `backgroundColor3`(`#F4F5F6`) 浅灰以保证深色文字可读。
深色版不受此限，三层背景（内容/顶栏/侧栏）与 Joplin 高度一致。

主题只覆盖 [plugin-spec §9.1](https://github.com/jasper-note/jasper/blob/main/docs/plugin-spec.md)
的**颜色语义令牌**，未覆盖的令牌回退到 `base` 基调默认值；不依赖任何内部 class 选择器。

## 安装

从 Release 下载 `joplin-theme-<version>.jplug`，在 Jasper：顶栏 → 插件图标 →
安装 → 选文件 → 启用（纯主题不涉及能力授权）。启用后到主题切换处选
「Joplin 浅色」或「Joplin 深色」。

## 本地打包

无需 Rust / wasm，纯 CSS：

```sh
python3 scripts/package.py joplin-theme          # 校验 + 出 dist/joplin-theme-<version>.jplug
python3 scripts/package.py joplin-theme --check  # 只校验 manifest
```

## 调色

改 `themes/joplin-light.css` / `themes/joplin-dark.css` 里的令牌值即可，
选择器固定为 `:root[data-theme='joplin-light'|'joplin-dark']`。

## License

MIT OR Apache-2.0，随仓库。
