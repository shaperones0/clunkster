"""Readme generator."""


from pathlib import Path
from scripts import doc_parse, doc_extract, doc_patch


@doc_patch.template()
def readme_txt():
    file_main = Path(__file__).parent.parent / 'main.py'
    lines_main = file_main.read_text(encoding='utf-8').splitlines()
    snips = doc_extract.extract(doc_parse.parse(lines_main))
    return f"""
Hi there!
{snips['MAIN_EX_START']}
"""


if __name__ == '__main__':
    print(readme_txt())
