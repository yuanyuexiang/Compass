"""探路工具：渲染一个动态站点，列出它调用的 XHR/JSON 接口（tech-design §4.1）。

摸清 JS 站点背后的数据接口后，往往可为它写一个纯 httpx 适配器（更稳更省），
或直接用 generic_browser 适配器渲染采集。

用法：uv run python scripts/dev_inspect.py <列表页网址>
"""

import sys


def main(url: str) -> None:
    from app.crawler import browser

    if not browser.available():
        print("未安装 playwright，无法探路")
        return
    print(f"渲染并监听网络请求：{url}\n")
    apis = browser.discover_apis(url)
    if not apis:
        print("未捕获到 XHR/fetch 接口（可能是纯静态页，用 httpx 的 generic 适配器即可）")
    else:
        print(f"捕获到 {len(apis)} 个数据接口：")
        for a in apis:
            print(f"  [{a['status']}] {a['method']:4s} {a['url']}")
    browser.shutdown()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法：uv run python scripts/dev_inspect.py <列表页网址>")
        sys.exit(1)
    main(sys.argv[1])
