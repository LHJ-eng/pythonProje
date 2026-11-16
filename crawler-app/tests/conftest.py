from __future__ import annotations

import pytest

from app.auth import hash_password
from app.config import Settings


SAMPLE_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>示例商品列表</title></head>
<body>
  <nav><a href="/">首页</a></nav>
  <table id="products">
    <thead>
      <tr><th>名称</th><th>价格</th><th>库存</th></tr>
    </thead>
    <tbody>
      <tr><td>苹果</td><td>5.50</td><td>100</td></tr>
      <tr><td>香蕉</td><td>3.20</td><td>80</td></tr>
      <tr><td>橙子</td><td>4.10</td><td>60</td></tr>
    </tbody>
  </table>
  <div class="product">
    <h2>商品 A</h2>
    <a href="/p/1">查看详情</a>
    <span class="price">¥9.9</span>
  </div>
  <div class="product">
    <h2>商品 B</h2>
    <a href="/p/2">查看详情</a>
    <span class="price">¥19.9</span>
  </div>
  <article>
    <h1>一篇示例文章</h1>
    <p>这是用于测试正文抽取功能的段落，内容需要足够长，才能通过正文启发式规则的长度阈值判断。</p>
    <p>DataHarvester 会把网页正文、标题、作者与发布时间整理为一行结构化数据，方便后续导出分析。</p>
  </article>
</body>
</html>
"""


@pytest.fixture
def settings(tmp_path):
    return Settings(
        data_dir=tmp_path,
        password_hash=hash_password("correct-password"),
        secret_key=b"test-secret-key-0123456789abcdef",
        max_rows=1000,
    )
