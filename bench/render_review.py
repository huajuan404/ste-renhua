#!/usr/bin/env python3
"""把冻结改写试验中的模型争议转成可人工裁决的对照。私有内容只写入指定本地目录。"""
import argparse
import json
from pathlib import Path

import rewrite


def build(src, out):
    src, out = Path(src).resolve(), Path(out).resolve()
    manifest = rewrite.manifest(src)
    cases = [{key: c[key] for key in ('id', 'text')} for c in manifest['cases']]
    for case in cases:
        first_line = case['text'].splitlines()[0].replace('**', '').strip()
        case['title'] = case['id'] + ' · ' + first_line[:36] + ('…' if len(first_line) > 36 else '')
    drafts, issues = [], []
    for stem, case, gen in rewrite.drafts(src, manifest):
        drafts.append({'stem': stem, 'case': gen['case'], 'cond': gen['cond'], 'run': gen['run'], 'text': gen['text']})
        units = {u['id']: u for u in case['units']}
        for model in manifest['judges']:
            result = rewrite.engine.load(src / rewrite.VERSION / f'{stem}__{model}.json')
            if result['manifest_hash'] != manifest['hash'] or result['text_hash'] != gen['text_hash']:
                raise ValueError('判分与冻结原稿/成稿不一致')
            rewrite.validate_judgment(result, case, gen['text'])
            for item in result['units']:
                if item['status'] == 'kept':
                    continue
                unit = units[item['id']]
                issues.append({'stem': stem, 'case': case['id'], 'cond': gen['cond'], 'model': model,
                               'kind': item['status'], 'unit_id': item['id'], 'unit_text': unit['text'],
                               'original_quote': unit['quote'], 'quote': item['quote'], 'note': item.get('note', '')})
            for kind, field, prefix in [('addition', 'additions', 'A'), ('unlisted', 'unlisted', 'X')]:
                for i, item in enumerate(result[field], 1):
                    issues.append({'stem': stem, 'case': case['id'], 'cond': gen['cond'], 'model': model,
                                   'kind': item.get('status', kind), 'unit_id': f'{prefix}{i}', 'unit_text': '',
                                   'original_quote': item.get('original_quote', ''), 'quote': item['quote'],
                                   'note': item.get('note', '')})
    if not issues:
        raise ValueError('这批输出没有待裁决的信息变化')
    for i, issue in enumerate(issues, 1):
        issue['id'] = f'D{i:02d}'
    out.mkdir(parents=True, exist_ok=True)
    data = {'manifest_hash': manifest['hash'], 'cases': cases, 'drafts': drafts, 'issues': issues,
            'data_path': str(out / 'review-data.json')}
    data['review_data_hash'] = rewrite.digest(data)
    payload = json.dumps(data, ensure_ascii=False).replace('<', '\\u003c').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')
    template = Path(__file__).with_name('review.html').read_text(encoding='utf-8')
    fragment = template.replace('__REVIEW_DATA__', payload)
    if len(fragment.encode()) >= 1_000_000:
        raise ValueError('对照超过 1 MB，请缩小原稿集合')
    rewrite.engine.save(out / 'review-data.json', data)
    path = out / 'rewrite-adjudication.html'
    path.write_text(fragment, encoding='utf-8')
    print(f'{len(issues)} 处标记，涉及 {len({x["stem"] for x in issues})} 篇改写稿：{path}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--from', dest='src', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    try:
        build(args.src, args.out)
    except (ValueError, KeyError, FileNotFoundError) as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()
