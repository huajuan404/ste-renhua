#!/usr/bin/env python3
"""生成整篇编辑质量对照；正文预渲染，私有内容仅写入指定本地目录。"""
import argparse
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re

import rewrite


def inline(text):
    parts = re.split(r'(`[^`\n]+`|\*\*[^*\n]+\*\*)', text)
    return ''.join('<code>' + escape(p[1:-1]) + '</code>' if p.startswith('`') and p.endswith('`')
                   else '<strong>' + escape(p[2:-2]) + '</strong>' if p.startswith('**') and p.endswith('**')
                   else escape(p) for p in parts)


def markdown(text, counterpart):
    """本试验正文的有限 Markdown 子集；原文另以逐字文本保留。"""
    lines = text.splitlines()
    other = {line.strip() for line in counterpart.splitlines()}
    result, i = [], 0
    def css(block):
        return ' class="edited"' if any(line.strip() not in other for line in block) else ''
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if i + 1 < len(lines) and line.strip().startswith('|') and re.fullmatch(r'[\s|:\-]+', lines[i + 1]) and '-' in lines[i + 1]:
            def cells(row, tag):
                return ''.join(f'<{tag}>{inline(cell.strip())}</{tag}>' for cell in row.strip().strip('|').split('|'))
            table = ['<div class="table-scroll"><table><thead><tr>' + cells(line, 'th') + '</tr></thead><tbody>']
            i += 2
            while i < len(lines) and lines[i].strip().startswith('|'):
                table.append('<tr' + css([lines[i]]) + '>' + cells(lines[i], 'td') + '</tr>')
                i += 1
            result.append(''.join(table) + '</tbody></table></div>')
            continue
        heading = re.match(r'^(#{1,6})\s+(.+)$', line)
        if heading:
            level = min(6, len(heading[1]) + 1)
            result.append(f'<h{level}{css([line])}>{inline(heading[2])}</h{level}>')
            i += 1
            continue
        listing = re.match(r'^(?:[-*]|\d+\.)\s+(.+)$', line)
        if listing:
            ordered = bool(re.match(r'^\d+\.', line))
            tag = 'ol' if ordered else 'ul'
            items = []
            while i < len(lines):
                match = re.match(r'^(\d+\.|[-*])\s+(.+)$', lines[i])
                if not match or bool(re.match(r'\d', match[1])) != ordered:
                    break
                items.append('<li' + css([lines[i]]) + '>' + inline(match[2]) + '</li>')
                i += 1
            result.append(f'<{tag}>' + ''.join(items) + f'</{tag}>')
            continue
        block = [line]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(r'^(?:#|\||[-*]\s|\d+\.\s)', lines[i]):
            block.append(lines[i])
            i += 1
        result.append('<p' + css(block) + '>' + '<br>'.join(inline(x) for x in block) + '</p>')
    return ''.join(result)


def length(text):
    return len(re.sub(r'\s', '', text))


