from app.crawler.adapters.ccgp import CcgpAdapter

DETAIL_HTML = """
<html><body><div class="vF_detail_content">
  <p>公告正文</p>
  <a href="/attach/招标文件.pdf">招标文件.pdf</a>
  <a href="http://download.example.com/files/resp.docx">响应文件模板</a>
  <a href="/attach/招标文件.pdf#page=1">重复链接</a>
  <a href="/page/other.htm">普通页面链接</a>
</div></body></html>
"""


def test_extract_attachments_by_extension_and_dedup():
    adapter = CcgpAdapter()
    links = adapter.extract_attachments(DETAIL_HTML, "https://www.ccgp.gov.cn/cggg/zygg/x.htm")
    assert len(links) == 2
    assert links[0].url == "https://www.ccgp.gov.cn/attach/招标文件.pdf"
    assert links[0].filename == "招标文件.pdf"
    assert links[1].filename == "响应文件模板"


def test_extract_attachments_none():
    adapter = CcgpAdapter()
    assert adapter.extract_attachments("<html><body>无附件</body></html>", "https://x.cn/") == []
