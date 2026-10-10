#!/usr/bin/env python3
"""把多个冻结批次的合格候选汇成一页，不更改原运行清单或模型正文。"""
import argparse
import json
from pathlib import Path
import re

import render_editor_review as review
import rewrite
import screen_rewrite as screen


def previous_conflicts(src, manifest, drafts):
    """同一成稿有未解决的旧保真标记时，不靠一次新判分放行。"""
    conflicts = {}
    for stem, case, gen in drafts:
        if gen['cond'] == 'identity':
            continue
        for path in src.glob('screen-v*/' + stem + '.json'):
            if path.parent.name == screen.VERSION:
                continue
            result = rewrite.engine.load(path)
            if result.get('manifest_hash') != manifest['hash'] or result.get('text_hash') != gen['text_hash']:
                continue
            policy = rewrite.engine.load(path.parent / 'policy.json')
            if (policy['manifest_hash'] != manifest['hash']
                    or policy['rules_hash'] != rewrite.digest(policy['rules'])
                    or result['rules_hash'] != policy['rules_hash']):
                raise ValueError('旧预筛的依据与冻结规则不一致')
            if policy['rules']['fidelity_prompt'] != rewrite.JUDGE_PROMPT:
                raise ValueError('旧保真检查提示不同，不能自动裁决历史争议')
            rewrite.validate_judgment(result['fidelity'], case, gen['text'])
            if screen.information_changes(result['fidelity']):
                conflicts.setdefault(stem, []).append({'version': path.parent.name, 'result_hash': rewrite.digest(result)})
    return conflicts


def build(sources, out):
    out = Path(out).resolve()
    sources = [Path(src).resolve() for src in sources]
    if not sources or len(set(sources)) != len(sources):
        raise ValueError('批次清单为空或重复')
    bindings, variants, indexes, articles, judges = [], [], [], [], set()
    total = 0
    for i, src in enumerate(sources, 1):
        manifest = rewrite.manifest(src)
        drafts = rewrite.drafts(src, manifest)
        _, qualification = review.qualified_drafts(src, manifest, drafts)
        conflicts = previous_conflicts(src, manifest, drafts)
        total += qualification['total_candidates']
        binding = {'manifest_hash': manifest['hash'], **qualification, 'review_data_hash': None,
                   'unresolved_fidelity_conflicts': conflicts}
        try:
            path = review.build(src, out / 'batches' / str(i), scope='mixed', qualified_only=True)
        except ValueError as error:
            if str(error) != '没有改写稿可供审阅':
                raise
            bindings.append(binding)
            continue
        data = rewrite.engine.load(path.with_name('editor-review-data.json'))
        if data['review_data_hash'] != rewrite.digest({k: v for k, v in data.items() if k != 'review_data_hash'}):
            raise ValueError('批次 review 数据哈希不一致')
        binding['review_data_hash'] = data['review_data_hash']
        bindings.append(binding)
        retained = [v for v in data['variants'] if v['id'] not in conflicts]
        variants.extend({**v, 'source_manifest_hash': manifest['hash']} for v in retained)
        judges.update(data['judges'])
        page = path.read_text()
        index = re.search(r'<nav aria-label="候选索引">(.*?)</nav>', page, re.S)[1]
        start = page.index('<article class="variant"')
        body = page[start:page.index('\n<div id="summary"', start)]
        for ident in conflicts:
            index = re.sub(r'<a href="#' + re.escape(ident) + r'"[^>]*>.*?</a>', '', index, flags=re.S)
            body = re.sub(r'<article class="variant" id="' + re.escape(ident) + r'"[^>]*>.*?</article>', '', body, flags=re.S)
        indexes.append(index)
        articles.append(body)
    if not variants:
        raise ValueError('没有合格候选可供审阅')
    if len({v['id'] for v in variants}) != len(variants):
        raise ValueError('跨批次候选 ID 重复，不能混合 review 记录')
    data = {'manifest_kind': 'review_collection', 'manifest_hash': rewrite.digest(bindings),
            'source_reviews': bindings, 'variants': variants, 'judges': sorted(judges), 'scope': 'mixed',
            'qualification': {'total_candidates': total, 'qualified_candidates': len(variants)}}
    data['review_data_hash'] = rewrite.digest(data)
    payload = json.dumps(data, ensure_ascii=False).replace('<', '\\u003c').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')
    note = (f'<p class="hint">共试 {total} 篇，只有 {len(variants)} 篇通过内部检查并进入本页；仍待你判断是否采用。</p>'
            '<p class="hint">每篇标明“完整回复”或“连续小节”；片段的评价和字数变化不代表整篇效果。</p>')
    values = {'__INDEX__': ''.join(indexes), '__ARTICLES__': '\n'.join(articles),
              '__DATA__': payload, '__SCOPE__': '内容', '__SCOPE_NOTE__': note}
    template = Path(review.__file__).with_name('editor-review.html').read_text()
    page = re.sub(r'__(?:INDEX|ARTICLES|DATA|SCOPE|SCOPE_NOTE)__', lambda m: values[m.group()], template)
    out.mkdir(parents=True, exist_ok=True)
    rewrite.engine.save(out / 'editor-review-data.json', data)
    path = out / 'editor-review.html'
    path.write_text(page, encoding='utf-8')
    print(f'{len(variants)} 篇合格候选 / {total} 篇试跑：{path}', flush=True)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--from', dest='sources', nargs='+', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--serve', action='store_true')
    args = parser.parse_args()
    try:
        path = build(args.sources, args.out)
        if args.serve:
            review.serve(path)
    except (ValueError, KeyError, TypeError, FileNotFoundError) as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()