def build(src, out):
    src, out = Path(src).resolve(), Path(out).resolve()
    manifest = rewrite.manifest(src)
    variants = []
    conditions = {c['id']: c for c in manifest['conditions']}
    for stem, case, gen in rewrite.drafts(src, manifest):
        if gen['cond'] == 'identity':
            continue
        checks = []
        units = {u['id']: u for u in case['units']}
        for model in manifest['judges']:
            judgment = rewrite.engine.load(src / rewrite.VERSION / f'{stem}__{model}.json')
            if judgment['manifest_hash'] != manifest['hash'] or judgment['text_hash'] != gen['text_hash']:
                raise ValueError('判分与冻结成稿不一致')
            rewrite.validate_judgment(judgment, case, gen['text'])
            for item in judgment['units']:
                if item['status'] != 'kept':
                    checks.append({'model': model, 'kind': item['status'], 'original_quote': units[item['id']]['quote'], **item})
            for field in ['unlisted', 'additions']:
                for item in judgment[field]:
                    checks.append({'model': model, 'kind': field, **item})
        condition = conditions[gen['cond']]
        variants.append({'id': stem, 'case': case['id'], 'label': condition.get('label', gen['cond']),
                         'original': case['text'], 'text': gen['text'], 'text_hash': gen['text_hash'],
                         'models': gen['meta'].get('models', []), 'checks': checks,
                         'source': condition.get('repo', ''), 'commit': condition.get('commit', ''),
                         'original_length': length(case['text']), 'length': length(gen['text']),
                         'unchanged': gen['text'] == case['text']})
    if not variants:
        raise ValueError('没有改写稿可供审阅')
    data = {'manifest_hash': manifest['hash'], 'variants': variants, 'judges': manifest['judges']}
    data['review_data_hash'] = rewrite.digest(data)
    articles, index = [], []
    fields = {'concision': ('简洁程度', [('better', '更简洁'), ('same', '差不多'), ('worse', '更冗长')]),
              'clarity': ('好懂程度', [('better', '更好懂'), ('same', '差不多'), ('worse', '更难懂')]),
              'fidelity': ('信息和语气', [('same', '未发现变化'), ('changed', '有变化'), ('uncertain', '不确定')]),
              'acceptance': ('是否采用', [('yes', '愿意用这版'), ('no', '仍用原稿')])}
    for v in variants:
        ident = v['id']
        label = escape(v['label'])
        delta = v['length'] - v['original_length']
        delta_label = f'{delta:+d} 字（{delta / v["original_length"]:+.1%}）' if delta else '字数不变'
        state = '逐字未改，没有编辑收益' if v['unchanged'] else '待你判断编辑收益'
        index.append(f'<a href="#{ident}" data-nav="{ident}">{label}<small>{v["length"]} 字 · {escape(delta_label)}</small></a>')
        flags = []
        for check in v['checks']:
            flags.append('<li><p>' + escape(check.get('note', '')) + '</p>'
                         + ('<div><span>原稿</span> ' + escape(check['original_quote']) + '</div>' if check.get('original_quote') else '')
                         + ('<div><span>改写</span> ' + escape(check['quote']) + '</div>' if check.get('quote') else '') + '</li>')
        judge_text = (f'模型标出 {len(flags)} 处可能的信息变化，尚未经人工确认。' if flags
                      else '模型未标出信息变化；这不代表已通过人工验收。')
        assessment = ''.join(f'<fieldset><legend>{title}</legend>' + ''.join(
            f'<button type="button" data-field="{field}" data-value="{value}" aria-pressed="false">{name}</button>'
            for value, name in options) + '</fieldset>' for field, (title, options) in fields.items())
        source_link = (f'<a href="{escape(v["source"], quote=True)}/blob/{escape(v["commit"], quote=True)}/SKILL.md" target="_blank" rel="noreferrer">来源规则 ↗</a>' if v['source'].startswith('https://github.com/') else '')
        articles.append(f'''<article class="variant" id="{ident}" data-variant="{ident}">
<header class="variant-head"><h2>{label}</h2><p>{v['original_length']} → <b>{v['length']}</b> 字 <span class="delta {'longer' if delta > 0 else ''}">{escape(delta_label)}</span> · {state}</p></header>
<div class="comparison"><section><div class="column-label">原稿 <small>{v['original_length']} 字</small></div><div class="prose">{markdown(v['original'], v['text'])}</div></section>
<section><div class="column-label">改写稿 <small>{v['length']} 字</small></div><div class="prose">{markdown(v['text'], v['original'])}</div></section></div>
<details class="evidence"><summary>模型的核对意见 · {len(flags)} 处标记</summary><p>{judge_text}</p><ol>{''.join(flags)}</ol></details>
<section class="assessment"><h3>你的 review</h3><div class="fields">{assessment}</div><label>具体意见（可选）<textarea data-note rows="3" maxlength="600" placeholder="哪处变好了，或哪处仍然不好？"></textarea></label></section>
<details class="provenance"><summary>规则来源与逐字正文</summary><p>{source_link} · 本轮追加简洁、保真和只交正文的要求。生成：{escape(', '.join(v['models']))}；核对：{escape(', '.join(data['judges']))}。</p><div class="comparison"><label>原稿逐字文本<textarea readonly rows="8">{escape(v['original'])}</textarea></label><label>模型逐字输出<textarea readonly rows="8">{escape(v['text'])}</textarea></label></div></details></article>''')
    template = Path(__file__).with_name('editor-review.html').read_text()
    payload = json.dumps(data, ensure_ascii=False).replace('<', '\\u003c').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')
    page = template.replace('__INDEX__', ''.join(index)).replace('__ARTICLES__', ''.join(articles)).replace('__DATA__', payload)
    out.mkdir(parents=True, exist_ok=True)
    rewrite.engine.save(out / 'editor-review-data.json', data)
    path = out / 'editor-review.html'
    path.write_text(page, encoding='utf-8')
    print(f'{len(variants)} 篇候选，全文对照：{path}', flush=True)
    return path


def serve(path):
    """只提供当前页面，不开放所在私有目录。"""
    class Page(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path not in ['/', '/editor-review.html']:
                self.send_error(404)
                return
            content = path.read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(content)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(content)
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Page)
    print(f'本地预览：http://127.0.0.1:{server.server_port}/', flush=True)
    server.serve_forever()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--from', dest='src', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--serve', action='store_true')
    args = parser.parse_args()
    try:
        path = build(args.src, args.out)
        if args.serve:
            serve(path)
    except (ValueError, KeyError, FileNotFoundError) as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()
