"""Print the built docs site into a single PDF.

Usage: ``python -m scripts.pdf <site dir> <pdf file>``.

Pages are taken in the order of the site's navigation, their articles put
into one document (ids prefixed per page, so they stay unique), and links
between pages, code links included, pointed to anchors within it. Chromium
prints it with the site's own stylesheets.
"""

import sys
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

# pages, in navigation order: every page link of the primary navigation
JS_PAGES = """() => {
    const pages = [];
    for (const a of document.querySelectorAll(
        '.md-nav--primary a.md-nav__link[href]'
    )) {
        const url = new URL(a.href);
        url.hash = '';
        if (url.pathname.endsWith('/')) url.pathname += 'index.html';
        if (url.protocol === 'file:' && !pages.includes(url.href)) {
            pages.push(url.href);
        }
    }
    return pages;
}"""

# article of the current page, rewritten for the document
JS_ARTICLE = """([prefixes, prefix]) => {
    const article = document
        .querySelector('article.md-content__inner')
        .cloneNode(true);
    article
        .querySelectorAll('.headerlink, .md-content__button, .md-source-file')
        .forEach(el => el.remove());
    article.querySelectorAll('[id]')
        .forEach(el => { el.id = `${prefix}--${el.id}`; });
    for (const img of article.querySelectorAll('img[src]')) {
        img.setAttribute('src', img.src);
    }
    for (const a of article.querySelectorAll('a[href]')) {
        const url = new URL(a.getAttribute('href'), location.href);
        if (url.protocol !== 'file:') continue;
        const hash = decodeURIComponent(url.hash.slice(1));
        url.hash = '';
        if (url.pathname.endsWith('/')) url.pathname += 'index.html';
        const target = prefixes[url.href];
        if (target === undefined) {
            // a file of the site, not a page: there's nothing to point to
            a.removeAttribute('href');
        } else {
            a.setAttribute('href', `#${target}${hash ? `--${hash}` : ''}`);
        }
    }
    return article.outerHTML;
}"""

# head of the document: the site's stylesheets, and how the body looks
JS_HEAD = """() => ({
    styles: [...document.querySelectorAll('link[rel="stylesheet"]')]
        .map(link => link.href),
    body: [...document.body.attributes]
        .map(attr => `${attr.name}="${attr.value}"`).join(' '),
})"""

PRINT_CSS = """
@page { size: A4; margin: 16mm 14mm; }
html, body { background: white; }
.pdf-page { break-before: page; }
.pdf-page:first-child { break-before: auto; }
.md-typeset h1, .md-typeset h2, .md-typeset h3, .md-typeset h4 {
    break-after: avoid;
}
/* code isn't scrollable on paper */
.md-typeset pre > code {
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    overflow: visible;
    max-height: none;
}
.md-typeset table:not([class]) { display: table; }
.md-typeset details { display: block; }
.md-typeset details > :not(summary) { display: block; }
"""


def collect(page: Page, site: Path) -> tuple[str, list[str]]:
    """Collect the document's head and the articles of all pages."""
    page.goto((site / 'index.html').as_uri(), wait_until='load')
    urls = [str(url) for url in page.evaluate(JS_PAGES)]
    head = page.evaluate(JS_HEAD)
    styles = ''.join(
        f'<link rel="stylesheet" href="{href}">' for href in head['styles']
    )
    body = str(head['body'])
    prefixes = {url: f'p{i}' for i, url in enumerate(urls)}
    articles: list[str] = []
    for url in urls:
        page.goto(url, wait_until='load')
        article = str(page.evaluate(JS_ARTICLE, [prefixes, prefixes[url]]))
        articles.append(
            f'<section class="pdf-page" id="{prefixes[url]}">'
            f'{article}</section>'
        )
    document = (
        '<!doctype html><html><head><meta charset="utf-8">'
        f'{styles}<style>{PRINT_CSS}</style></head><body {body}>'
        '<div class="md-container"><main class="md-main">'
        f'<div class="md-content">{"".join(articles)}</div>'
        '</main></div></body></html>'
    )
    return document, urls


def main() -> None:
    """Print the site."""
    site = Path(sys.argv[1]).resolve()
    file_pdf = Path(sys.argv[2]).resolve()
    # the document lives in the site while printing, so that it can load the
    #  site's files
    file_html = site / '_pdf.html'
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        document, urls = collect(page, site)
        try:
            file_html.write_text(document, encoding='utf-8')
            page.goto(file_html.as_uri(), wait_until='networkidle')
            page.emulate_media(media='print')
            page.pdf(
                path=file_pdf,
                print_background=True,
                prefer_css_page_size=True,
                outline=True,
                tagged=True,
                display_header_footer=True,
                header_template='<span></span>',
                footer_template=(
                    '<div style="font-size:8px;width:100%;text-align:center">'
                    '<span class="pageNumber"></span></div>'
                ),
            )
        finally:
            file_html.unlink(missing_ok=True)
            browser.close()
    print(f'{len(urls)} pages printed into {file_pdf}')


if __name__ == '__main__':
    main()
